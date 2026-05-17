from __future__ import annotations

from typing import Any

import frappe


DEFAULT_HOTSPOT_ADS: tuple[dict[str, Any], ...] = (
	{
		"ad_name": "Welcome Announcement",
		"enabled": 1,
		"ad_type": "HTML/Text",
		"cta_url": "https://uniquemindpro.xyz",
		"bg_color": "#111827",
		"text_color": "#f9fafb",
		"ad_html": """<div style="text-align: center; padding: 25px 15px; font-family: sans-serif;">
			<h2 style="color: #6366f1; font-size: 22px; font-weight: bold; margin-bottom: 12px; letter-spacing: -0.5px;">Welcome to UniqueMind Hotspot!</h2>
			<p style="font-size: 15px; margin-bottom: 18px; color: #d1d5db; line-height: 1.5;">Enjoy your free daily high-speed internet, sponsored by <strong>UniqueMind Pro</strong>.</p>
			<div style="background: rgba(99, 102, 241, 0.1); border: 1px solid rgba(99, 102, 241, 0.25); padding: 12px; border-radius: 8px; font-size: 13px; color: #a5b4fc; max-width: 320px; margin: 0 auto 18px auto; line-height: 1.4;">
				💡 <strong>Custom Software & Networks</strong><br/>We build premium software systems, cloud networks, and enterprise hotspots.
			</div>
			<p style="font-size: 12px; color: #9ca3af; margin: 0;">Once the countdown completes, your free session will activate!</p>
		</div>"""
	},
)

DEFAULT_HOTSPOT_PLANS: tuple[dict[str, Any], ...] = (
	{
		"plan_name": "Free - 1 Hour",
		"price": 0,
		"currency": "TZS",
		"validity_value": 1,
		"validity_unit": "Hours",
		"is_free": 1,
		"session_chunk_minutes": 20,
		"ad_countdown_seconds": 15,
		"linked_ad": "Welcome Announcement",
		"description": "Free 1-hour access — watched in 20-minute chunks with a quick advertisement.",
	},
	{
		"plan_name": "TSh 500 - 6 Hours",
		"price": 500,
		"currency": "TZS",
		"validity_value": 6,
		"validity_unit": "Hours",
		"description": "Demo package for 6-hour access.",
	},
	{
		"plan_name": "TSh 1000 - 24 Hours",
		"price": 1000,
		"currency": "TZS",
		"validity_value": 24,
		"validity_unit": "Hours",
		"description": "Demo package for 24-hour access.",
	},
	{
		"plan_name": "TSh 5000 - 7 Days",
		"price": 5000,
		"currency": "TZS",
		"validity_value": 7,
		"validity_unit": "Days",
		"description": "Demo package for 7-day access.",
	},
)


def ensure_default_hotspot_plans() -> dict[str, int]:
	# Seed default ads first
	for ad_row in DEFAULT_HOTSPOT_ADS:
		existing_ad = frappe.db.get_value("Hotspot Ad", {"ad_name": ad_row["ad_name"]}, "name")
		if existing_ad:
			ad_doc = frappe.get_doc("Hotspot Ad", existing_ad)
		else:
			ad_doc = frappe.new_doc("Hotspot Ad")
		
		ad_doc.ad_name = ad_row["ad_name"]
		ad_doc.enabled = ad_row["enabled"]
		ad_doc.ad_type = ad_row["ad_type"]
		ad_doc.cta_url = ad_row["cta_url"]
		ad_doc.bg_color = ad_row["bg_color"]
		ad_doc.text_color = ad_row["text_color"]
		ad_doc.ad_html = ad_row["ad_html"]
		ad_doc.save(ignore_permissions=True)

	created = 0
	updated = 0

	for row in DEFAULT_HOTSPOT_PLANS:
		existing = frappe.db.get_value("Hotspot Plan", {"plan_name": row["plan_name"]}, "name")
		if existing:
			doc = frappe.get_doc("Hotspot Plan", existing)
			updated += 1
		else:
			doc = frappe.new_doc("Hotspot Plan")
			created += 1

		doc.plan_name = row["plan_name"]
		doc.enabled = 1
		doc.is_free = row.get("is_free", 0)
		doc.price = row["price"]
		doc.currency = row["currency"]
		doc.validity_value = row["validity_value"]
		doc.validity_unit = row["validity_unit"]
		doc.session_chunk_minutes = row.get("session_chunk_minutes", 0)
		doc.ad_countdown_seconds = row.get("ad_countdown_seconds", 15)
		doc.linked_ad = row.get("linked_ad")
		doc.description = row["description"]
		doc.save(ignore_permissions=True)

	frappe.db.commit()
	return {"created": created, "updated": updated, "total": len(DEFAULT_HOTSPOT_PLANS)}


def after_migrate() -> None:
	ensure_default_hotspot_plans()
