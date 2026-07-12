# Copyright (c) 2026, Sydney Kibanga and contributors
# For license information, please see license.txt

from textwrap import dedent
import secrets
import string

import frappe
from frappe.model.document import Document


class NasDevice(Document):
	pass


@frappe.whitelist()
def generate_opennds_fas_key(name: str | None = None) -> dict:
	"""
	Generate a new shared secret for openNDS secure FAS.
	Stores it on the Nas Device record when a document name is provided.
	"""
	alphabet = string.ascii_letters + string.digits
	key = "".join(secrets.choice(alphabet) for _ in range(16))

	if name:
		doc = frappe.get_doc("Nas Device", name)
		doc.opennds_fas_key = key
		doc.save(ignore_permissions=True)
		frappe.db.commit()

	return {"ok": True, "opennds_fas_key": key}


def _render_openwrt_hardening_bundle(hotspot_iface: str = "br-lan", conn_limit: int = 150, ttl_value: int = 64) -> str:
	hotspot_iface = (hotspot_iface or "br-lan").strip()
	conn_limit = max(1, int(conn_limit or 150))
	ttl_value = max(1, min(int(ttl_value or 64), 255))

	return dedent(
		f"""\
		#!/bin/sh
		set -eu

		# Hotspot hardening bundle for OpenWrt firewall4 / nftables.
		# Apply client isolation, then install a fragment that fw4 includes inside table inet fw4 for:
		# - per-client new-connection throttle
		# - TTL normalization as a heuristic anti-tethering layer

		HOTSPOT_IFACE="{hotspot_iface}"
		CONN_LIMIT="{conn_limit}"
		TTL_VALUE="{ttl_value}"
		OUT_FILE="${{1:-/usr/share/nftables.d/table-pre/99-hotspot-hardening.nft}}"

		mkdir -p "$(dirname "$OUT_FILE")"

		cat >"$OUT_FILE" <<EOF
		chain hotspot_hardening {{
		  type filter hook prerouting priority mangle; policy accept;

		  # Throttle excessive new connections from a single guest IP.
		  # This is a loadable meter-based control, not a simultaneous-connection counter.
		  iifname "$HOTSPOT_IFACE" ct state new meter hotspot_newconn {{ ip saddr limit rate over ${CONN_LIMIT}/minute }} counter drop

		  # Normalize TTL for guest traffic. This is a heuristic, not a guarantee.
		  iifname "$HOTSPOT_IFACE" ip ttl 63 ip ttl set $TTL_VALUE
		}}
		EOF

		changed=0
		for section in $(uci show wireless 2>/dev/null | sed -n 's/^wireless\\.\\([^=]*\\)=wifi-iface$/\\1/p'); do
		  if uci -q set "wireless.$section.isolate='1'"; then
		    changed=1
		  fi
		done
		if [ "$changed" -eq 1 ]; then
		  uci commit wireless
		fi

		echo "Wrote nftables snippet to: $OUT_FILE"
		echo "Reload firewall: /etc/init.d/firewall restart"
		echo "Reload wifi if needed: wifi reload"
		"""
	).strip() + "\n"


@frappe.whitelist()
def generate_openwrt_hardening_bundle(name: str | None = None, hotspot_iface: str = "br-lan", conn_limit: int = 150, ttl_value: int = 64) -> dict:
	"""
	Generate a deployable OpenWrt hardening script for the selected NAS.
	"""
	bundle = _render_openwrt_hardening_bundle(hotspot_iface=hotspot_iface, conn_limit=conn_limit, ttl_value=ttl_value)

	return {"ok": True, "bundle": bundle}


@frappe.whitelist()
def generate_openwrt_provisioning_script(name: str) -> dict:
	doc = frappe.get_doc("Nas Device", name)
	site_url = frappe.utils.get_url()
	nas_id = doc.short_name or doc.device_name

	script = f"""#!/bin/sh
set -eu

echo "=========================================="
echo " Starting OpenWrt Provisioning Script"
echo " Device: {doc.device_name} ({doc.ip_address})"
echo "=========================================="

echo "1. Installing required packages..."
apk update || true
apk add kmod-usb-net-rtl8152 kmod-usb-net-asix || true

echo "2. Configuring Network..."
uci set network.lan.ipaddr='{doc.ip_address}'
uci commit network

echo "3. Configuring OpenNDS..."
uci set opennds.@opennds[0].gatewayport='{doc.opennds_gateway_port}'
uci set opennds.@opennds[0].faskey='{doc.opennds_fas_key}'
uci set opennds.@opennds[0].max_clients_per_token='1'
uci set opennds.@opennds[0].login_option_enabled='3'
uci set opennds.@opennds[0].theme_spec_path='/usr/lib/opennds/theme_click-to-continue.sh'

# Clear and rebuild preauthenticated_users
uci delete opennds.@opennds[0].preauthenticated_users || true
uci add_list opennds.@opennds[0].preauthenticated_users='allow udp port 53'
uci add_list opennds.@opennds[0].preauthenticated_users='allow tcp port 53'
uci add_list opennds.@opennds[0].preauthenticated_users='allow tcp port 443 to 157.173.109.148'
uci add_list opennds.@opennds[0].preauthenticated_users='allow tcp port 80 to 157.173.109.148'

uci commit opennds

echo "4. Creating Agent Configuration..."
cat << 'EOF' > /etc/hotspot_restore.conf
FRAPPE_BASE_URL="{site_url}"
NAS_IDENTIFIER="{nas_id}"
NAS_SECRET="{doc.shared_secret}"
EOF

echo "5. Installing Custom Theme and Worker Scripts..."

mkdir -p /usr/lib/opennds
cat << 'EOF' > /usr/lib/opennds/theme_click-to-continue.sh
#!/bin/sh
title="theme_click-to-continue"
generate_splash_sequence() {{
	echo "<!DOCTYPE html>
		<html>
		<head>
		<meta charset=\"utf-8\">
		<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">
		<title>Redirecting...</title>
		<script>
			var redirUrl = \"{site_url}/hotspot/login?fas=\$fas\";
			window.location.replace(redirUrl);
		</script>
		</head>
		<body style=\"background-color:#101622; color:white; font-family:sans-serif; text-align:center; padding-top:50px;\">
		<p>Redirecting to secure login portal...</p>
		</body>
		</html>
	"
}}
EOF
chmod +x /usr/lib/opennds/theme_click-to-continue.sh

# Script 1: Restore Active Clients
cat << 'EOF' > /usr/bin/hotspot_restore_active_clients.sh
#!/bin/sh
set -eu

FRAPPE_BASE_URL="${{FRAPPE_BASE_URL:-}}"
NAS_IDENTIFIER="${{NAS_IDENTIFIER:-}}"
NAS_SECRET="${{NAS_SECRET:-}}"
POLL_INTERVAL="${{POLL_INTERVAL:-15}}"
LOG_TAG="${{LOG_TAG:-hotspot-restore}}"
API_PATH="/api/method/hotspot_ms.api.portal.restore_active_access"

[ -f /etc/hotspot_restore.conf ] && . /etc/hotspot_restore.conf

require_cmd() {{
  command -v "$1" >/dev/null 2>&1 || {{
    echo "Missing required command: $1" >&2
    exit 1
  }}
}}

log() {{
  if command -v logger >/dev/null 2>&1; then
    logger -t "$LOG_TAG" -- "$*"
  else
    echo "$LOG_TAG: $*"
  fi
}}

urlencode() {{
  local s="$1"
  local out=""
  local i ch
  i=1
  while [ "$i" -le "${{#s}}" ]; do
    ch="$(printf '%s' "$s" | cut -c "$i")"
    case "$ch" in
      [a-zA-Z0-9.~_-]) out="${{out}}${{ch}}" ;;
      :) out="${{out}}%3A" ;;
      /) out="${{out}}%2F" ;;
      \?) out="${{out}}%3F" ;;
      \&) out="${{out}}%26" ;;
      =) out="${{out}}%3D" ;;
      +) out="${{out}}%2B" ;;
      @) out="${{out}}%40" ;;
      " ") out="${{out}}%20" ;;
      *) out="${{out}}${{ch}}" ;;
    esac
    i=$((i + 1))
  done
  printf '%s' "$out"
}}

fetch_restore_decision() {{
  local mac="$1"
  local ip="$2"
  local url

  url="${{FRAPPE_BASE_URL%/}}${{API_PATH}}?nas_identifier=$(urlencode "$NAS_IDENTIFIER")&secret=$(urlencode "$NAS_SECRET")&mac_address=$(urlencode "$mac")"
  if [ -n "$ip" ]; then
    url="${{url}}&ip_address=$(urlencode "$ip")"
  fi

  wget -qO- --timeout=15 "$url" 2>/dev/null || true
}}

extract_json_field() {{
  local payload="$1"
  local expr="$2"
  printf '%s' "$payload" | jsonfilter -e "$expr" 2>/dev/null || true
}}

restore_one_client() {{
  local ip="$1"
  local mac="$2"
  local token="$3"
  local payload allow minutes session_id voucher_code

  payload="$(fetch_restore_decision "$mac" "$ip")"
  [ -n "$payload" ] || return 0

  allow="$(extract_json_field "$payload" '@.message.allow')"
  [ "$allow" = "true" ] || return 0

  minutes="$(extract_json_field "$payload" '@.message.session_timeout_minutes')"
  session_id="$(extract_json_field "$payload" '@.message.session_id')"
  voucher_code="$(extract_json_field "$payload" '@.message.voucher_code')"

  case "$minutes" in
    ''|*[!0-9]*) minutes=1 ;;
  esac
  [ "$minutes" -gt 0 ] || minutes=1

  if ndsctl auth "$mac" "$minutes" "" "" "" "" "RESTORE|${{session_id}}|${{voucher_code}}" >/dev/null 2>&1; then
    log "restored mac=$mac ip=$ip token=$token session=$session_id minutes=$minutes voucher=$voucher_code"
    return 0
  fi

  if ndsctl auth "$mac" >/dev/null 2>&1; then
    log "restored mac=$mac ip=$ip token=$token session=$session_id via fallback auth"
    return 0
  fi

  log "failed to restore mac=$mac ip=$ip token=$token"
  return 1
}}

scan_preauth_clients() {{
  ndsctl status | awk '
    /^Client [0-9]+$/ {{ ip=""; mac=""; token=""; state=""; next }}
    /IP:/ {{
      for (i = 1; i <= NF; i++) {{
        if ($i == "IP:") ip = $(i + 1)
        if ($i == "MAC:") mac = $(i + 1)
      }}
      next
    }}
    /Token:/ {{ token = $2; next }}
    /State:/ {{
      state = $2
      if (state == "Preauthenticated" && mac != "") {{
        printf "%s\t%s\t%s\\n", ip, mac, token
      }}
      next
    }}
  '
}}

run_once() {{
  scan_preauth_clients | while IFS="$(printf '\\t')" read -r ip mac token; do
    [ -n "$mac" ] || continue
    restore_one_client "$ip" "$mac" "$token"
  done
}}

main() {{
  require_cmd ndsctl
  require_cmd wget
  require_cmd jsonfilter

  [ -n "$FRAPPE_BASE_URL" ] || {{ echo "FRAPPE_BASE_URL is required" >&2; exit 1; }}
  [ -n "$NAS_IDENTIFIER" ] || {{ echo "NAS_IDENTIFIER is required" >&2; exit 1; }}
  [ -n "$NAS_SECRET" ] || {{ echo "NAS_SECRET is required" >&2; exit 1; }}

  if [ "${{1:-}}" = "--once" ]; then
    run_once
    exit 0
  fi

  while true; do
    run_once
    sleep "$POLL_INTERVAL"
  done
}}

main "$@"
EOF

# Script 2: Deauth Worker
cat << 'EOF' > /usr/bin/hotspot_deauth_worker.sh
#!/bin/sh
set -eu

FRAPPE_BASE_URL="${{FRAPPE_BASE_URL:-}}"
NAS_IDENTIFIER="${{NAS_IDENTIFIER:-}}"
NAS_SECRET="${{NAS_SECRET:-}}"
POLL_INTERVAL="${{POLL_INTERVAL:-30}}"
LOG_TAG="${{LOG_TAG:-hotspot-agent}}"

[ -f /etc/hotspot_restore.conf ] && . /etc/hotspot_restore.conf

require_cmd() {{
  command -v "$1" >/dev/null 2>&1 || {{
    echo "Missing required command: $1" >&2
    exit 1
  }}
}}

log() {{
  if command -v logger >/dev/null 2>&1; then
    logger -t "$LOG_TAG" -- "$*"
  else
    echo "$LOG_TAG: $*"
  fi
}}

urlencode() {{
  local s="$1"
  local out=""
  local i ch
  i=1
  while [ "$i" -le "${{#s}}" ]; do
    ch="$(printf '%s' "$s" | cut -c "$i")"
    case "$ch" in
      [a-zA-Z0-9.~_-]) out="${{out}}${{ch}}" ;;
      :) out="${{out}}%3A" ;;
      /) out="${{out}}%2F" ;;
      \?) out="${{out}}%3F" ;;
      \&) out="${{out}}%26" ;;
      =) out="${{out}}%3D" ;;
      +) out="${{out}}%2B" ;;
      @) out="${{out}}%40" ;;
      " ") out="${{out}}%20" ;;
      *) out="${{out}}${{ch}}" ;;
    esac
    i=$((i + 1))
  done
  printf '%s' "$out"
}}

scan_active_clients_usage() {{
  ndsctl status | awk '
    BEGIN {{
      first = 1
      printf "["
    }}
    /Client [0-9]+/ || /Client [0-9]+$/ {{
      ip=""
      mac=""
      token=""
      state=""
      datain=0
      dataout=0
      next
    }}
    /MAC:/ {{
      for (i = 1; i <= NF; i++) {{
        if ($i == "MAC:") mac = $(i + 1)
      }}
      next
    }}
    /State:/ {{ state = $2; next }}
    /Download this session:/ {{
      dataout = $4 * 1024
      next
    }}
    /Upload this session:/ {{
      datain = $4 * 1024
      if (state == "Authenticated" && mac != "") {{
        if (first == 0) {{
          printf ","
        }}
        printf "{{\"mac_address\":\"%s\",\"input_octets\":%s,\"output_octets\":%s}}", mac, datain, dataout
        first = 0
      }}
      next
    }}
    END {{
      printf "]"
    }}
  '
}}

sync_usage() {{
  local payload url response ok
  payload="$(scan_active_clients_usage)"
  [ -n "$payload" ] || return 0
  [ "$payload" != "[]" ] || return 0

  url="${{FRAPPE_BASE_URL%/}}/api/method/hotspot_ms.api.portal.sync_session_usage"
  response="$(wget -qO- --post-data="nas_identifier=$(urlencode "$NAS_IDENTIFIER")&secret=$(urlencode "$NAS_SECRET")&usage_data=$(urlencode "$payload")" --timeout=10 "$url" 2>/dev/null || true)"
  
  if [ -n "$response" ]; then
    ok="$(printf '%s' "$response" | jsonfilter -e '@.ok' 2>/dev/null || true)"
    if [ "$ok" = "true" ]; then
      log "synchronized usage data successfully"
      return 0
    fi
    log "sync failed with server response: $response"
    return 1
  fi
  return 1
}}

pull_and_apply_deauths() {{
  local url response actions_count i action_id session_id ip mac reason
  url="${{FRAPPE_BASE_URL%/}}/api/method/hotspot_ms.api.portal.pull_disconnect_actions?nas_identifier=$(urlencode "$NAS_IDENTIFIER")&secret=$(urlencode "$NAS_SECRET")"
  response="$(wget -qO- --timeout=10 "$url" 2>/dev/null || true)"
  [ -n "$response" ] || return 0

  actions_count="$(printf '%s' "$response" | jsonfilter -e '@.count' 2>/dev/null || echo "0")"
  [ "${{actions_count:-0}}" -gt 0 ] || return 0

  i=0
  while [ "$i" -lt "$actions_count" ]; do
    action_id="$(printf '%s' "$response" | jsonfilter -e "@.actions[$i].action_id" 2>/dev/null || true)"
    session_id="$(printf '%s' "$response" | jsonfilter -e "@.actions[$i].session_id" 2>/dev/null || true)"
    ip="$(printf '%s' "$response" | jsonfilter -e "@.actions[$i].ip_address" 2>/dev/null || true)"
    mac="$(printf '%s' "$response" | jsonfilter -e "@.actions[$i].mac_address" 2>/dev/null || true)"
    reason="$(printf '%s' "$response" | jsonfilter -e "@.actions[$i].reason" 2>/dev/null || true)"
    
    if [ -n "$mac" ]; then
      local deauth_note="deauth_ok"
      if ndsctl deauth "$mac" >/dev/null 2>&1; then
        log "deauthenticated mac=$mac ip=$ip session=$session_id reason=$reason"
      else
        deauth_note="already_offline"
      fi

      local ack_url
      ack_url="${{FRAPPE_BASE_URL%/}}/api/method/hotspot_ms.api.portal.acknowledge_disconnect_action?session_id=$(urlencode "$session_id")&nas_identifier=$(urlencode "$NAS_IDENTIFIER")&secret=$(urlencode "$NAS_SECRET")&result=ok&note=$(urlencode "$deauth_note")"
      wget -qO- --timeout=10 "$ack_url" >/dev/null 2>&1 || true
    fi
    i=$((i + 1))
  done
}}

main() {{
  require_cmd ndsctl
  require_cmd wget
  require_cmd jsonfilter

  [ -n "$FRAPPE_BASE_URL" ] || {{ echo "FRAPPE_BASE_URL is required" >&2; exit 1; }}
  [ -n "$NAS_IDENTIFIER" ] || {{ echo "NAS_IDENTIFIER is required" >&2; exit 1; }}
  [ -n "$NAS_SECRET" ] || {{ echo "NAS_SECRET is required" >&2; exit 1; }}

  log "started combined hotspot agent"

  while true; do
    sync_usage || true
    pull_and_apply_deauths || true
    sleep "$POLL_INTERVAL"
  done
}}

main "$@"
EOF

# Script 3: Sync Session Usage
cat << 'EOF' > /usr/bin/hotspot_sync_session_usage.sh
#!/bin/sh
set -eu

FRAPPE_BASE_URL="${{FRAPPE_BASE_URL:-}}"
NAS_IDENTIFIER="${{NAS_IDENTIFIER:-}}"
NAS_SECRET="${{NAS_SECRET:-}}"
POLL_INTERVAL="${{POLL_INTERVAL:-30}}"
LOG_TAG="${{LOG_TAG:-hotspot-sync}}"
API_PATH="/api/method/hotspot_ms.api.portal.sync_session_usage"
DEAUTH_API_PATH="/api/method/hotspot_ms.api.portal.pull_disconnect_actions"
ACK_API_PATH="/api/method/hotspot_ms.api.portal.acknowledge_disconnect_action"

[ -f /etc/hotspot_restore.conf ] && . /etc/hotspot_restore.conf

require_cmd() {{
  command -v "$1" >/dev/null 2>&1 || {{
    echo "Missing required command: $1" >&2
    exit 1
  }}
}}

log() {{
  if command -v logger >/dev/null 2>&1; then
    logger -t "$LOG_TAG" -- "$*"
  else
    echo "$LOG_TAG: $*"
  fi
}}

urlencode() {{
  local s="$1"
  local out=""
  local i ch
  i=1
  while [ "$i" -le "${{#s}}" ]; do
    ch="$(printf '%s' "$s" | cut -c "$i")"
    case "$ch" in
      [a-zA-Z0-9.~_-]) out="${{out}}${{ch}}" ;;
      :) out="${{out}}%3A" ;;
      /) out="${{out}}%2F" ;;
      \?) out="${{out}}%3F" ;;
      \&) out="${{out}}%26" ;;
      =) out="${{out}}%3D" ;;
      +) out="${{out}}%2B" ;;
      @) out="${{out}}%40" ;;
      " ") out="${{out}}%20" ;;
      *) out="${{out}}${{ch}}" ;;
    esac
    i=$((i + 1))
  done
  printf '%s' "$out"
}}

scan_active_clients_usage() {{
  ndsctl json 2>/dev/null | awk -F'"' '
    BEGIN {{ printf "["; first = 1; mac = ""; state = ""; datain = 0; dataout = 0 }}
    /^[ \t]*"mac":/ {{ mac = $4 }}
    /^[ \t]*"state":/ {{ state = $4 }}
    /^[ \t]*"download_this_session":/ {{ dataout = $4 }}
    /^[ \t]*"upload_this_session":/ {{ datain = $4 }}
    /^[ \t]*}},/ || /^[ \t]*}}$/ {{
      if (mac != "" && state != "") {{
        if (state == "Authenticated") {{
          if (first == 0) printf ","
          printf "{{\"mac_address\":\"%s\",\"input_octets\":%s,\"output_octets\":%s}}", mac, datain, dataout
          first = 0
        }}
        mac = ""; state = ""; datain = 0; dataout = 0
      }}
    }}
    END {{ printf "]" }}
  '
}}

sync_usage() {{
  local payload url response ok
  payload="$(scan_active_clients_usage)"
  [ -n "$payload" ] || return 0
  [ "$payload" != "[]" ] || return 0

  url="${{FRAPPE_BASE_URL%/}}${{API_PATH}}"
  response="$(wget -qO- --post-data="nas_identifier=$(urlencode "$NAS_IDENTIFIER")&secret=$(urlencode "$NAS_SECRET")&usage_data=$(urlencode "$payload")" --timeout=15 "$url" 2>/dev/null || true)"
  
  if [ -n "$response" ]; then
    ok="$(printf '%s' "$response" | jsonfilter -e '@.message.ok' 2>/dev/null || true)"
    if [ "$ok" = "true" ]; then
      log "synchronized usage data successfully"
      return 0
    fi
    log "sync failed with server response: $response"
    return 1
  fi
  return 1
}}

kill_client_by_mac() {{
  local target_mac="$1"
  local token ip
  
  ndsctl deauth "$target_mac" >/dev/null 2>&1 || true
  
  if ndsctl status 2>/dev/null | grep -A 2 -i "$target_mac" | grep -q "State: Authenticated"; then
    token="$(ndsctl status 2>/dev/null | awk -v m="$target_mac" 'tolower($0) ~ tolower(m) {{getline; if ($1 == "Token:") print $2}}')"
    if [ -n "$token" ]; then
      ndsctl deauth "$token" >/dev/null 2>&1 || true
    fi
  fi
  
  if ndsctl status 2>/dev/null | grep -A 2 -i "$target_mac" | grep -q "State: Authenticated"; then
    ip="$(ndsctl status 2>/dev/null | awk -v m="$target_mac" 'tolower($0) ~ tolower(m) {{for(i=1;i<=NF;i++) if($i=="IP:") print $(i+1)}}')"
    if [ -n "$ip" ]; then
      ndsctl deauth "$ip" >/dev/null 2>&1 || true
    fi
  fi
}}

poll_deauth() {{
  local url response count i mac session_id still_connected
  url="${{FRAPPE_BASE_URL%/}}${{DEAUTH_API_PATH}}?nas_identifier=$(urlencode "$NAS_IDENTIFIER")&secret=$(urlencode "$NAS_SECRET")"
  response="$(wget -qO- --timeout=15 "$url" 2>/dev/null || true)"
  [ -n "$response" ] || return 0
  
  count="$(printf '%s' "$response" | jsonfilter -e '@.message.count' 2>/dev/null || echo 0)"
  [ "$count" -gt 0 ] || return 0
  
  i=0
  while [ "$i" -lt "$count" ]; do
    mac="$(printf '%s' "$response" | jsonfilter -e "@.message.actions[$i].mac_address" 2>/dev/null || true)"
    session_id="$(printf '%s' "$response" | jsonfilter -e "@.message.actions[$i].session_id" 2>/dev/null || true)"
    
    if [ -n "$session_id" ] && [ -n "$mac" ]; then
      log "Deauthenticating MAC $mac (Session: $session_id)"
      
      kill_client_by_mac "$mac"
      
      still_connected=0
      if ndsctl status 2>/dev/null | grep -A 2 -i "$mac" | grep -q "State: Authenticated"; then
        still_connected=1
      fi
      
      if [ "$still_connected" -eq 1 ]; then
        log "ERROR: Failed to deauth MAC $mac using all methods."
      else
        log "Successfully deauthed MAC $mac, sending ack to Frappe"
        wget -qO- "${{FRAPPE_BASE_URL%/}}${{ACK_API_PATH}}?nas_identifier=$(urlencode "$NAS_IDENTIFIER")&secret=$(urlencode "$NAS_SECRET")&session_id=$(urlencode "$session_id")&result=ok" >/dev/null 2>&1 || true
      fi
    fi
    i=$((i + 1))
  done
}}

main() {{
  require_cmd ndsctl
  require_cmd wget
  require_cmd jsonfilter

  [ -n "$FRAPPE_BASE_URL" ] || exit 1
  [ -n "$NAS_IDENTIFIER" ] || exit 1
  [ -n "$NAS_SECRET" ] || exit 1

  if [ "${{1:-}}" = "--once" ]; then
    poll_deauth
    sync_usage
    exit 0
  fi

  while true; do
    poll_deauth
    sync_usage
    sleep "$POLL_INTERVAL"
  done
}}

main "$@"
EOF

echo "6. Making scripts executable and scheduling them..."
chmod +x /usr/bin/hotspot_restore_active_clients.sh
chmod +x /usr/bin/hotspot_deauth_worker.sh
chmod +x /usr/bin/hotspot_sync_session_usage.sh

cat << 'EOF' > /etc/rc.local
#!/bin/sh
sleep 15
/etc/init.d/opennds restart
sleep 5
sh /usr/bin/hotspot_restore_active_clients.sh &
sh /usr/bin/hotspot_deauth_worker.sh &
sh /usr/bin/hotspot_sync_session_usage.sh &
exit 0
EOF
chmod +x /etc/rc.local

echo "7. Restarting services..."
/etc/init.d/network restart || true
/etc/init.d/mwan3 restart || true
/etc/init.d/firewall restart || true
/etc/init.d/opennds restart || true

echo "=========================================="
echo " Provisioning Complete! "
echo "=========================================="
"""
	return {"ok": True, "script": script}
