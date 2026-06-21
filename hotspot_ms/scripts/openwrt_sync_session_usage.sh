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
DEAUTH_API_PATH="/api/method/hotspot_ms.api.portal.pull_disconnect_actions"
ACK_API_PATH="/api/method/hotspot_ms.api.portal.acknowledge_disconnect_action"

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
  ndsctl json 2>/dev/null | awk -F'"' '
    BEGIN {
      printf "["
      first = 1
      mac = ""
      state = ""
      datain = 0
      dataout = 0
    }
    /^[ \t]*"mac":/ { mac = $4 }
    /^[ \t]*"state":/ { state = $4 }
    /^[ \t]*"download_this_session":/ { dataout = $4 }
    /^[ \t]*"upload_this_session":/ { datain = $4 }
    /^[ \t]*},/ || /^[ \t]*}$/ {
      if (mac != "" && state != "") {
        if (state == "Authenticated") {
          if (first == 0) printf ","
          printf "{\"mac_address\":\"%s\",\"input_octets\":%s,\"output_octets\":%s}", mac, datain, dataout
          first = 0
        }
        mac = ""
        state = ""
        datain = 0
        dataout = 0
      }
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
    ok="$(printf '%s' "$response" | jsonfilter -e '@.message.ok' 2>/dev/null || true)"
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

poll_deauth() {
  local url response count i mac session_id
  url="${FRAPPE_BASE_URL%/}${DEAUTH_API_PATH}?nas_identifier=$(urlencode "$NAS_IDENTIFIER")&secret=$(urlencode "$NAS_SECRET")"
  response="$(wget -qO- --timeout=15 "$url" 2>/dev/null || true)"
  [ -n "$response" ] || return 0
  
  count="$(printf '%s' "$response" | jsonfilter -e '@.message.count' 2>/dev/null || echo 0)"
  [ "$count" -gt 0 ] || return 0
  
  i=0
  while [ "$i" -lt "$count" ]; do
    mac="$(printf '%s' "$response" | jsonfilter -e "@.message.actions[$i].mac_address" 2>/dev/null || true)"
    session_id="$(printf '%s' "$response" | jsonfilter -e "@.message.actions[$i].session_id" 2>/dev/null || true)"
    
    if [ -n "$mac" ] && [ -n "$session_id" ]; then
      log "Deauthenticating MAC $mac (Session: $session_id)"
      ndsctl deauth "$mac" >/dev/null 2>&1 || true
      
      # Acknowledge to Frappe
      wget -qO- "${FRAPPE_BASE_URL%/}${ACK_API_PATH}?nas_identifier=$(urlencode "$NAS_IDENTIFIER")&secret=$(urlencode "$NAS_SECRET")&session_id=$(urlencode "$session_id")&result=ok" >/dev/null 2>&1 || true
    fi
    i=$((i + 1))
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
    poll_deauth
    sync_usage
    exit 0
  fi

  while true; do
    poll_deauth
    sync_usage
    sleep "$POLL_INTERVAL"
  done
}

main "$@"
