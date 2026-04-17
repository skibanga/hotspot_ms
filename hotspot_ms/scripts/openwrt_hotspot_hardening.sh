#!/bin/sh
set -eu

# Hotspot hardening bundle for OpenWrt firewall4 / nftables.
# Apply client isolation, then install a fragment that fw4 includes inside table inet fw4 for:
# - per-client new-connection throttle
# - TTL normalization as a heuristic anti-tethering layer
#
# Usage:
#   HOTSPOT_IFACE=br-lan CONN_LIMIT=150 TTL_VALUE=64 \
#     ./openwrt_hotspot_hardening.sh /usr/share/nftables.d/table-pre/99-hotspot-hardening.nft

HOTSPOT_IFACE="${HOTSPOT_IFACE:-br-lan}"
CONN_LIMIT="${CONN_LIMIT:-150}"
TTL_VALUE="${TTL_VALUE:-64}"
OUT_FILE="${1:-/usr/share/nftables.d/table-pre/99-hotspot-hardening.nft}"

mkdir -p "$(dirname "$OUT_FILE")"

cat >"$OUT_FILE" <<EOF
chain hotspot_hardening {
  type filter hook prerouting priority mangle; policy accept;

  # Throttle excessive new connections from a single guest IP.
  # This is a loadable meter-based control, not a simultaneous-connection counter.
  iifname "$HOTSPOT_IFACE" ct state new meter hotspot_newconn { ip saddr limit rate over ${CONN_LIMIT}/minute } counter drop

  # Normalize TTL for guest traffic. This is a heuristic, not a guarantee.
  iifname "$HOTSPOT_IFACE" ip ttl 63 ip ttl set $TTL_VALUE
}
EOF

for section in $(uci show wireless 2>/dev/null | sed -n 's/^wireless\.\([^=]*\)=wifi-iface$/\1/p'); do
  uci -q set "wireless.$section.isolate='1'"
done
uci -q commit wireless

echo "Wrote nftables snippet to: $OUT_FILE"
echo "Reload firewall: /etc/init.d/firewall restart"
echo "Reload wifi if needed: wifi reload"
