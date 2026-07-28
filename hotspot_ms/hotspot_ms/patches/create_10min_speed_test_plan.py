import frappe


def execute():
	if not frappe.db.exists("Hotspot Plan", {"is_free": 1}):
		doc = frappe.new_doc("Hotspot Plan")
		doc.plan_name = "10 Min Speed Test (Free)"
		doc.enabled = 1
		doc.is_free = 1
		doc.price = 0
		doc.validity_value = 10
		doc.validity_unit = "Minutes"
		doc.requires_ad_view = 0
		doc.description = "Free 10-minute daily speed test access trial."
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
