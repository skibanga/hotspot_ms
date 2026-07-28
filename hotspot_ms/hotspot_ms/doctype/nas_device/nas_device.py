# Copyright (c) 2026, Sydney Kibanga and contributors
# For license information, please see license.txt

from textwrap import dedent
import secrets
import string
import socket
from urllib.parse import quote, urlparse

import frappe
from frappe.model.document import Document


class NasDevice(Document):
	def validate(self):
		if not self.shared_secret:
			alphabet = string.ascii_letters + string.digits
			self.shared_secret = "".join(secrets.choice(alphabet) for _ in range(8))


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
	parsed_url = urlparse(site_url)
	domain_name = parsed_url.netloc or parsed_url.path
	if ":" in domain_name:
		domain_name = domain_name.split(":")[0]

	site_ip = ""
	try:
		resolved_ip = socket.gethostbyname(domain_name)
		if resolved_ip and not resolved_ip.startswith("127."):
			site_ip = resolved_ip
	except Exception:
		pass

	fas_ip_setting = f"\toption fasremoteip '{site_ip}'\n" if site_ip else ""
	preauth_ip_settings = f"\tlist preauthenticated_users 'allow tcp port 443 to {site_ip}'\n\tlist preauthenticated_users 'allow tcp port 80 to {site_ip}'\n" if site_ip else ""

	nas_id = doc.short_name or doc.device_name

	script = f"""#!/bin/sh
set -eu

echo "=========================================="
echo " Starting OpenWrt Provisioning Script"
echo " Device: {doc.device_name} ({doc.ip_address})"
echo "=========================================="

echo "1. Installing required packages..."
if command -v apk >/dev/null 2>&1; then
	apk update || true
	apk add opennds kmod-usb-net-rtl8152 kmod-usb-net-asix ca-certificates ca-bundle curl wget || true
elif command -v opkg >/dev/null 2>&1; then
	opkg update || true
	opkg install opennds kmod-usb-net-rtl8152 kmod-usb-net-asix ca-certificates ca-bundle curl wget || true
fi

echo "2. Configuring Network & LAN Interface..."
if ! uci -q get network.lan >/dev/null 2>&1; then
	uci set network.lan=interface
	uci set network.lan.proto='static'
fi

WAN_DEV="$(uci -q get network.wan.device || uci -q get network.wan.ifname || echo "eth0")"
LAN_PORTS=""
for dev in $(ip -o link show 2>/dev/null | awk -F': ' '$2 ~ /^(eth|en|lan|wlan)[0-9]+/ {{print $2}}'); do
	if [ "$dev" != "$WAN_DEV" ]; then
		LAN_PORTS="$LAN_PORTS $dev"
	fi
done

if [ -n "$LAN_PORTS" ]; then
	uci set network.lan.device='br-lan'
	if ! uci -q get network.@device[0] >/dev/null 2>&1; then
		uci add network device >/dev/null 2>&1 || true
	fi
	uci set network.@device[0].name='br-lan'
	uci set network.@device[0].type='bridge'
	uci delete network.@device[0].ports 2>/dev/null || true
	for port in $LAN_PORTS; do
		uci add_list network.@device[0].ports="$port"
		ip link set "$port" up 2>/dev/null || true
	done
elif [ -z "$(uci -q get network.lan.device)" ]; then
	uci set network.lan.device='eth0'
fi

uci set network.lan.ipaddr='{doc.ip_address}'
uci set network.lan.netmask='255.255.255.0'
uci commit network || true

echo "2b. Configuring DHCP Server for LAN..."
if ! uci -q get dhcp.lan >/dev/null 2>&1; then
	uci set dhcp.lan=dhcp
fi
uci set dhcp.lan.interface='lan'
uci set dhcp.lan.start='100'
uci set dhcp.lan.limit='150'
uci set dhcp.lan.leasetime='12h'
uci set dhcp.lan.dhcpv4='server'
uci commit dhcp || true
/etc/init.d/dnsmasq restart || true

echo "3. Configuring OpenNDS (Direct Remote FAS)..."
detect_lan_iface() {{
	if uci -q get network.lan.device >/dev/null 2>&1; then
		uci -q get network.lan.device
		return
	fi
	if ip link show dev br-lan >/dev/null 2>&1; then
		echo "br-lan"
		return
	fi
	if ip link show dev eth1 >/dev/null 2>&1; then
		echo "eth1"
		return
	fi
	local iface
	iface="$(ip -o link show 2>/dev/null | awk -F': ' '$2 !~ /^(lo|docker|veth|wg)/ {{print $2; exit}}')"
	echo "${{iface:-eth0}}"
}}

GW_IFACE="$(detect_lan_iface)"
echo " OpenNDS Gateway Interface: $GW_IFACE"

cat << EOF > /etc/config/opennds
config opennds
	option enabled '1'
	option gatewayinterface '$GW_IFACE'
	option gatewayname '{nas_id}'
	option gatewayport '{doc.opennds_gateway_port}'
{fas_ip_setting}	option fasremotefqdn '{domain_name}'
	option fasport '80'
	option faspath '/hotspot/login'
	option fassecureenabled '1'
	option faskey '{doc.opennds_fas_key or ""}'

	list preauthenticated_users 'allow udp port 53'
	list preauthenticated_users 'allow tcp port 53'
{preauth_ip_settings}EOF

echo "3b. Applying Hardening and Anti-Tethering Rules..."
mkdir -p /usr/share/nftables.d/table-pre/
cat << 'EOF' > /usr/share/nftables.d/table-pre/99-hotspot-hardening.nft
chain hotspot_hardening {{
	type filter hook prerouting priority mangle; policy accept;

	# Anti-Tethering: Drop packets coming from LAN with TTL 63
	iifname {{ "br-lan", "eth1" }} ip ttl 63 counter drop
	iifname {{ "br-lan", "eth1" }} ip6 hoplimit 63 counter drop

	# Block common Proxy & VPN bypass ports (NetShare, PDANet, etc)
	iifname {{ "br-lan", "eth1" }} tcp dport {{ 1080, 3128, 7777, 8080, 8243, 10808 }} counter drop
	iifname {{ "br-lan", "eth1" }} udp dport {{ 1080, 3128, 7777, 8080, 8243, 10808 }} counter drop
}}
EOF

# Ensure wireless client isolation is enabled if wireless config exists
if [ -f /etc/config/wireless ]; then
	for section in $(uci show wireless 2>/dev/null | sed -n 's/^wireless\.\([^=]*\)=wifi-iface$/\1/p'); do
		uci -q set "wireless.$section.isolate='1'" || true
	done
	uci commit wireless 2>/dev/null || true
fi

echo "4. Creating Agent Configuration..."
cat << 'EOF' > /etc/hotspot_restore.conf
FRAPPE_BASE_URL="{site_url}"
NAS_IDENTIFIER="{nas_id}"
NAS_SECRET="{doc.shared_secret}"
EOF

echo "5. Installing Hotspot Worker Scripts..."
mkdir -p /usr/lib/opennds

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
      "#") out="${{out}}%23" ;;
      "%") out="${{out}}%25" ;;
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
      "#") out="${{out}}%23" ;;
      "%") out="${{out}}%25" ;;
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
  ndsctl status 2>/dev/null | awk '
    BEGIN {{ printf "["; first = 1; mac = ""; state = ""; down_bytes = 0; up_bytes = 0 }}
    /Client/ {{
      if (mac != "" && state == "Authenticated") {{
        if (first == 0) printf ","
        printf "{{\"mac_address\":\"%s\",\"input_octets\":%.0f,\"output_octets\":%.0f}}", mac, up_bytes, down_bytes
        first = 0
      }}
      mac = ""; state = ""; down_bytes = 0; up_bytes = 0
    }}
    /IP:/ {{
      for (i = 1; i <= NF; i++) {{
        if ($i == "MAC:") mac = $(i + 1)
      }}
    }}
    /State:/ {{ state = $2 }}
    /Download this session:/ {{
      val = $4; unit = $5
      gsub(/;/, "", unit)
      if (unit == "kB" || unit == "KB" || unit == "kb") mult = 1024
      else if (unit == "MB" || unit == "mb") mult = 1048576
      else if (unit == "GB" || unit == "gb") mult = 1073741824
      else mult = 1
      down_bytes = val * mult
    }}
    /Upload this session:/ {{
      val = $4; unit = $5
      gsub(/;/, "", unit)
      if (unit == "kB" || unit == "KB" || unit == "kb") mult = 1024
      else if (unit == "MB" || unit == "mb") mult = 1048576
      else if (unit == "GB" || unit == "gb") mult = 1073741824
      else mult = 1
      up_bytes = val * mult
    }}
    END {{
      if (mac != "" && state == "Authenticated") {{
        if (first == 0) printf ","
        printf "{{\"mac_address\":\"%s\",\"input_octets\":%.0f,\"output_octets\":%.0f}}", mac, up_bytes, down_bytes
      }}
      printf "]"
    }}
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
[ -x /etc/init.d/network ] && /etc/init.d/network restart || true
[ -x /etc/init.d/mwan3 ] && /etc/init.d/mwan3 restart || true
[ -x /etc/init.d/firewall ] && /etc/init.d/firewall restart || true
[ -x /etc/init.d/opennds ] && /etc/init.d/opennds enable 2>/dev/null || true
[ -x /etc/init.d/opennds ] && /etc/init.d/opennds start 2>/dev/null || /etc/init.d/opennds restart || true

echo "8. Launching hotspot background agents..."
killall hotspot_restore_active_clients.sh 2>/dev/null || pkill -f hotspot_restore_active_clients 2>/dev/null || true
killall hotspot_deauth_worker.sh 2>/dev/null || pkill -f hotspot_deauth_worker 2>/dev/null || true
killall hotspot_sync_session_usage.sh 2>/dev/null || pkill -f hotspot_sync_session_usage 2>/dev/null || true

sh /usr/bin/hotspot_restore_active_clients.sh >/dev/null 2>&1 &
sh /usr/bin/hotspot_deauth_worker.sh >/dev/null 2>&1 &
sh /usr/bin/hotspot_sync_session_usage.sh >/dev/null 2>&1 &

echo "=========================================="
echo " Provisioning Complete! "
echo "=========================================="
"""
	return {"ok": True, "script": script}


def _get_doc_secret(doc) -> str:
	try:
		secret = doc.get_password("shared_secret", raise_exception=False)
		if secret:
			return secret
	except Exception:
		pass
	return (doc.get("shared_secret") or "").strip()


@frappe.whitelist()
def get_provisioning_command(name: str) -> dict:
	doc = frappe.get_doc("Nas Device", name)
	secret = _get_doc_secret(doc)
	site_url = frappe.utils.get_url()
	enc_name = quote(doc.name)
	enc_secret = quote(secret or "")
	cmd = f'wget --no-check-certificate -qO- "{site_url}/api/method/hotspot_ms.hotspot_ms.doctype.nas_device.nas_device.download_provisioning_script?name={enc_name}&secret={enc_secret}" | sh'
	return {"ok": True, "command": cmd}


@frappe.whitelist(allow_guest=True)
def download_provisioning_script(name: str, secret: str | None = None):
	if not frappe.db.exists("Nas Device", name):
		frappe.local.response["http_status_code"] = 404
		return "NAS Device Not Found"

	doc = frappe.get_doc("Nas Device", name)
	real_secret = _get_doc_secret(doc)
	if secret and real_secret:
		if secret != real_secret and secret != (doc.get("shared_secret") or ""):
			frappe.local.response["http_status_code"] = 403
			return "Unauthorized"

	res = generate_openwrt_provisioning_script(name)
	frappe.response["type"] = "text"
	frappe.response["content_type"] = "text/plain"
	return res.get("script", "")
