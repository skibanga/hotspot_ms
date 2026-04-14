#!/bin/sh
set -eu

# Hotspot hardening bundle for OpenWrt firewall4 / nftables.
# Apply client isolation, then install nftables rules for:
# - per-client connection cap
# - TTL normalization as a heuristic anti-tethering layer
#
# Usage:
#   HOTSPOT_IFACE=br-lan CONN_LIMIT=150 TTL_VALUE=64 \
#     ./openwrt_hotspot_hardening.sh /etc/nftables.d/99-hotspot-hardening.nft

HOTSPOT_IFACE="${HOTSPOT_IFACE:-br-lan}"
CONN_LIMIT="${CONN_LIMIT:-150}"
TTL_VALUE="${TTL_VALUE:-64}"
OUT_FILE="${1:-/etc/nftables.d/99-hotspot-hardening.nft}"

cat >"$OUT_FILE" <<EOF
table inet fw4 {
  set hotspot_connlimit {
    type ipv4_addr
    size 65535
    flags dynamic
  }

  chain hotspot_hardening {
    type filter hook prerouting priority mangle; policy accept;

    # Cap excessive new tracked connections from a single guest IP.
    iifname "$HOTSPOT_IFACE" ct state new add @hotspot_connlimit { ip saddr ct count over $CONN_LIMIT } counter drop

    # Normalize TTL for guest traffic. This is a heuristic, not a guarantee.
    iifname "$HOTSPOT_IFACE" ip ttl 63 ip ttl set $TTL_VALUE
  }
}
EOF

for section in $(uci show wireless 2>/dev/null | sed -n 's/^wireless\.\([^=]*\)=wifi-iface$/\1/p'); do
  uci -q set "wireless.$section.isolate='1'"
done
uci -q commit wireless

echo "Wrote nftables snippet to: $OUT_FILE"
echo "Reload firewall: /etc/init.d/firewall restart"
echo "Reload wifi if needed: wifi reload"
