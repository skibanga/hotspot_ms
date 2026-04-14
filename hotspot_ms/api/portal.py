from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import string
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from typing import Any

import frappe
from frappe.utils import add_to_date, cint, flt, get_datetime, now_datetime

from hotspot_ms.defaults import ensure_default_hotspot_plans

DEAUTH_PENDING_PREFIX = "DEAUTH_PENDING|"


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

	if gatewayaddress and authdir and hid:
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

		auth_path = authdir.lstrip("/")
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
