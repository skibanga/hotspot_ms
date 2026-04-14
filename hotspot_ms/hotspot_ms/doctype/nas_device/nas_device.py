# Copyright (c) 2026, Sydney Kibanga and contributors
# For license information, please see license.txt

import secrets

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
	key = secrets.token_hex(32)

	if name:
		doc = frappe.get_doc("Nas Device", name)
		doc.opennds_fas_key = key
		doc.save(ignore_permissions=True)
		frappe.db.commit()

	return {"ok": True, "opennds_fas_key": key}
