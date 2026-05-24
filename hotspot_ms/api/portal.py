from __future__ import annotations

import base64
import hashlib
import hmac
import math
import secrets
import string
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from typing import Any

import frappe
from frappe.utils import add_to_date, cint, flt, get_datetime, now_datetime

from hotspot_ms.defaults import ensure_default_hotspot_plans

DEAUTH_PENDING_PREFIX = "DEAUTH_PENDING|"


def _error(message: str, code: str = "ERROR") -> dict[str, Any]:
	return {"ok": False, "code": code, "message": frappe._(message)}


def _success(message: str, **data: Any) -> dict[str, Any]:
	res = {"ok": True, "message": frappe._(message)}
	res.update(data)
	return res


def _get_plan(plan_name: str):
	return frappe.get_doc("Hotspot Plan", plan_name)


def _resolve_voucher(voucher_code: str):
	voucher_name = frappe.db.get_value("Hotspot Voucher", {"voucher_code": voucher_code}, "name")
	if not voucher_name:
		return None
	return frappe.get_doc("Hotspot Voucher", voucher_name)


def _issue_payment_voucher(plan_name: str, customer: str | None = None):
	plan = frappe.get_doc("Hotspot Plan", plan_name)
	voucher = frappe.new_doc("Hotspot Voucher")
	voucher.voucher_code = f"SNP-{secrets.token_hex(5).upper()}"
	voucher.status = "New"
	voucher.plan = plan.name
	if flt(plan.data_limit_mb) > 0:
		voucher.data_limit_mb = flt(plan.data_limit_mb)
	if customer:
		voucher.customer = customer
	voucher.insert(ignore_permissions=True)
	return voucher


def _compute_expiry(activated_on, plan_doc):
	validity_value = cint(plan_doc.validity_value) or 1
	validity_unit = (plan_doc.validity_unit or "Days").lower()
	if validity_unit.startswith("minute"):
		return add_to_date(activated_on, minutes=validity_value)
	if validity_unit.startswith("hour"):
		return add_to_date(activated_on, hours=validity_value)
	return add_to_date(activated_on, days=validity_value)


def _remaining_session_minutes(expires_on) -> int:
	if not expires_on:
		return 0

	remaining_seconds = (get_datetime(expires_on) - now_datetime()).total_seconds()
	if remaining_seconds <= 0:
		return 0

	return max(1, int(math.ceil(remaining_seconds / 60)))


def _normalize_mac(mac_address: str | None) -> str:
	value = (mac_address or "").strip().lower()
	if not value:
		return ""

	compact = "".join(ch for ch in value if ch.isalnum())
	if len(compact) == 12 and all(ch in "0123456789abcdef" for ch in compact):
		return ":".join(compact[i : i + 2] for i in range(0, 12, 2))

	return value


def _normalize_ip(ip_address: str | None) -> str:
	return (ip_address or "").strip()


def _normalize_host_port(value: str | None) -> str:
	text = (value or "").strip()
	if not text:
		return ""

	parsed = urlsplit(text if "://" in text else f"//{text}", scheme="http")
	host_port = parsed.netloc or parsed.path
	return host_port.strip().strip("/")


def _b64decode_text(value: str) -> str:
	text = (value or "").strip().replace(" ", "+")
	if not text:
		return ""

	padding = (-len(text)) % 4
	if padding:
		text += "=" * padding

	return base64.b64decode(text).decode("utf-8", errors="replace").strip()


def _normalize_opennds_payload(payload: dict[str, Any]) -> dict[str, Any]:
	normalized: dict[str, Any] = {}
	for key, value in (payload or {}).items():
		if value is None:
			continue
		text = str(value).strip()
		if not text:
			continue
		normalized[key.strip()] = text

	aliases = {
		"client_hid": "hid",
		"clientipaddress": "clientip",
		"clientmacaddress": "clientmac",
		"gateway_addr": "gatewayaddress",
		"gateway_port": "gatewayport",
	}
	for source, target in aliases.items():
		if source in normalized and target not in normalized:
			normalized[target] = normalized[source]

	return normalized


def _decode_opennds_secure_fas(fas_value: str | None) -> dict[str, Any]:
	text = (fas_value or "").strip()
	if not text:
		return {}

	decoded = _b64decode_text(text)
	if not decoded:
		return {}

	if "&" not in decoded and ", " in decoded:
		decoded = decoded.replace(", ", "&")

	parsed = dict(parse_qsl(decoded, keep_blank_values=True))
	return _normalize_opennds_payload(parsed)


def get_opennds_captive_context(form_dict: Any | None = None) -> dict[str, Any]:
	"""
	Normalize captive portal parameters from openNDS.
	Supports insecure redirects and secure level 1 base64 payloads.
	"""
	args = dict(form_dict or {})
	context = _normalize_opennds_payload(args)
	secure_payload = _decode_opennds_secure_fas(context.get("fas"))
	if secure_payload:
		context.update(secure_payload)
		context["secure_fas"] = True
	else:
		context["secure_fas"] = False

	if not context.get("clientip") and context.get("authaction"):
		try:
			auth_url = urlsplit(context["authaction"])
			for key, value in parse_qsl(auth_url.query, keep_blank_values=True):
				key = key.strip()
				value = value.strip()
				if key in {"clientip", "clientmac", "gatewayname", "hid", "gatewayaddress", "authdir", "originurl", "clientif", "tok", "gatewayport"} and value:
					context.setdefault(key, value)
		except Exception:
			pass

	return context


def _get_opennds_fas_key(nas_device: str | None = None) -> str:
	nas_name = _resolve_nas_device(nas_device)
	if not nas_name:
		nas = frappe.get_all(
			"Nas Device",
			filters={"enabled": 1},
			ignore_permissions=True,
			fields=["name"],
			limit=1,
		)
		nas_name = nas[0]["name"] if nas else ""

	if not nas_name:
		return ""

	nas_doc = frappe.get_doc("Nas Device", nas_name)
	key = (nas_doc.get("opennds_fas_key") or "").strip()
	if key:
		return key
	return (frappe.conf.get("opennds_fas_key") or "").strip()


def _get_opennds_gateway_port(nas_device: str | None = None) -> str:
	nas_name = _resolve_nas_device(nas_device)
	if not nas_name:
		nas = frappe.get_all(
			"Nas Device",
			filters={"enabled": 1},
			ignore_permissions=True,
			fields=["name"],
			limit=1,
		)
		nas_name = nas[0]["name"] if nas else ""

	if not nas_name:
		return "2050"

	nas_doc = frappe.get_doc("Nas Device", nas_name)
	return str(cint(nas_doc.get("opennds_gateway_port") or 2050) or 2050)


def _compute_opennds_return_token(hid: str, faskey: str) -> str:
	return hashlib.sha256(f"{(hid or '').strip()}{(faskey or '').strip()}".encode()).hexdigest()


@frappe.whitelist()
def generate_opennds_fas_key(name: str | None = None) -> dict[str, Any]:
	"""Generate a shared secret for openNDS secure FAS and save it to the NAS record."""
	alphabet = string.ascii_letters + string.digits
	key = "".join(secrets.choice(alphabet) for _ in range(16))

	if name:
		doc = frappe.get_doc("Nas Device", name)
		doc.opennds_fas_key = key
		doc.save(ignore_permissions=True)
		frappe.db.commit()

	return _success("FAS key generated", opennds_fas_key=key)


def _is_data_exhausted(voucher) -> bool:
	limit = flt(voucher.data_limit_mb)
	if limit <= 0:
		return False
	return flt(voucher.data_used_mb) >= limit


def _sync_voucher_status(voucher) -> bool:
	"""Keep voucher status in sync with expiry and data limits."""
	now = now_datetime()
	changed = False

	if voucher.expires_on and get_datetime(voucher.expires_on) <= now and voucher.status != "Expired":
		voucher.status = "Expired"
		changed = True
	elif _is_data_exhausted(voucher) and voucher.status not in {"Used", "Expired", "Blocked"}:
		voucher.status = "Used"
		changed = True

	if changed:
		voucher.save(ignore_permissions=True)

	return changed


def _consume_voucher_on_termination(voucher) -> bool:
	"""
	Consume a voucher immediately when an admin terminates the session.
	This closes the reuse loophole that remains if the voucher stays Active.
	"""
	if not voucher or voucher.status in {"Expired", "Blocked", "Used"}:
		return False

	voucher.status = "Used"
	voucher.save(ignore_permissions=True)
	return True


def _validate_device_reuse(voucher, mac_address: str | None = None, ip_address: str | None = None) -> dict[str, Any] | None:
	"""
	Strict one-device policy:
	- Prefer MAC lock when available.
	- Fall back to IP lock if MAC is unavailable in the captive payload.
	"""
	bound_mac = _normalize_mac(voucher.device_mac)
	incoming_mac = _normalize_mac(mac_address)
	bound_ip = _normalize_ip(voucher.ip_address)
	incoming_ip = _normalize_ip(ip_address)

	if bound_mac:
		if incoming_mac and incoming_mac != bound_mac:
			return _error("Voucher is locked to another device", "DEVICE_MISMATCH")
		if not incoming_mac:
			return _error("Client MAC is required for this voucher", "MISSING_CLIENT_MAC")
		return None

	if bound_ip and incoming_ip and incoming_ip != bound_ip and voucher.status in {"Active", "Used", "Expired"}:
		return _error("Voucher is already bound to another client", "DEVICE_MISMATCH")

	return None


def _to_mb(octets: float) -> float:
	return round((flt(octets) / 1024 / 1024), 2)


def _resolve_nas_device(nas_identifier: str | None) -> str | None:
	if not nas_identifier:
		return None

	value = _normalize_host_port(nas_identifier) or (nas_identifier or "").strip()
	if not value:
		return None

	if frappe.db.exists("Nas Device", value):
		return value

	for field in ("device_name", "short_name", "ip_address"):
		name = frappe.db.get_value("Nas Device", {field: value}, "name")
		if name:
			return name

	return None


def _find_restorable_voucher(mac_address: str, nas_name: str | None = None):
	if not mac_address:
		return None

	rows = frappe.get_all(
		"Hotspot Voucher",
		filters={"device_mac": mac_address, "status": "Active"},
		fields=["name", "last_nas", "expires_on", "modified"],
		order_by="expires_on desc, modified desc",
		ignore_permissions=True,
	)

	for row in rows:
		if row.get("last_nas") and nas_name and row.get("last_nas") != nas_name:
			continue

		voucher = frappe.get_doc("Hotspot Voucher", row["name"])
		if _sync_voucher_status(voucher):
			frappe.db.commit()

		if voucher.status != "Active":
			continue

		if voucher.expires_on and get_datetime(voucher.expires_on) <= now_datetime():
			continue

		return voucher

	return None


def _validate_nas_access(nas_identifier: str | None, secret: str | None):
	nas_name = _resolve_nas_device(nas_identifier)
	if not nas_name:
		return None, _error("Unknown NAS device", "INVALID_NAS")

	nas_doc = frappe.get_doc("Nas Device", nas_name)
	expected_secret = (nas_doc.get_password("shared_secret") or "").strip()
	provided_secret = (secret or "").strip()

	if not expected_secret or not provided_secret:
		return None, _error("Missing NAS shared secret", "MISSING_NAS_SECRET")

	if not hmac.compare_digest(expected_secret, provided_secret):
		return None, _error("Invalid NAS shared secret", "INVALID_NAS_SECRET")

	if not cint(nas_doc.enabled):
		return None, _error("NAS device is disabled", "NAS_DISABLED")

	return nas_doc, None


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


def _default_opennds_authdir() -> str:
	"""
	openNDS uses a virtual auth directory. If the captive payload omits it,
	fall back to the documented default.
	"""
	return "opennds_auth"


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
			"is_free",
		],
		order_by="price asc",
	)

	for p in plans:
		p.plan_name = frappe._(p.plan_name)
		p.description = frappe._(p.description)
		if p.validity_unit:
			p.validity_unit = frappe._(p.validity_unit)

	return _success("Packages fetched", packages=plans)


def _has_claimed_free_today(mac_address: str, plan_name: str) -> bool:
	"""Check if this MAC already claimed a free voucher today."""
	if not mac_address:
		return False

	today_start = now_datetime().replace(hour=0, minute=0, second=0, microsecond=0)
	existing = frappe.get_all(
		"Hotspot Voucher",
		filters={
			"plan": plan_name,
			"device_mac": mac_address,
			"generated_on": (">=", today_start),
		},
		fields=["name"],
		ignore_permissions=True,
		limit=1,
	)
	return bool(existing)


@frappe.whitelist(allow_guest=True)
def claim_free_voucher(
	mac_address: str | None = None,
	ip_address: str | None = None,
	nas_device: str | None = None,
) -> dict[str, Any]:
	"""
	Claim a free 1-hour voucher. One claim per MAC address per calendar day.
	Issues a new voucher from the free plan, activates it, and returns the session.
	"""
	mac_address = _normalize_mac(mac_address)
	ip_address = _normalize_ip(ip_address)

	if not mac_address:
		return _error("Device MAC address is required for free access", "MISSING_MAC")

	# Find the active free plan
	free_plans = frappe.get_all(
		"Hotspot Plan",
		filters={"enabled": 1, "is_free": 1},
		fields=["name", "plan_name"],
		ignore_permissions=True,
		limit=1,
	)
	if not free_plans:
		return _error("No free plan is currently available", "NO_FREE_PLAN")

	plan_name = free_plans[0]["name"]

	# Check once-per-day limit
	if _has_claimed_free_today(mac_address, plan_name):
		return _error(
			"You have already used your free access today. Come back tomorrow!",
			"FREE_ALREADY_CLAIMED",
		)

	# Issue a free voucher
	plan_doc = frappe.get_doc("Hotspot Plan", plan_name)
	voucher = frappe.new_doc("Hotspot Voucher")
	voucher.voucher_code = f"FREE-{secrets.token_hex(5).upper()}"
	voucher.status = "New"
	voucher.plan = plan_doc.name
	voucher.device_mac = mac_address
	if ip_address:
		voucher.ip_address = ip_address
	if flt(plan_doc.data_limit_mb) > 0:
		voucher.data_limit_mb = flt(plan_doc.data_limit_mb)
	voucher.insert(ignore_permissions=True)
	frappe.db.commit()

	# Activate through the standard flow
	result = activate_voucher(
		voucher_code=voucher.voucher_code,
		mac_address=mac_address,
		ip_address=ip_address,
		nas_device=nas_device,
	)
	if not result.get("ok"):
		return result

	result["voucher_code"] = voucher.voucher_code
	result["message"] = frappe._("Free access granted! Enjoy your 1 hour of internet.")
	return result


@frappe.whitelist(allow_guest=True)
def payment_transaction_status(payment_ref: str) -> dict[str, Any]:
	payment_ref = (payment_ref or "").strip()
	if not payment_ref:
		return _error("payment_ref is required", "MISSING_PAYMENT_REF")

	tx = frappe.get_value(
		"Payment Transaction",
		{"payment_ref": payment_ref},
		[
			"name",
			"payment_ref",
			"status",
			"plan",
			"voucher",
			"provider_response_message",
			"requested_on",
			"completed_on",
		],
		as_dict=True,
	)
	if not tx:
		return _error("Payment transaction not found", "PAYMENT_NOT_FOUND")

	return _success("Payment status fetched", payment=tx)


@frappe.whitelist(allow_guest=True)
def check_pending_paid_voucher(mac_address: str) -> dict[str, Any]:
	"""
	Checks if this MAC address has a paid-but-unused voucher from a successful
	Payment Transaction. This handles the case where the user paid, closed
	the browser, and the webhook auto-activate failed or was skipped.
	Returns the payment_ref so the frontend can call activate_paid_access.
	"""
	mac_address = _normalize_mac(mac_address)
	if not mac_address:
		return {"ok": False, "found": False}

	# Find successful payments whose metadata contains this MAC
	# and whose voucher is still "New" (not yet activated)
	transactions = frappe.get_all(
		"Payment Transaction",
		filters={"status": "Successful"},
		fields=["name", "payment_ref", "voucher", "webhook_payload", "plan"],
		order_by="completed_on desc",
		limit=20,
		ignore_permissions=True,
	)

	for tx in transactions:
		voucher_name = (tx.get("voucher") or "").strip()
		if not voucher_name:
			continue

		# Only match vouchers that are still "New" (unused)
		voucher_status = frappe.db.get_value("Hotspot Voucher", voucher_name, "status")
		if voucher_status != "New":
			continue

		# Check if metadata contains this MAC address
		import json as _json
		try:
			payload = _json.loads(tx.get("webhook_payload") or "{}")
			meta = (payload.get("data") or {}).get("metadata") or {}
			stored_mac = _normalize_mac(meta.get("mac_address") or "")
			if stored_mac == mac_address:
				return {
					"ok": True,
					"found": True,
					"payment_ref": tx.get("payment_ref"),
					"voucher": voucher_name,
					"plan": tx.get("plan") or "",
				}
		except Exception:
			continue

	return {"ok": True, "found": False}


@frappe.whitelist(allow_guest=True)
def activate_paid_access(
	payment_ref: str,
	mac_address: str | None = None,
	ip_address: str | None = None,
	nas_device: str | None = None,
	tok: str | None = None,
	redir: str | None = None,
	authaction: str | None = None,
	fas: str | None = None,
	gatewayaddress: str | None = None,
	gatewayport: str | None = None,
	authdir: str | None = None,
	hid: str | None = None,
) -> dict[str, Any]:
	payment_ref = (payment_ref or "").strip()
	if not payment_ref:
		return _error("payment_ref is required", "MISSING_PAYMENT_REF")

	tx = frappe.get_value(
		"Payment Transaction",
		{"payment_ref": payment_ref},
		["name", "status", "plan", "voucher", "customer"],
		as_dict=True,
	)
	if not tx:
		return _error("Payment transaction not found", "PAYMENT_NOT_FOUND")

	status = (tx.get("status") or "").strip()
	if status != "Successful":
		if status in {"Failed", "Cancelled"}:
			return _error(f"Payment is {status.lower()}", "PAYMENT_NOT_SUCCESSFUL")
		return _error("Payment is still pending", "PAYMENT_PENDING")

	voucher_name = (tx.get("voucher") or "").strip()
	voucher = frappe.get_doc("Hotspot Voucher", voucher_name) if voucher_name and frappe.db.exists("Hotspot Voucher", voucher_name) else None
	if not voucher:
		plan_name = (tx.get("plan") or "").strip()
		if not plan_name:
			return _error("Paid transaction has no plan", "MISSING_PLAN")
		voucher = _issue_payment_voucher(plan_name, customer=tx.get("customer"))
		frappe.db.set_value("Payment Transaction", tx["name"], "voucher", voucher.name, update_modified=True)

	activated = activate_voucher(
		voucher_code=voucher.voucher_code,
		mac_address=mac_address,
		ip_address=ip_address,
		nas_device=nas_device,
		customer=tx.get("customer"),
	)
	if not activated.get("ok"):
		return activated

	redirect_result = build_opennds_redirect(
		session_id=activated.get("session_id"),
		voucher_code=voucher.voucher_code,
		tok=tok,
		redir=redir,
		authaction=authaction,
		fas=fas,
		gatewayaddress=gatewayaddress,
		gatewayport=gatewayport,
		authdir=authdir,
		hid=hid,
		nas_device=nas_device,
	)
	if not redirect_result.get("ok"):
		return redirect_result

	return _success(
		"Payment confirmed and access granted",
		payment_ref=payment_ref,
		voucher_code=voucher.voucher_code,
		session_id=activated.get("session_id"),
		redirect_url=redirect_result.get("redirect_url"),
	)


@frappe.whitelist(allow_guest=True)
def verify_voucher(
	voucher_code: str,
	mac_address: str | None = None,
	ip_address: str | None = None,
) -> dict[str, Any]:
	voucher_code = (voucher_code or "").strip()
	if not voucher_code:
		return _error("Voucher code is required", "MISSING_VOUCHER")

	voucher = _resolve_voucher(voucher_code)
	if not voucher:
		return _error("Voucher not found", "INVALID_VOUCHER")

	plan_doc = _get_plan(voucher.plan)
	if _sync_voucher_status(voucher):
		frappe.db.commit()

	device_error = _validate_device_reuse(voucher, mac_address=mac_address, ip_address=ip_address)
	if device_error:
		return device_error

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
	if _sync_voucher_status(voucher):
		frappe.db.commit()

	mac_address = _normalize_mac(mac_address)
	ip_address = _normalize_ip(ip_address)

	device_error = _validate_device_reuse(voucher, mac_address=mac_address, ip_address=ip_address)
	if device_error:
		return device_error

	if voucher.status in {"Blocked", "Expired", "Used"}:
		return _error(f"Voucher is {voucher.status.lower()}", "VOUCHER_NOT_USABLE")

	existing_open_session = frappe.get_all(
		"Hotspot Session",
		filters={"voucher": voucher.name, "session_status": "Open"},
		ignore_permissions=True,
		fields=["name", "session_id", "mac_address", "ip_address"],
		order_by="start_time desc",
		limit=1,
	)
	if existing_open_session:
		open_session = existing_open_session[0]
		open_mac = _normalize_mac(open_session.get("mac_address"))
		open_ip = _normalize_ip(open_session.get("ip_address"))
		if open_mac and mac_address and open_mac != mac_address:
			return _error("Voucher is already active on another device", "DEVICE_MISMATCH")
		if open_ip and ip_address and open_ip != ip_address:
			return _error("Voucher is already active on another device", "DEVICE_MISMATCH")
		return _success("Voucher already active", session_id=open_session["session_id"])

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
	gatewayaddress: str | None = None,
	gatewayport: str | None = None,
	authdir: str | None = None,
	hid: str | None = None,
	nas_device: str | None = None,
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
	gatewayaddress = (gatewayaddress or "").strip()
	gatewayport = (gatewayport or "").strip()
	authdir = (authdir or "").strip()
	hid = (hid or "").strip()
	nas_device = (nas_device or "").strip()

	if not session_id:
		return _error("session_id is required", "MISSING_SESSION")
	if not voucher_code:
		return _error("voucher_code is required", "MISSING_VOUCHER")

	status_url = _build_status_url(session_id, voucher_code, upstream_redir=redir)

	if gatewayaddress and hid:
		faskey = _get_opennds_fas_key(nas_device)
		if not faskey:
			return _error("Missing openNDS FAS key", "MISSING_FAS_KEY")

		return_token = _compute_opennds_return_token(hid, faskey)
		host_port = _normalize_host_port(gatewayaddress)
		if not host_port:
			host_port = gatewayaddress
		if ":" not in host_port:
			port = gatewayport or _get_opennds_gateway_port(nas_device)
			host_port = f"{host_port}:{port}" if port else host_port

		auth_path = (authdir or _default_opennds_authdir()).lstrip("/")
		auth_base = f"http://{host_port}/{auth_path}/"
		redirect_url = _append_query(auth_base, {"tok": return_token, "redir": status_url})
		return _success("Redirect URL prepared", redirect_url=redirect_url, status_url=status_url, mode="fas-secure")

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
			"mac_address",
			"ip_address",
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
			"mac_address": s.get("mac_address"),
			"ip_address": s.get("ip_address"),
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
def restore_active_access(
	nas_identifier: str,
	secret: str,
	mac_address: str,
	ip_address: str | None = None,
) -> dict[str, Any]:
	"""
	Allow the router to restore a valid authenticated client after reboot/power loss.
	The router supplies the reconnecting client MAC/IP and a NAS shared secret.
	Frappe decides whether there is still a valid active voucher and returns the
	remaining session time so openNDS can reauthenticate without resetting the plan.
	"""
	nas_doc, error = _validate_nas_access(nas_identifier, secret)
	if error:
		return error

	mac_address = _normalize_mac(mac_address)
	ip_address = _normalize_ip(ip_address)
	if not mac_address:
		return _error("mac_address is required", "MISSING_MAC")

	voucher = _find_restorable_voucher(mac_address, nas_name=nas_doc.name)
	if not voucher:
		return _success("No restorable access", allow=False, mac_address=mac_address)

	device_error = _validate_device_reuse(voucher, mac_address=mac_address, ip_address=ip_address)
	if device_error:
		return _success(
			"Active voucher belongs to another device",
			allow=False,
			code=device_error.get("code") or "DEVICE_MISMATCH",
			mac_address=mac_address,
		)

	if voucher.expires_on and get_datetime(voucher.expires_on) <= now_datetime():
		_sync_voucher_status(voucher)
		frappe.db.commit()
		return _success("Voucher already expired", allow=False, mac_address=mac_address)

	open_session_rows = frappe.get_all(
		"Hotspot Session",
		filters={"voucher": voucher.name, "session_status": "Open"},
		fields=["name", "session_id", "mac_address", "ip_address", "nas_device"],
		order_by="start_time desc",
		limit=1,
		ignore_permissions=True,
	)

	if open_session_rows:
		session = frappe.get_doc("Hotspot Session", open_session_rows[0]["name"])
		session_changed = False
		if ip_address and session.ip_address != ip_address:
			session.ip_address = ip_address
			session_changed = True
		if session.nas_device != nas_doc.name:
			session.nas_device = nas_doc.name
			session_changed = True
		if session_changed:
			session.save(ignore_permissions=True)
	else:
		session = frappe.new_doc("Hotspot Session")
		session.session_id = f"HS-{secrets.token_hex(6).upper()}"
		session.session_status = "Open"
		session.voucher = voucher.name
		session.customer = voucher.customer
		session.nas_device = nas_doc.name
		session.mac_address = mac_address
		session.ip_address = ip_address
		session.start_time = now_datetime()
		session.insert(ignore_permissions=True)

	voucher_changed = False
	if ip_address and voucher.ip_address != ip_address:
		voucher.ip_address = ip_address
		voucher_changed = True
	if voucher.last_nas != nas_doc.name:
		voucher.last_nas = nas_doc.name
		voucher_changed = True
	if voucher_changed:
		voucher.save(ignore_permissions=True)

	frappe.db.commit()

	session_timeout_minutes = _remaining_session_minutes(voucher.expires_on)
	if session_timeout_minutes <= 0:
		return _success("Voucher already expired", allow=False, mac_address=mac_address)

	return _success(
		"Active access restored",
		allow=True,
		mac_address=mac_address,
		ip_address=ip_address,
		voucher_code=voucher.voucher_code,
		session_id=session.session_id,
		session_timeout_minutes=session_timeout_minutes,
		expires_on=voucher.expires_on,
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
		_sync_voucher_status(voucher)

	frappe.db.commit()
	return _success("Session closed", session_id=session.session_id)


@frappe.whitelist()
def request_session_deauth(session_id: str, reason: str | None = None) -> dict[str, Any]:
	"""
	Queue a session for router-side deauthentication from Desk.
	The OpenWrt agent polls the pending marker and applies ndsctl deauth.
	"""
	session_id = (session_id or "").strip()
	if not session_id:
		return _error("session_id is required", "MISSING_SESSION")

	session_name = frappe.db.get_value("Hotspot Session", {"session_id": session_id}, "name")
	if not session_name:
		return _error("Session not found", "INVALID_SESSION")

	session = frappe.get_doc("Hotspot Session", session_name)
	if session.terminate_cause and session.terminate_cause.startswith(DEAUTH_PENDING_PREFIX):
		return _success("Deauth already queued", session_id=session.session_id)

	now = now_datetime()
	session.session_status = "Terminated"
	session.stop_time = now
	if not flt(session.total_mb):
		session.total_mb = _to_mb(flt(session.input_octets) + flt(session.output_octets))

	base_reason = (reason or "Admin deauth").strip() or "Admin deauth"
	if session.mac_address or session.ip_address:
		session.terminate_cause = f"{DEAUTH_PENDING_PREFIX}{base_reason}"
	else:
		session.terminate_cause = base_reason

	session.save(ignore_permissions=True)
	voucher_consumed = False
	if session.voucher:
		voucher = frappe.get_doc("Hotspot Voucher", session.voucher)
		voucher_consumed = _consume_voucher_on_termination(voucher)
	frappe.db.commit()

	return _success(
		"Deauth queued",
		session_id=session.session_id,
		mac_address=session.mac_address,
		ip_address=session.ip_address,
		reason=base_reason,
		voucher_consumed=voucher_consumed,
	)


@frappe.whitelist(allow_guest=True)
def pull_disconnect_actions(nas_identifier: str, secret: str, limit: int = 20) -> dict[str, Any]:
	"""
	Pull pending disconnect actions (deauth queue) for router-side agent.
	Use with a NAS shared secret to avoid exposing control commands publicly.
	"""
	nas_doc, error = _validate_nas_access(nas_identifier, secret)
	if error:
		return error

	limit = max(1, min(cint(limit) or 20, 100))
	rows = frappe.get_all(
		"Hotspot Session",
		filters={"terminate_cause": ("like", f"{DEAUTH_PENDING_PREFIX}%")},
		fields=[
			"name",
			"session_id",
			"session_status",
			"terminate_cause",
			"ip_address",
			"mac_address",
			"nas_device",
			"stop_time",
		],
		order_by="modified asc",
		limit=limit,
		ignore_permissions=True,
	)

	actions = []
	for row in rows:
		# If session is bound to a specific NAS, return only matching actions.
		if row.get("nas_device") and row.get("nas_device") != nas_doc.name:
			continue

		reason = (row.get("terminate_cause") or "").replace(DEAUTH_PENDING_PREFIX, "", 1)
		actions.append(
			{
				"action_id": row.get("session_id"),
				"session_id": row.get("session_id"),
				"ip_address": row.get("ip_address"),
				"mac_address": row.get("mac_address"),
				"reason": reason or "Session ended",
				"stop_time": row.get("stop_time"),
			}
		)

	return _success("Disconnect actions fetched", actions=actions, count=len(actions))


@frappe.whitelist(allow_guest=True)
def acknowledge_disconnect_action(
	session_id: str,
	nas_identifier: str,
	secret: str,
	result: str | None = "ok",
	note: str | None = None,
) -> dict[str, Any]:
	"""
	Acknowledge that router processed a disconnect action.
	Removes DEAUTH_PENDING marker so the action is not sent again.
	"""
	nas_doc, error = _validate_nas_access(nas_identifier, secret)
	if error:
		return error

	session_id = (session_id or "").strip()
	if not session_id:
		return _error("session_id is required", "MISSING_SESSION")

	session_name = frappe.db.get_value("Hotspot Session", {"session_id": session_id}, "name")
	if not session_name:
		return _success("Session already removed", session_id=session_id)

	session = frappe.get_doc("Hotspot Session", session_name)
	if session.nas_device and session.nas_device != nas_doc.name:
		return _error("Session belongs to another NAS device", "NAS_MISMATCH")

	terminate_cause = (session.terminate_cause or "").strip()
	if terminate_cause.startswith(DEAUTH_PENDING_PREFIX):
		base = terminate_cause[len(DEAUTH_PENDING_PREFIX) :].strip() or "Session ended"
		status = (result or "ok").strip().lower()
		suffix = "router deauth ok" if status == "ok" else f"router deauth {status}"
		if note:
			suffix = f"{suffix}: {note.strip()}"
		session.terminate_cause = f"{base} ({suffix})"
		session.save(ignore_permissions=True)
		frappe.db.commit()
		return _success("Disconnect action acknowledged", session_id=session_id)

	return _success("No pending disconnect action", session_id=session_id)


@frappe.whitelist()
def seed_dummy_packages() -> dict[str, Any]:
	"""Create or update starter packages for quick portal testing."""
	result = ensure_default_hotspot_plans()
	return _success("Dummy packages seeded", **result)


@frappe.whitelist(allow_guest=True)
def sync_session_usage(
	nas_identifier: str,
	secret: str,
	usage_data: str,
) -> dict[str, Any]:
	"""
	Sync data usage (upload/download octets) for active clients from the router.
	`usage_data` must be a JSON array of objects:
	[
		{"mac_address": "aa:bb:cc:dd:ee:ff", "input_octets": 12345, "output_octets": 67890},
		...
	]
	"""
	nas_doc, error = _validate_nas_access(nas_identifier, secret)
	if error:
		return error

	if not usage_data:
		return _error("usage_data is required", "MISSING_USAGE_DATA")

	try:
		records = frappe.parse_json(usage_data)
	except Exception as e:
		return _error(f"Invalid usage_data JSON: {e}", "INVALID_JSON")

	if not isinstance(records, list):
		return _error("usage_data must be a JSON array", "INVALID_FORMAT")

	updated_count = 0
	for rec in records:
		mac = _normalize_mac(rec.get("mac_address"))
		if not mac:
			continue

		# Find open session for this MAC (matching this NAS or unset)
		sessions = frappe.get_all(
			"Hotspot Session",
			filters=[
				["mac_address", "=", mac],
				["session_status", "=", "Open"],
				["nas_device", "in", [nas_doc.name, "", None]]
			],
			fields=["name", "voucher", "nas_device", "input_octets", "output_octets", "ip_address", "customer"],
			limit=1,
			ignore_permissions=True,
		)
		if not sessions:
			continue

		session_name = sessions[0]["name"]
		session_doc = sessions[0]
		
		# Auto-populate NAS device link if it was missing/unset
		nas_device = session_doc.get("nas_device") or nas_doc.name
		
		# Calculate session traffic fields
		input_octets = flt(rec.get("input_octets") or 0)
		output_octets = flt(rec.get("output_octets") or 0)
		
		# Check if router counters have reset or overflowed (shrunk below database level)
		if input_octets < flt(session_doc.get("input_octets") or 0) or output_octets < flt(session_doc.get("output_octets") or 0):
			# Counters have shrunk! This is a reset/overflow.
			# Close the old session
			old_session = frappe.get_doc("Hotspot Session", session_name)
			old_session.session_status = "Closed"
			old_session.stop_time = now_datetime()
			old_session.save(ignore_permissions=True)
			
			# Create a brand new session for the fresh counters
			new_session = frappe.new_doc("Hotspot Session")
			new_session.session_id = f"HS-{secrets.token_hex(6).upper()}"
			new_session.session_status = "Open"
			new_session.voucher = session_doc.get("voucher")
			new_session.customer = session_doc.get("customer")
			new_session.nas_device = nas_device
			new_session.mac_address = mac
			new_session.ip_address = session_doc.get("ip_address")
			new_session.start_time = now_datetime()
			new_session.input_octets = input_octets
			new_session.output_octets = output_octets
			new_session.total_mb = _to_mb(input_octets + output_octets)
			new_session.insert(ignore_permissions=True)
			
			target_session_name = new_session.name
			target_total_mb = new_session.total_mb
		else:
			# Normal case: update existing session
			total_mb = _to_mb(input_octets + output_octets)
			frappe.db.set_value(
				"Hotspot Session",
				session_name,
				{
					"nas_device": nas_device,
					"input_octets": input_octets,
					"output_octets": output_octets,
					"total_mb": total_mb
				},
				update_modified=False
			)
			target_session_name = session_name
			target_total_mb = total_mb
		
		# Also update the parent Hotspot Voucher immediately in real-time
		voucher_name = session_doc.get("voucher")
		if voucher_name:
			# Sum data used across all sessions of this voucher
			voucher_sessions = frappe.get_all(
				"Hotspot Session",
				filters={"voucher": voucher_name},
				fields=["name", "total_mb"],
				ignore_permissions=True,
			)
			total_voucher_mb = 0.0
			for vs in voucher_sessions:
				if vs["name"] == target_session_name:
					total_voucher_mb += flt(target_total_mb)
				else:
					total_voucher_mb += flt(vs.get("total_mb") or 0)
			
			frappe.db.set_value(
				"Hotspot Voucher",
				voucher_name,
				{
					"data_used_mb": round(total_voucher_mb, 2),
					"data_used_gb": round(total_voucher_mb / 1024.0, 3)
				},
				update_modified=False
			)
		
		updated_count += 1

	if updated_count > 0:
		frappe.db.commit()

	return _success("Session usage synchronized", updated_sessions=updated_count)


@frappe.whitelist(allow_guest=True)
def get_random_active_ad(mac_address: str | None = None) -> dict[str, Any]:
	"""
	Returns an active ad to display to the user.
	Implements the Least-Shown-First equal exposure algorithm.
	"""
	mac_address = _normalize_mac(mac_address)
	if mac_address:
		free_plans = frappe.get_all(
			"Hotspot Plan",
			filters={"enabled": 1, "is_free": 1},
			fields=["name", "max_slices_per_day"],
			ignore_permissions=True,
			limit=1,
		)
		if free_plans:
			plan_name = free_plans[0]["name"]
			max_slices = cint(free_plans[0].get("max_slices_per_day")) or 4
			
			today_start = now_datetime().replace(hour=0, minute=0, second=0, microsecond=0)
			voucher = frappe.get_all(
				"Hotspot Voucher",
				filters={
					"plan": plan_name,
					"device_mac": mac_address,
					"generated_on": (">=", today_start),
				},
				fields=["name", "ad_slices_used", "status"],
				ignore_permissions=True,
				limit=1,
			)
			if voucher and (cint(voucher[0].ad_slices_used) >= max_slices or voucher[0].status == "Expired"):
				return _error(
					frappe._("You have reached your daily limit of free access today. Please buy a package to continue!"),
					"FREE_LIMIT_REACHED"
				)

	active_ads = frappe.get_all(
		"Hotspot Ad",
		filters={"status": "Active"},
		fields=["name", "title", "ad_type", "video_file", "cta_url", "views_limit", "views_count"],
		ignore_permissions=True,
	)
	
	valid_ads = [ad for ad in active_ads if cint(ad.views_count) < cint(ad.views_limit)]
	
	if not valid_ads:
		return {
			"ok": True,
			"ad": {
				"name": "Fallback",
				"title": "Welcome to Tanzania Hotspot",
				"ad_type": "Text",
				"cta_url": "",
				"video_file": ""
			}
		}
	
	valid_ads.sort(key=lambda x: cint(x.views_count))
	lowest_views = cint(valid_ads[0]["views_count"])
	best_candidates = [ad for ad in valid_ads if cint(ad["views_count"]) == lowest_views]
	
	import random
	selected_ad = random.choice(best_candidates)
	
	return {
		"ok": True,
		"ad": {
			"name": selected_ad.name,
			"title": selected_ad.title,
			"ad_type": selected_ad.ad_type,
			"cta_url": selected_ad.cta_url or "",
			"video_file": selected_ad.video_file or ""
		}
	}


@frappe.whitelist(allow_guest=True)
def check_free_slice_status(mac_address: str) -> dict[str, Any]:
	"""
	Checks the current daily free tier progress for a MAC address.
	"""
	mac_address = _normalize_mac(mac_address)
	if not mac_address:
		return _error("MAC address is required", "MISSING_MAC")
	
	free_plans = frappe.get_all(
		"Hotspot Plan",
		filters={"enabled": 1, "is_free": 1},
		fields=["name", "validity_value", "validity_unit", "max_slices_per_day"],
		ignore_permissions=True,
		limit=1,
	)
	if not free_plans:
		return {
			"ok": True,
			"allowed": False,
			"reason": "NO_FREE_PLAN",
			"message": frappe._("No free plan is currently active.")
		}
		
	plan_doc = free_plans[0]
	plan_name = plan_doc["name"]
	max_slices = cint(plan_doc.get("max_slices_per_day")) or 4
	
	today_start = now_datetime().replace(hour=0, minute=0, second=0, microsecond=0)
	voucher = frappe.get_all(
		"Hotspot Voucher",
		filters={
			"plan": plan_name,
			"device_mac": mac_address,
			"generated_on": (">=", today_start),
		},
		fields=["name", "ad_slices_used", "status"],
		ignore_permissions=True,
		limit=1,
	)
	
	if not voucher:
		return {
			"ok": True,
			"allowed": True,
			"ad_slices_used": 0,
			"max_slices_per_day": max_slices,
			"slice_duration_val": cint(plan_doc.get("validity_value")) or 15,
			"slice_duration_unit": plan_doc.get("validity_unit") or "Minutes"
		}
	
	slices_used = cint(voucher[0].get("ad_slices_used") or 0)
	is_expired = voucher[0].get("status") == "Expired"
	allowed = bool(slices_used < max_slices and not is_expired)
	
	return {
		"ok": True,
		"allowed": allowed,
		"ad_slices_used": slices_used,
		"max_slices_per_day": max_slices,
		"slice_duration_val": cint(plan_doc.get("validity_value")) or 15,
		"slice_duration_unit": plan_doc.get("validity_unit") or "Minutes",
		"reason": "LIMIT_REACHED" if not allowed else "PROGRESS"
	}


@frappe.whitelist(allow_guest=True)
def log_ad_view_and_claim_slice(
	mac_address: str,
	ad_id: str,
	ip_address: str | None = None,
	nas_device: str | None = None
) -> dict[str, Any]:
	"""
	Logs the ad view event and updates the daily free voucher with a new 15-minute slice.
	"""
	mac_address = _normalize_mac(mac_address)
	ip_address = _normalize_ip(ip_address)
	
	if not mac_address:
		return _error("Device MAC address is required", "MISSING_MAC")
	
	if ad_id and ad_id != "Fallback":
		try:
			ad = frappe.get_doc("Hotspot Ad", ad_id)
			ad.views_count = cint(ad.views_count) + 1
			if ad.views_count >= ad.views_limit:
				ad.status = "Completed"
			ad.save(ignore_permissions=True)
			
			log = frappe.new_doc("Hotspot Ad View Log")
			log.ad = ad_id
			log.viewer_mac = mac_address
			log.viewer_ip = ip_address
			log.insert(ignore_permissions=True)
		except Exception as e:
			frappe.log_error(f"Error logging ad view: {e}", "Ad Platform Error")

	free_plans = frappe.get_all(
		"Hotspot Plan",
		filters={"enabled": 1, "is_free": 1},
		fields=["name", "validity_value", "validity_unit", "max_slices_per_day", "data_limit_mb"],
		ignore_permissions=True,
		limit=1,
	)
	if not free_plans:
		return _error("No free plan is currently available", "NO_FREE_PLAN")
	
	plan_doc = free_plans[0]
	plan_name = plan_doc["name"]
	slice_duration_val = cint(plan_doc.get("validity_value")) or 15
	slice_duration_unit = (plan_doc.get("validity_unit") or "Minutes").lower()
	max_slices = cint(plan_doc.get("max_slices_per_day")) or 4

	now = now_datetime()
	if slice_duration_unit.startswith("minute"):
		slice_expiry = add_to_date(now, minutes=slice_duration_val)
	elif slice_duration_unit.startswith("hour"):
		slice_expiry = add_to_date(now, hours=slice_duration_val)
	else:
		slice_expiry = add_to_date(now, days=slice_duration_val)

	today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
	existing_voucher = frappe.get_all(
		"Hotspot Voucher",
		filters={
			"plan": plan_name,
			"device_mac": mac_address,
			"generated_on": (">=", today_start),
		},
		fields=["name", "ad_slices_used", "status"],
		ignore_permissions=True,
		limit=1,
	)

	if existing_voucher:
		voucher_doc = frappe.get_doc("Hotspot Voucher", existing_voucher[0]["name"])
		if cint(voucher_doc.ad_slices_used) >= max_slices or voucher_doc.status == "Expired":
			return _error("You have reached your daily limit of free access.", "FREE_LIMIT_REACHED")
		
		voucher_doc.ad_slices_used = cint(voucher_doc.ad_slices_used) + 1
		voucher_doc.current_slice_expires_on = slice_expiry
		voucher_doc.status = "Active"
		voucher_doc.save(ignore_permissions=True)
		voucher_code = voucher_doc.voucher_code
	else:
		voucher_doc = frappe.new_doc("Hotspot Voucher")
		voucher_doc.voucher_code = f"FREE-{secrets.token_hex(5).upper()}"
		voucher_doc.status = "Active"
		voucher_doc.plan = plan_name
		voucher_doc.device_mac = mac_address
		if ip_address:
			voucher_doc.ip_address = ip_address
		if flt(plan_doc.get("data_limit_mb")) > 0:
			voucher_doc.data_limit_mb = flt(plan_doc.get("data_limit_mb"))
		voucher_doc.ad_slices_used = 1
		voucher_doc.current_slice_expires_on = slice_expiry
		voucher_doc.insert(ignore_permissions=True)
		voucher_code = voucher_doc.voucher_code

	frappe.db.commit()

	result = activate_voucher(
		voucher_code=voucher_code,
		mac_address=mac_address,
		ip_address=ip_address,
		nas_device=nas_device,
	)
	
	if not result.get("ok"):
		return result

	result["voucher_code"] = voucher_code
	result["ad_slices_used"] = voucher_doc.ad_slices_used
	result["max_slices_per_day"] = max_slices
	result["message"] = frappe._("Ad watched successfully! Internet unlocked for next {0} {1}.").format(
		slice_duration_val,
		frappe._(plan_doc.get("validity_unit") or "Minutes")
	)
	return result


@frappe.whitelist(allow_guest=True)
def get_advertiser_dashboard(advertiser_email: str) -> dict[str, Any]:
	"""
	Returns all ad assets and view log metrics for the advertiser's dashboard.
	"""
	advertiser_email = (advertiser_email or "").strip().lower()
	if not advertiser_email:
		return _error("Advertiser email is required", "MISSING_EMAIL")
	
	ads = frappe.get_all(
		"Hotspot Ad",
		filters={"advertiser_email": advertiser_email},
		fields=["name", "title", "ad_type", "video_file", "cta_url", "status", "views_limit", "views_count"],
		ignore_permissions=True,
		order_by="creation desc"
	)
	
	total_views = sum(cint(ad.get("views_count") or 0) for ad in ads)
	
	from frappe.utils import add_days, getdate
	last_7_days = {}
	for i in range(7):
		day = getdate(add_days(now_datetime(), -i))
		last_7_days[str(day)] = 0
		
	ad_names = [ad["name"] for ad in ads]
	if ad_names:
		logs = frappe.get_all(
			"Hotspot Ad View Log",
			filters={
				"ad": ("in", ad_names),
				"viewed_on": (">=", add_days(now_datetime(), -7))
			},
			fields=["viewed_on"],
			ignore_permissions=True
		)
		for log in logs:
			day_str = str(getdate(log["viewed_on"]))
			if day_str in last_7_days:
				last_7_days[day_str] += 1
				
	chart_data = [{"date": k, "views": v} for k, v in sorted(last_7_days.items())]
	
	return {
		"ok": True,
		"ads": ads,
		"total_ads": len(ads),
		"total_views": total_views,
		"chart_data": chart_data
	}


@frappe.whitelist(allow_guest=True)
def create_advertiser_ad(
	advertiser_email: str,
	title: str,
	ad_type: str,
	cta_url: str | None = None,
	video_file: str | None = None,
	views_limit: int = 1000
) -> dict[str, Any]:
	"""
	Submit a new Ad asset for approval.
	"""
	advertiser_email = (advertiser_email or "").strip().lower()
	title = (title or "").strip()
	ad_type = (ad_type or "").strip()
	
	if not (advertiser_email and title and ad_type):
		return _error("Email, Title, and Ad Type are required fields", "MISSING_FIELDS")
	
	exists = frappe.db.exists("Hotspot Ad", {"title": title})
	if exists:
		return _error("An ad with this title already exists. Please choose a different title.", "DUPLICATE_TITLE")
	
	ad = frappe.new_doc("Hotspot Ad")
	ad.advertiser_email = advertiser_email
	ad.title = title
	ad.ad_type = ad_type
	ad.cta_url = cta_url
	ad.video_file = video_file
	ad.status = "Pending Approval"
	ad.views_limit = cint(views_limit) or 1000
	ad.views_count = 0
	ad.insert(ignore_permissions=True)
	frappe.db.commit()
	
	return {
		"ok": True,
		"message": frappe._("Ad submitted successfully and is pending admin approval!"),
		"ad": ad.name
	}


@frappe.whitelist(allow_guest=True)
def upload_ad_media(file_name: str, file_data: str) -> dict[str, Any]:
	"""
	Saves base64 media file to the public files folder and returns its URL.
	"""
	import base64
	from frappe.utils.file_manager import save_file
	
	if "," in file_data:
		file_data = file_data.split(",")[1]
		
	decoded_data = base64.b64decode(file_data)
	
	file_doc = save_file(
		fname=file_name,
		content=decoded_data,
		dt="Hotspot Ad",
		dn="Temp",
		is_private=0
	)
	
	return {
		"ok": True,
		"file_url": file_doc.file_url
	}


@frappe.whitelist(allow_guest=True)
def register_advertiser(email: str, password: str) -> dict[str, Any]:
	"""
	Registers a new advertiser as a secure Frappe User.
	"""
	email = (email or "").strip().lower()
	password = (password or "").strip()
	
	if not (email and password):
		return {"ok": False, "message": frappe._("Email and password are required")}
		
	if frappe.db.exists("User", email):
		return {"ok": False, "message": frappe._("This email address is already registered. Please sign in.")}
		
	try:
		user = frappe.new_doc("User")
		user.email = email
		user.first_name = email.split("@")[0]
		user.send_welcome_email = 0
		user.new_password = password
		user.insert(ignore_permissions=True)
		frappe.db.commit()
		return {"ok": True, "message": frappe._("Registration successful!")}
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "Register Advertiser Failed")
		return {"ok": False, "message": str(e)}


@frappe.whitelist(allow_guest=True)
def login_advertiser(email: str, password: str) -> dict[str, Any]:
	"""
	Secures advertiser dashboard login by verifying passwords natively.
	"""
	from frappe.utils.password import check_password as verify_pw
	
	email = (email or "").strip().lower()
	password = (password or "").strip()
	
	if not (email and password):
		return {"ok": False, "message": frappe._("Email and password are required")}
		
	if not frappe.db.exists("User", email):
		return {"ok": False, "message": frappe._("Email not found. Please register first.")}
	
	try:
		verify_pw(email, password)
		return {"ok": True, "message": frappe._("Login successful!")}
	except frappe.AuthenticationError:
		return {"ok": False, "message": frappe._("Invalid email or password.")}
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Login Advertiser Failed")
		return {"ok": False, "message": frappe._("An error occurred during authentication.")}


