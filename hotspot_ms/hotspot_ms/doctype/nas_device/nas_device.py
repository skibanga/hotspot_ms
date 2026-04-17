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
