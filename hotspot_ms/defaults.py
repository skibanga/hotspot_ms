from __future__ import annotations

from typing import Any

import frappe


DEFAULT_HOTSPOT_PLANS: tuple[dict[str, Any], ...] = (
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
		doc.price = row["price"]
		doc.currency = row["currency"]
		doc.validity_value = row["validity_value"]
		doc.validity_unit = row["validity_unit"]
		doc.description = row["description"]
		doc.save(ignore_permissions=True)

	frappe.db.commit()
	return {"created": created, "updated": updated, "total": len(DEFAULT_HOTSPOT_PLANS)}


def after_migrate() -> None:
	ensure_default_hotspot_plans()
