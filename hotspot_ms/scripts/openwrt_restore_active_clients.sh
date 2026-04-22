#!/bin/sh
set -eu

# Restore previously paid hotspot users after router reboot/power loss.
# The worker scans preauthenticated openNDS clients, asks Frappe whether their
# MAC still owns a valid active voucher, and if yes reauthenticates them using
# the remaining minutes until voucher expiry.
#
# Required env:
#   FRAPPE_BASE_URL   e.g. https://hotspot.uniquemindpro.xyz
#   NAS_IDENTIFIER    e.g. OpenWrt-Main
#   NAS_SECRET        NAS shared secret from Frappe Nas Device
#
# Optional env:
#   POLL_INTERVAL     seconds between scans when running in loop mode (default 15)
#   LOG_TAG           logger tag (default hotspot-restore)
#
# Usage:
#   sh /usr/bin/hotspot_restore_active_clients.sh --once
#   sh /usr/bin/hotspot_restore_active_clients.sh

FRAPPE_BASE_URL="${FRAPPE_BASE_URL:-}"
NAS_IDENTIFIER="${NAS_IDENTIFIER:-}"
NAS_SECRET="${NAS_SECRET:-}"
POLL_INTERVAL="${POLL_INTERVAL:-15}"
LOG_TAG="${LOG_TAG:-hotspot-restore}"
API_PATH="/api/method/hotspot_ms.api.portal.restore_active_access"

[ -f /etc/hotspot_restore.conf ] && . /etc/hotspot_restore.conf

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

log() {
  if command -v logger >/dev/null 2>&1; then
    logger -t "$LOG_TAG" -- "$*"
  else
    echo "$LOG_TAG: $*"
  fi
}

urlencode() {
  local s="$1"
  local out=""
  local i ch
  i=1
  while [ "$i" -le "${#s}" ]; do
    ch="$(printf '%s' "$s" | cut -c "$i")"
    case "$ch" in
      [a-zA-Z0-9.~_-]) out="${out}${ch}" ;;
      :) out="${out}%3A" ;;
      /) out="${out}%2F" ;;
      \?) out="${out}%3F" ;;
      \&) out="${out}%26" ;;
      =) out="${out}%3D" ;;
      +) out="${out}%2B" ;;
      @) out="${out}%40" ;;
      " ") out="${out}%20" ;;
      *)
        # Keep the worker BusyBox-safe. Inputs here are controlled values
        # (MAC/IP/NAS/secret), so explicit substitutions are sufficient.
        out="${out}${ch}"
        ;;
    esac
    i=$((i + 1))
  done
  printf '%s' "$out"
}

fetch_restore_decision() {
  local mac="$1"
  local ip="$2"
  local url

  url="${FRAPPE_BASE_URL%/}${API_PATH}?nas_identifier=$(urlencode "$NAS_IDENTIFIER")&secret=$(urlencode "$NAS_SECRET")&mac_address=$(urlencode "$mac")"
  if [ -n "$ip" ]; then
    url="${url}&ip_address=$(urlencode "$ip")"
  fi

  wget -qO- --timeout=15 "$url" 2>/dev/null || true
}

extract_json_field() {
  local payload="$1"
  local expr="$2"
  printf '%s' "$payload" | jsonfilter -e "$expr" 2>/dev/null || true
}

restore_one_client() {
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

  if ndsctl auth "$mac" "$minutes" "" "" "" "" "RESTORE|${session_id}|${voucher_code}" >/dev/null 2>&1; then
    log "restored mac=$mac ip=$ip token=$token session=$session_id minutes=$minutes voucher=$voucher_code"
    return 0
  fi

  if ndsctl auth "$mac" >/dev/null 2>&1; then
    log "restored mac=$mac ip=$ip token=$token session=$session_id via fallback auth"
    return 0
  fi

  log "failed to restore mac=$mac ip=$ip token=$token"
  return 1
}

scan_preauth_clients() {
  ndsctl status | awk '
    /^Client [0-9]+$/ { ip=""; mac=""; token=""; state=""; next }
    /IP:/ {
      for (i = 1; i <= NF; i++) {
        if ($i == "IP:") ip = $(i + 1)
        if ($i == "MAC:") mac = $(i + 1)
      }
      next
    }
    /Token:/ { token = $2; next }
    /State:/ {
      state = $2
      if (state == "Preauthenticated" && mac != "") {
        printf "%s\t%s\t%s\n", ip, mac, token
      }
      next
    }
  '
}

run_once() {
  scan_preauth_clients | while IFS="$(printf '\t')" read -r ip mac token; do
    [ -n "$mac" ] || continue
    restore_one_client "$ip" "$mac" "$token"
  done
}

main() {
  require_cmd ndsctl
  require_cmd wget
  require_cmd jsonfilter

  [ -n "$FRAPPE_BASE_URL" ] || { echo "FRAPPE_BASE_URL is required" >&2; exit 1; }
  [ -n "$NAS_IDENTIFIER" ] || { echo "NAS_IDENTIFIER is required" >&2; exit 1; }
  [ -n "$NAS_SECRET" ] || { echo "NAS_SECRET is required" >&2; exit 1; }

  if [ "${1:-}" = "--once" ]; then
    run_once
    exit 0
  fi

  while true; do
    run_once
    sleep "$POLL_INTERVAL"
  done
}

main "$@"
