from __future__ import annotations

import secrets
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from typing import Any

import frappe
from frappe.utils import add_to_date, cint, flt, get_datetime, now_datetime


def _error(message: str, code: str = "ERROR") -> dict[str, Any]:
	return {"ok": False, "code": code, "message": message}


def _success(message: str, **data: Any) -> dict[str, Any]:
	res = {"ok": True, "message": message}
	res.update(data)
	return res


def _get_plan(plan_name: str):
	return frappe.get_doc("Hotspot Plan", plan_name)


def _resolve_voucher(voucher_code: str):
	voucher_name = frappe.db.get_value("Hotspot Voucher", {"voucher_code": voucher_code}, "name")
	if not voucher_name:
		return None
	return frappe.get_doc("Hotspot Voucher", voucher_name)


def _compute_expiry(activated_on, plan_doc):
	validity_value = cint(plan_doc.validity_value) or 1
	validity_unit = (plan_doc.validity_unit or "Days").lower()
	if validity_unit.startswith("minute"):
		return add_to_date(activated_on, minutes=validity_value)
	if validity_unit.startswith("hour"):
		return add_to_date(activated_on, hours=validity_value)
	return add_to_date(activated_on, days=validity_value)


def _expiry_check(voucher, plan_doc):
	if not voucher.expires_on:
		return
	if get_datetime(voucher.expires_on) < now_datetime() and voucher.status != "Expired":
		voucher.status = "Expired"
		voucher.save(ignore_permissions=True)
		frappe.db.commit()


def _to_mb(octets: float) -> float:
	return round((flt(octets) / 1024 / 1024), 2)


def _resolve_nas_device(nas_identifier: str | None) -> str | None:
	if not nas_identifier:
		return None

	value = (nas_identifier or "").strip()
	if not value:
		return None

	if frappe.db.exists("Nas Device", value):
		return value

	for field in ("device_name", "short_name", "ip_address"):
		name = frappe.db.get_value("Nas Device", {field: value}, "name")
		if name:
			return name

	return None


def _build_status_url(session_id: str, voucher_code: str, upstream_redir: str | None = None) -> str:
	params = {"session_id": session_id, "voucher_code": voucher_code}
	if upstream_redir:
		params["upstream_redir"] = upstream_redir
	return frappe.utils.get_url(f"/hotspot/status?{urlencode(params)}")


def _append_query(base_url: str, query: dict[str, str]) -> str:
	parsed = urlsplit(base_url)
	existing_query = dict(parse_qsl(parsed.query, keep_blank_values=True))
	existing_query.update({k: v for k, v in query.items() if v is not None and str(v).strip() != ""})
	return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(existing_query), parsed.fragment))


@frappe.whitelist(allow_guest=True)
def get_packages() -> dict[str, Any]:
	plans = frappe.get_all(
		"Hotspot Plan",
		filters={"enabled": 1},
		ignore_permissions=True,
		fields=[
			"name",
			"plan_name",
			"price",
			"currency",
			"validity_value",
			"validity_unit",
			"data_limit_mb",
			"download_kbps",
			"upload_kbps",
			"description",
		],
		order_by="price asc",
	)
	return _success("Packages fetched", packages=plans)


@frappe.whitelist(allow_guest=True)
def verify_voucher(voucher_code: str) -> dict[str, Any]:
	voucher_code = (voucher_code or "").strip()
	if not voucher_code:
		return _error("Voucher code is required", "MISSING_VOUCHER")

	voucher = _resolve_voucher(voucher_code)
	if not voucher:
		return _error("Voucher not found", "INVALID_VOUCHER")

	plan_doc = _get_plan(voucher.plan)
	_expiry_check(voucher, plan_doc)

	if voucher.status in {"Blocked", "Expired", "Used"}:
		return _error(f"Voucher is {voucher.status.lower()}", "VOUCHER_NOT_USABLE")

	if not plan_doc.enabled:
		return _error("Voucher plan is currently unavailable", "PLAN_DISABLED")

	remaining_mb = None
	if flt(voucher.data_limit_mb) > 0:
		remaining_mb = max(round(flt(voucher.data_limit_mb) - flt(voucher.data_used_mb), 2), 0)

	return _success(
		"Voucher is valid",
		voucher={
			"code": voucher.voucher_code,
			"status": voucher.status,
			"plan": voucher.plan,
			"expires_on": voucher.expires_on,
			"data_limit_mb": voucher.data_limit_mb,
			"data_used_mb": voucher.data_used_mb,
			"remaining_mb": remaining_mb,
		},
		plan={
			"name": plan_doc.plan_name,
			"validity_value": plan_doc.validity_value,
			"validity_unit": plan_doc.validity_unit,
			"download_kbps": plan_doc.download_kbps,
			"upload_kbps": plan_doc.upload_kbps,
		},
	)


@frappe.whitelist(allow_guest=True)
def activate_voucher(
	voucher_code: str,
	mac_address: str | None = None,
	ip_address: str | None = None,
	nas_device: str | None = None,
	customer: str | None = None,
) -> dict[str, Any]:
	voucher_code = (voucher_code or "").strip()
	if not voucher_code:
		return _error("Voucher code is required", "MISSING_VOUCHER")

	voucher = _resolve_voucher(voucher_code)
	if not voucher:
		return _error("Voucher not found", "INVALID_VOUCHER")

	plan_doc = _get_plan(voucher.plan)
	_expiry_check(voucher, plan_doc)

	if voucher.status in {"Blocked", "Expired", "Used"}:
		return _error(f"Voucher is {voucher.status.lower()}", "VOUCHER_NOT_USABLE")

	if voucher.status == "Active" and voucher.device_mac and mac_address and voucher.device_mac != mac_address:
		return _error("Voucher is already active on another device", "DEVICE_MISMATCH")

	existing_open_session = frappe.get_all(
		"Hotspot Session",
		filters={"voucher": voucher.name, "session_status": "Open"},
		ignore_permissions=True,
		fields=["name", "session_id"],
		order_by="start_time desc",
		limit=1,
	)
	if existing_open_session:
		return _success("Voucher already active", session_id=existing_open_session[0]["session_id"])

	now = now_datetime()
	if voucher.status == "New":
		voucher.status = "Active"

	if not voucher.activated_on:
		voucher.activated_on = now

	if not voucher.expires_on:
		voucher.expires_on = _compute_expiry(voucher.activated_on, plan_doc)

	if flt(voucher.data_limit_mb) <= 0 and flt(plan_doc.data_limit_mb) > 0:
		voucher.data_limit_mb = plan_doc.data_limit_mb

	if mac_address:
		voucher.device_mac = mac_address
	if ip_address:
		voucher.ip_address = ip_address
	resolved_nas = _resolve_nas_device(nas_device)
	if resolved_nas:
		voucher.last_nas = resolved_nas
	if customer:
		voucher.customer = customer

	voucher.save(ignore_permissions=True)

	session = frappe.new_doc("Hotspot Session")
	session.session_id = f"HS-{secrets.token_hex(6).upper()}"
	session.session_status = "Open"
	session.voucher = voucher.name
	session.customer = voucher.customer
	session.nas_device = resolved_nas
	session.mac_address = voucher.device_mac
	session.ip_address = voucher.ip_address
	session.start_time = now
	session.insert(ignore_permissions=True)

	frappe.db.commit()

	return _success(
		"Voucher activated",
		session_id=session.session_id,
		voucher={
			"code": voucher.voucher_code,
			"status": voucher.status,
			"plan": voucher.plan,
			"expires_on": voucher.expires_on,
			"data_limit_mb": voucher.data_limit_mb,
			"data_used_mb": voucher.data_used_mb,
		},
	)


@frappe.whitelist(allow_guest=True)
def build_opennds_redirect(
	session_id: str,
	voucher_code: str,
	tok: str | None = None,
	redir: str | None = None,
	authaction: str | None = None,
	fas: str | None = None,
) -> dict[str, Any]:
	"""
	Build a browser redirect URL for openNDS FAS flow.
	- If authaction/fas + tok are present: return gateway auth URL with tok + redir.
	- Else: fallback directly to hotspot status page.
	"""
	session_id = (session_id or "").strip()
	voucher_code = (voucher_code or "").strip()
	tok = (tok or "").strip()
	authaction = (authaction or "").strip()
	fas = (fas or "").strip()

	if not session_id:
		return _error("session_id is required", "MISSING_SESSION")
	if not voucher_code:
		return _error("voucher_code is required", "MISSING_VOUCHER")

	status_url = _build_status_url(session_id, voucher_code, upstream_redir=redir)

	auth_base = authaction or fas
	if auth_base and tok:
		redirect_url = _append_query(auth_base, {"tok": tok, "redir": status_url})
		return _success("Redirect URL prepared", redirect_url=redirect_url, status_url=status_url, mode="fas")

	return _success("Status URL prepared", redirect_url=status_url, status_url=status_url, mode="direct")


@frappe.whitelist(allow_guest=True)
def session_status(voucher_code: str | None = None, session_id: str | None = None) -> dict[str, Any]:
	filters = {"session_status": "Open"}
	if session_id:
		filters["session_id"] = session_id
	elif voucher_code:
		voucher_name = frappe.db.get_value("Hotspot Voucher", {"voucher_code": voucher_code}, "name")
		if not voucher_name:
			return _error("Voucher not found", "INVALID_VOUCHER")
		filters["voucher"] = voucher_name
	else:
		return _error("voucher_code or session_id is required", "MISSING_FILTER")

	session = frappe.get_all(
		"Hotspot Session",
		filters=filters,
		ignore_permissions=True,
		fields=[
			"name",
			"session_id",
			"session_status",
			"voucher",
			"customer",
			"start_time",
			"stop_time",
			"input_octets",
			"output_octets",
			"total_mb",
		],
		order_by="start_time desc",
		limit=1,
	)
	if not session:
		return _error("No active session", "NO_ACTIVE_SESSION")

	s = session[0]
	if not flt(s.get("total_mb")):
		total_mb = _to_mb(flt(s.get("input_octets")) + flt(s.get("output_octets")))
		s["total_mb"] = total_mb
		frappe.db.set_value("Hotspot Session", s["name"], "total_mb", total_mb, update_modified=False)

	voucher = frappe.get_doc("Hotspot Voucher", s["voucher"])
	remaining_mb = None
	if flt(voucher.data_limit_mb) > 0:
		remaining_mb = max(round(flt(voucher.data_limit_mb) - flt(voucher.data_used_mb), 2), 0)

	return _success(
		"Session status fetched",
		session={
			"session_id": s.get("session_id"),
			"status": s.get("session_status"),
			"start_time": s.get("start_time"),
			"total_mb": s.get("total_mb"),
		},
		voucher={
			"code": voucher.voucher_code,
			"status": voucher.status,
			"expires_on": voucher.expires_on,
			"data_limit_mb": voucher.data_limit_mb,
			"data_used_mb": voucher.data_used_mb,
			"remaining_mb": remaining_mb,
		},
	)


@frappe.whitelist(allow_guest=True)
def logout_session(session_id: str) -> dict[str, Any]:
	session_name = frappe.db.get_value("Hotspot Session", {"session_id": session_id}, "name")
	if not session_name:
		return _error("Session not found", "INVALID_SESSION")

	session = frappe.get_doc("Hotspot Session", session_name)
	if session.session_status != "Open":
		return _success("Session already closed", session_id=session.session_id)

	now = now_datetime()
	session.session_status = "Closed"
	session.stop_time = now
	if not flt(session.total_mb):
		session.total_mb = _to_mb(flt(session.input_octets) + flt(session.output_octets))
	session.save(ignore_permissions=True)

	if session.voucher:
		voucher = frappe.get_doc("Hotspot Voucher", session.voucher)
		if voucher.status == "Active" and voucher.expires_on and get_datetime(voucher.expires_on) <= now:
			voucher.status = "Expired"
			voucher.save(ignore_permissions=True)

	frappe.db.commit()
	return _success("Session closed", session_id=session.session_id)


@frappe.whitelist()
def seed_dummy_packages() -> dict[str, Any]:
	"""Create or update starter packages for quick portal testing."""
	seed = [
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
	]

	created = 0
	updated = 0
	for row in seed:
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
	return _success("Dummy packages seeded", created=created, updated=updated, total=len(seed))
