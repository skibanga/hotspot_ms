from __future__ import annotations

import frappe
from frappe.utils import flt, get_datetime, now_datetime

DEAUTH_PENDING_PREFIX = "DEAUTH_PENDING|"


def _to_mb(octets: float) -> float:
	return round((flt(octets) / 1024 / 1024), 2)


def close_expired_or_used_sessions() -> dict[str, int]:
	"""
	Close open sessions once the voucher expires or data quota is exhausted.
	Also updates voucher status to Expired/Used.
	"""
	now = now_datetime()
	closed = 0
	voucher_updates = 0

	open_sessions = frappe.get_all(
		"Hotspot Session",
		filters={"session_status": "Open"},
		fields=["name", "voucher", "input_octets", "output_octets", "total_mb"],
		ignore_permissions=True,
	)

	for row in open_sessions:
		if not row.voucher:
			continue

		voucher = frappe.get_doc("Hotspot Voucher", row.voucher)
		session_total_mb = flt(row.total_mb) or _to_mb(flt(row.input_octets) + flt(row.output_octets))

		is_expired = bool(voucher.expires_on and get_datetime(voucher.expires_on) <= now)
		limit_mb = flt(voucher.data_limit_mb)
		data_used_mb = max(flt(voucher.data_used_mb), session_total_mb)
		is_used = bool(limit_mb > 0 and data_used_mb >= limit_mb)

		if not (is_expired or is_used):
			continue

		session = frappe.get_doc("Hotspot Session", row.name)
		session.session_status = "Expired" if is_expired else "Closed"
		session.stop_time = now
		session.total_mb = session_total_mb
		base_cause = "Session Expired" if is_expired else "Data Limit Reached"
		if session.ip_address or session.mac_address:
			session.terminate_cause = f"{DEAUTH_PENDING_PREFIX}{base_cause}"
		else:
			session.terminate_cause = base_cause
		session.save(ignore_permissions=True)
		closed += 1

		if is_used and flt(voucher.data_used_mb) < data_used_mb:
			voucher.data_used_mb = data_used_mb

		new_status = "Expired" if is_expired else "Used"
		if voucher.status != new_status:
			voucher.status = new_status
			voucher_updates += 1

		voucher.save(ignore_permissions=True)

	if closed or voucher_updates:
		frappe.db.commit()

	return {"closed_sessions": closed, "updated_vouchers": voucher_updates}
