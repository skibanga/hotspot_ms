#!/bin/sh
set -eu

# Periodically sync active client usage (upload/download octets) from openNDS to Frappe.
#
# Required env or /etc/hotspot_restore.conf:
#   FRAPPE_BASE_URL   e.g. https://hotspot.uniquemindpro.xyz
#   NAS_IDENTIFIER    e.g. OpenWrt-Main
#   NAS_SECRET        NAS shared secret from Frappe Nas Device
#
# Optional env:
#   POLL_INTERVAL     seconds between syncs when running in loop mode (default 30)
#   LOG_TAG           logger tag (default hotspot-sync)
#
# Usage:
#   sh /usr/bin/hotspot_sync_session_usage.sh --once
#   sh /usr/bin/hotspot_sync_session_usage.sh

FRAPPE_BASE_URL="${FRAPPE_BASE_URL:-}"
NAS_IDENTIFIER="${NAS_IDENTIFIER:-}"
NAS_SECRET="${NAS_SECRET:-}"
POLL_INTERVAL="${POLL_INTERVAL:-30}"
LOG_TAG="${LOG_TAG:-hotspot-sync}"
API_PATH="/api/method/hotspot_ms.api.portal.sync_session_usage"

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
        out="${out}${ch}"
        ;;
    esac
    i=$((i + 1))
  done
  printf '%s' "$out"
}

scan_active_clients_usage() {
  ndsctl status | awk '
    BEGIN {
      first = 1
      printf "["
    }
    /^Client [0-9]+$/ {
      ip=""
      mac=""
      token=""
      state=""
      datain=0
      dataout=0
      next
    }
    /IP:/ {
      for (i = 1; i <= NF; i++) {
        if ($i == "IP:") ip = $(i + 1)
        if ($i == "MAC:") mac = $(i + 1)
      }
      next
    }
    /Token:/ { token = $2; next }
    /State:/ { state = $2; next }
    /Data In:/ || /Upload:/ || /Data_in:/ {
      for (i = 1; i <= NF; i++) {
        if ($i == "In:" || $i == "Upload:" || $i == "Data_in:") {
          datain = $(i + 1)
        }
      }
      next
    }
    /Data Out:/ || /Download:/ || /Data_out:/ {
      for (i = 1; i <= NF; i++) {
        if ($i == "Out:" || $i == "Download:" || $i == "Data_out:") {
          dataout = $(i + 1)
        }
      }
      if (state == "Authenticated" && mac != "") {
        if (first == 0) {
          printf ","
        }
        printf "{\"mac_address\":\"%s\",\"input_octets\":%s,\"output_octets\":%s}", mac, datain, dataout
        first = 0
      }
      next
    }
    END {
      printf "]"
    }
  '
}

sync_usage() {
  local payload url response ok
  payload="$(scan_active_clients_usage)"
  [ -n "$payload" ] || return 0
  [ "$payload" != "[]" ] || return 0

  url="${FRAPPE_BASE_URL%/}${API_PATH}"
  response="$(wget -qO- --post-data="nas_identifier=$(urlencode "$NAS_IDENTIFIER")&secret=$(urlencode "$NAS_SECRET")&usage_data=$(urlencode "$payload")" --timeout=15 "$url" 2>/dev/null || true)"
  
  if [ -n "$response" ]; then
    ok="$(printf '%s' "$response" | jsonfilter -e '@.ok' 2>/dev/null || true)"
    if [ "$ok" = "true" ]; then
      log "synchronized usage data successfully"
      return 0
    fi
    log "sync failed with server response: $response"
    return 1
  fi

  log "sync failed: empty or unreachable API server"
  return 1
}

main() {
  require_cmd ndsctl
  require_cmd wget
  require_cmd jsonfilter

  [ -n "$FRAPPE_BASE_URL" ] || { echo "FRAPPE_BASE_URL is required" >&2; exit 1; }
  [ -n "$NAS_IDENTIFIER" ] || { echo "NAS_IDENTIFIER is required" >&2; exit 1; }
  [ -n "$NAS_SECRET" ] || { echo "NAS_SECRET is required" >&2; exit 1; }

  if [ "${1:-}" = "--once" ]; then
    sync_usage
    exit 0
  fi

  while true; do
    sync_usage
    sleep "$POLL_INTERVAL"
  done
}

main "$@"
