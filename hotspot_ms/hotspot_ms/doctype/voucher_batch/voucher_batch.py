# Copyright (c) 2026, Sydney Kibanga and contributors
# For license information, please see license.txt

from __future__ import annotations

import secrets
import string

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class VoucherBatch(Document):
	def generate_vouchers(self) -> int:
		if not self.plan:
			frappe.throw(_("Please select a Plan before generating vouchers."))

		remaining = (self.quantity or 0) - (self.generated_count or 0)
		if remaining <= 0:
			frappe.throw(_("All vouchers for this batch are already generated."))

		plan = frappe.get_doc("Hotspot Plan", self.plan)
		expires_on = self.expires_on
		prefix = (self.voucher_prefix or "").replace(" ", "").upper()
		created = 0

		for _ in range(remaining):
			voucher_code = _build_unique_voucher_code(prefix)
			doc = frappe.new_doc("Hotspot Voucher")
			doc.voucher_code = voucher_code
			doc.status = "New"
			doc.plan = self.plan
			doc.batch = self.name
			doc.expires_on = expires_on
			if flt(plan.data_limit_mb) > 0:
				doc.data_limit_mb = plan.data_limit_mb
			doc.insert(ignore_permissions=True)
			created += 1

		self.generated_count = (self.generated_count or 0) + created
		self.status = "Generated" if self.generated_count > 0 else self.status
		self.save(ignore_permissions=True)
		frappe.db.commit()
		return created


def _build_unique_voucher_code(prefix: str = "") -> str:
	alphabet = string.ascii_uppercase + string.digits
	prefix = (prefix or "").strip().upper()
	for _ in range(20):
		suffix = "".join(secrets.choice(alphabet) for _ in range(8))
		code = f"{prefix}-{suffix}" if prefix else suffix
		if not frappe.db.exists("Hotspot Voucher", {"voucher_code": code}):
			return code

	frappe.throw(_("Unable to generate a unique voucher code. Please retry."))


@frappe.whitelist()
def generate_vouchers_for_batch(batch: str) -> dict:
	doc = frappe.get_doc("Voucher Batch", batch)
	count = doc.generate_vouchers()
	return {"ok": True, "created": count, "batch": doc.name}
