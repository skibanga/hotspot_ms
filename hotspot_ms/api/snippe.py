from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from typing import Any

import frappe
import requests
from frappe.utils import cint, flt, get_url, now_datetime


def _ok(message: str, **data: Any) -> dict[str, Any]:
	result = {"ok": True, "message": message}
	result.update(data)
	return result


def _err(message: str, code: str = "ERROR", http_status: int = 400) -> dict[str, Any]:
	frappe.local.response["http_status_code"] = http_status
	return {"ok": False, "code": code, "message": message}


def _get_settings(require_enabled: bool = True, require_api_key: bool = True):
	settings = frappe.get_single("Snippe Settings")
	if require_enabled and not cint(settings.enabled):
		return None, _err("Snippe integration is disabled", "SNIPPE_DISABLED", 503)

	api_key = (settings.get_password("api_key") or "").strip()
	if require_api_key and not api_key:
		return None, _err("Snippe API key is not configured", "SNIPPE_API_KEY_MISSING", 500)

	base_url = (settings.base_url or "https://api.snippe.sh").strip().rstrip("/")
	timeout = max(5, min(cint(settings.request_timeout) or 30, 120))
	default_currency = (settings.default_currency or "TZS").strip().upper()
	default_payment_type = (settings.default_payment_type or "mobile").strip()
	webhook_url = (settings.webhook_url or "").strip()
	webhook_secret = (settings.get_password("webhook_secret") or "").strip()

	return {
		"doc": settings,
		"api_key": api_key,
		"base_url": base_url,
		"timeout": timeout,
		"default_currency": default_currency,
		"default_payment_type": default_payment_type,
		"webhook_url": webhook_url,
		"webhook_secret": webhook_secret,
	}, None


def _snippe_request(
	settings: dict[str, Any],
	method: str,
	path: str,
	*,
	payload: dict[str, Any] | None = None,
	idempotency_key: str | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
	url = f"{settings['base_url']}{path}"
	headers = {
		"Authorization": f"Bearer {settings['api_key']}",
		"Content-Type": "application/json",
	}
	if idempotency_key:
		headers["Idempotency-Key"] = idempotency_key

	try:
		response = requests.request(
			method=method.upper(),
			url=url,
			headers=headers,
			json=payload,
			timeout=settings["timeout"],
		)
	except requests.RequestException as exc:
		return None, _err(f"Snippe request failed: {exc}", "SNIPPE_REQUEST_FAILED", 502)

	try:
		body = response.json()
	except ValueError:
		body = {"status": "error", "code": response.status_code, "message": response.text}

	if response.status_code >= 400 or body.get("status") == "error":
		frappe.local.response["http_status_code"] = response.status_code or 400
		return None, {
			"ok": False,
			"code": "SNIPPE_API_ERROR",
			"message": body.get("message") or "Snippe API returned an error",
			"snippe_response": body,
			"http_status": response.status_code,
		}

	return body, None


def _new_payment_ref() -> str:
	return f"PT-{secrets.token_hex(6).upper()}"


def _safe_json_text(data: Any) -> str:
	try:
		return json.dumps(data, ensure_ascii=True, separators=(",", ":"))
	except Exception:
		return str(data)


def _status_from_snippe(snippe_status: str | None) -> str:
	value = (snippe_status or "").strip().lower()
	if value == "completed":
		return "Successful"
	if value in {"failed", "voided"}:
		return "Failed"
	if value == "expired":
		return "Cancelled"
	return "Pending"


def _issue_voucher(plan_name: str, customer: str | None = None):
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


def _parse_metadata(metadata_json: str | None) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
	if not metadata_json:
		return {}, None

	try:
		incoming = json.loads(metadata_json)
	except json.JSONDecodeError:
		return None, _err("metadata_json must be valid JSON object", "INVALID_METADATA")

	if not isinstance(incoming, dict):
		return None, _err("metadata_json must be a JSON object", "INVALID_METADATA")

	return incoming, None


def _resolve_allowed_methods(allowed_methods: str | None) -> list[str]:
	if not allowed_methods:
		return ["mobile_money", "qr"]

	mapping = {
		"mobile": "mobile_money",
		"mobile_money": "mobile_money",
		"qr": "qr",
		"dynamic-qr": "qr",
		"card": "card",
	}
	values = []
	for item in allowed_methods.split(","):
		key = item.strip().lower()
		if key in mapping and mapping[key] not in values:
			values.append(mapping[key])
	return values or ["mobile_money", "qr"]


def _create_payment_transaction(
	*,
	payment_ref: str,
	plan_doc,
	customer: str | None,
	payment_type: str,
	idempotency_key: str,
	currency: str,
	response: dict[str, Any],
) -> Any:
	data = (response or {}).get("data") or {}
	tx = frappe.new_doc("Payment Transaction")
	tx.payment_ref = payment_ref
	tx.status = _status_from_snippe(data.get("status"))
	tx.plan = plan_doc.name
	tx.amount = flt(plan_doc.price)
	tx.currency = currency
	tx.customer = customer
	tx.provider = "Snippe"
	tx.payment_type = payment_type
	tx.idempotency_key = idempotency_key
	tx.external_id = data.get("reference") or data.get("id")
	tx.checkout_url = data.get("payment_link_url") or data.get("checkout_url")
	tx.payment_url = data.get("payment_url")
	tx.provider_response_code = str((response or {}).get("code") or "")
	tx.provider_response_message = data.get("status") or "pending"
	tx.notes = _safe_json_text(response)
	if tx.status == "Successful" and not tx.completed_on:
		tx.completed_on = now_datetime()
	tx.insert(ignore_permissions=True)
	return tx


def _get_transaction_by_reference(snippe_reference: str | None, payment_ref: str | None = None) -> str | None:
	if snippe_reference:
		name = frappe.db.get_value("Payment Transaction", {"external_id": snippe_reference}, "name")
		if name:
			return name
	if payment_ref:
		return frappe.db.get_value("Payment Transaction", {"payment_ref": payment_ref}, "name")
	return None


@frappe.whitelist()
def get_snippe_settings() -> dict[str, Any]:
	settings, error = _get_settings(require_enabled=False, require_api_key=False)
	if error:
		return error

	doc = settings["doc"]
	return _ok(
		"Snippe settings loaded",
		settings={
			"enabled": cint(doc.enabled),
			"base_url": settings["base_url"],
			"default_currency": settings["default_currency"],
			"default_payment_type": settings["default_payment_type"],
			"webhook_url": settings["webhook_url"],
			"auto_issue_voucher": cint(doc.auto_issue_voucher),
		},
	)


@frappe.whitelist(allow_guest=True)
def create_snippe_payment(
	plan: str,
	payment_type: str | None = None,
	phone_number: str | None = None,
	firstname: str | None = None,
	lastname: str | None = None,
	email: str | None = None,
	address: str | None = None,
	city: str | None = None,
	state: str | None = None,
	postcode: str | None = None,
	country: str | None = None,
	redirect_url: str | None = None,
	cancel_url: str | None = None,
	allowed_methods: str | None = None,
	allow_custom_amount: int | None = None,
	min_amount: float | None = None,
	max_amount: float | None = None,
	description: str | None = None,
	expires_in: int | None = None,
	customer_name: str | None = None,
	customer: str | None = None,
	webhook_url: str | None = None,
	metadata_json: str | None = None,
	idempotency_key: str | None = None,
) -> dict[str, Any]:
	settings, error = _get_settings(require_enabled=True, require_api_key=True)
	if error:
		return error

	plan_doc = frappe.get_doc("Hotspot Plan", plan)
	if not cint(plan_doc.enabled):
		return _err("Selected plan is disabled", "PLAN_DISABLED")

	payment_type = (payment_type or settings["default_payment_type"] or "mobile").strip().lower()
	if payment_type not in {"mobile", "card", "dynamic-qr", "session"}:
		return _err("Unsupported payment_type. Use mobile, card, dynamic-qr or session.", "INVALID_PAYMENT_TYPE")

	amount_value = int(round(flt(plan_doc.price)))
	if amount_value <= 0:
		return _err("Plan price must be greater than zero", "INVALID_PLAN_PRICE")

	firstname = (firstname or "Hotspot").strip()
	lastname = (lastname or "Customer").strip()
	email = (email or "noreply@hotspot.local").strip()
	currency = (plan_doc.currency or settings["default_currency"] or "TZS").strip().upper()
	resolved_webhook = (webhook_url or settings["webhook_url"] or "").strip()
	if not resolved_webhook:
		resolved_webhook = f"{get_url()}/api/method/hotspot_ms.api.snippe.snippe_webhook"

	metadata: dict[str, Any] = {
		"plan_name": plan_doc.name,
		"plan_label": plan_doc.plan_name,
	}
	if customer:
		metadata["customer"] = customer
	incoming_metadata, metadata_error = _parse_metadata(metadata_json)
	if metadata_error:
		return metadata_error
	metadata.update(incoming_metadata or {})

	idempotency_key = (idempotency_key or f"hs-{secrets.token_hex(8)}").strip()
	payment_ref = _new_payment_ref()
	metadata["payment_ref"] = payment_ref

	if payment_type == "session":
		session_payload: dict[str, Any] = {
			"amount": amount_value,
			"currency": currency,
			"allowed_methods": _resolve_allowed_methods(allowed_methods),
			"description": (description or plan_doc.plan_name or plan_doc.name).strip(),
			"webhook_url": resolved_webhook,
			"metadata": metadata,
		}
		if redirect_url:
			session_payload["redirect_url"] = redirect_url.strip()
		if cint(expires_in):
			session_payload["expires_in"] = max(60, min(cint(expires_in), 86400))
		if cint(allow_custom_amount):
			min_amount_value = int(round(flt(min_amount)))
			max_amount_value = int(round(flt(max_amount)))
			if min_amount_value <= 0 or max_amount_value <= 0 or min_amount_value >= max_amount_value:
				return _err("For allow_custom_amount=1, set valid min_amount and max_amount", "INVALID_CUSTOM_AMOUNT")
			session_payload["allow_custom_amount"] = True
			session_payload["min_amount"] = min_amount_value
			session_payload["max_amount"] = max_amount_value

		session_customer: dict[str, Any] = {}
		if customer_name:
			session_customer["name"] = customer_name.strip()
		if phone_number:
			session_customer["phone"] = phone_number.strip()
		if email:
			session_customer["email"] = email
		if session_customer:
			session_payload["customer"] = session_customer

		session_response, session_error = _snippe_request(
			settings,
			"POST",
			"/api/v1/sessions",
			payload=session_payload,
			idempotency_key=idempotency_key,
		)
		if session_error:
			return session_error

		tx = _create_payment_transaction(
			payment_ref=payment_ref,
			plan_doc=plan_doc,
			customer=customer,
			payment_type=payment_type,
			idempotency_key=idempotency_key,
			currency=currency,
			response=session_response or {},
		)
		frappe.db.commit()
		return _ok(
			"Snippe checkout session created",
			payment_ref=tx.payment_ref,
			transaction=tx.name,
			snippe=session_response,
		)

	payload: dict[str, Any] = {
		"payment_type": payment_type,
		"details": {"amount": amount_value, "currency": currency},
		"customer": {
			"firstname": firstname,
			"lastname": lastname,
			"email": email,
		},
		"webhook_url": resolved_webhook,
		"metadata": metadata,
	}

	if payment_type == "mobile":
		if not (phone_number or "").strip():
			return _err("phone_number is required for mobile payments", "MISSING_PHONE")
		payload["phone_number"] = (phone_number or "").strip()
	elif payment_type == "card":
		redirect_url = (redirect_url or "").strip()
		cancel_url = (cancel_url or "").strip()
		if not redirect_url or not cancel_url:
			return _err("redirect_url and cancel_url are required for card payments", "MISSING_REDIRECT_URLS")
		payload["details"]["redirect_url"] = redirect_url
		payload["details"]["cancel_url"] = cancel_url
		missing = [
			key
			for key, value in {
				"address": address,
				"city": city,
				"state": state,
				"postcode": postcode,
				"country": country,
			}.items()
			if not (value or "").strip()
		]
		if missing:
			return _err(f"Missing required card customer fields: {', '.join(missing)}", "MISSING_CARD_FIELDS")
		payload["customer"].update(
			{
				"address": (address or "").strip(),
				"city": (city or "").strip(),
				"state": (state or "").strip(),
				"postcode": (postcode or "").strip(),
				"country": (country or "").strip().upper(),
			}
		)

	response, request_error = _snippe_request(
		settings,
		"POST",
		"/v1/payments",
		payload=payload,
		idempotency_key=idempotency_key,
	)
	if request_error:
		return request_error

	tx = _create_payment_transaction(
		payment_ref=payment_ref,
		plan_doc=plan_doc,
		customer=customer,
		payment_type=payment_type,
		idempotency_key=idempotency_key,
		currency=currency,
		response=response or {},
	)

	frappe.db.commit()
	return _ok(
		"Snippe payment created",
		payment_ref=tx.payment_ref,
		transaction=tx.name,
		snippe=response,
	)


@frappe.whitelist(allow_guest=True)
def create_snippe_session(
	plan: str,
	phone_number: str | None = None,
	email: str | None = None,
	customer_name: str | None = None,
	redirect_url: str | None = None,
	allowed_methods: str | None = None,
	allow_custom_amount: int | None = None,
	min_amount: float | None = None,
	max_amount: float | None = None,
	description: str | None = None,
	expires_in: int | None = None,
	customer: str | None = None,
	webhook_url: str | None = None,
	metadata_json: str | None = None,
	idempotency_key: str | None = None,
) -> dict[str, Any]:
	return create_snippe_payment(
		plan=plan,
		payment_type="session",
		phone_number=phone_number,
		email=email,
		customer_name=customer_name,
		redirect_url=redirect_url,
		allowed_methods=allowed_methods,
		allow_custom_amount=allow_custom_amount,
		min_amount=min_amount,
		max_amount=max_amount,
		description=description,
		expires_in=expires_in,
		customer=customer,
		webhook_url=webhook_url,
		metadata_json=metadata_json,
		idempotency_key=idempotency_key,
	)


@frappe.whitelist()
def sync_snippe_payment_status(payment_ref: str) -> dict[str, Any]:
	settings, error = _get_settings(require_enabled=True, require_api_key=True)
	if error:
		return error

	tx_name = frappe.db.get_value("Payment Transaction", {"payment_ref": payment_ref}, "name")
	if not tx_name:
		return _err("Payment transaction not found", "PAYMENT_NOT_FOUND", 404)

	tx = frappe.get_doc("Payment Transaction", tx_name)
	if not tx.external_id:
		return _err("Payment transaction has no external reference", "MISSING_EXTERNAL_REFERENCE")

	path = f"/v1/payments/{tx.external_id}"
	if (tx.payment_type or "").strip().lower() == "session":
		path = f"/api/v1/sessions/{tx.external_id}"

	response, request_error = _snippe_request(settings, "GET", path)
	if request_error:
		return request_error

	data = (response or {}).get("data") or {}
	tx.status = _status_from_snippe(data.get("status"))
	tx.provider_response_code = str((response or {}).get("code") or "")
	tx.provider_response_message = data.get("status") or tx.provider_response_message
	tx.notes = _safe_json_text(response)
	if tx.status == "Successful" and not tx.completed_on:
		tx.completed_on = now_datetime()
	tx.save(ignore_permissions=True)
	frappe.db.commit()

	return _ok("Payment status synced", payment_ref=tx.payment_ref, status=tx.status, snippe=response)


@frappe.whitelist(allow_guest=True)
def snippe_webhook() -> dict[str, Any]:
	settings, error = _get_settings(require_enabled=False, require_api_key=False)
	if error:
		return error

	raw_body = frappe.request.get_data(as_text=True) or ""
	signature = (frappe.get_request_header("X-Webhook-Signature") or "").strip()
	webhook_secret = settings["webhook_secret"]
	if webhook_secret:
		expected = hmac.new(webhook_secret.encode(), raw_body.encode(), hashlib.sha256).hexdigest()
		if not hmac.compare_digest(expected, signature):
			return _err("Invalid webhook signature", "INVALID_WEBHOOK_SIGNATURE", 401)

	try:
		payload = json.loads(raw_body or "{}")
	except json.JSONDecodeError:
		return _err("Invalid webhook JSON payload", "INVALID_WEBHOOK_PAYLOAD")

	event_type = (payload.get("type") or frappe.get_request_header("X-Webhook-Event") or "").strip()
	event_id = (payload.get("id") or "").strip()
	data = payload.get("data") or {}
	reference = (data.get("reference") or "").strip()
	session_reference = (data.get("session_reference") or "").strip()
	metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
	payment_ref = (metadata.get("payment_ref") or "").strip()

	tx_name = _get_transaction_by_reference(reference, payment_ref=payment_ref)
	if not tx_name and session_reference:
		tx_name = _get_transaction_by_reference(session_reference, payment_ref=payment_ref)
	if not tx_name:
		# Accept webhook to prevent repeated retries, but surface mismatch.
		return _ok(
			"Webhook received but transaction not found",
			reference=reference,
			session_reference=session_reference,
			event_type=event_type,
		)

	tx = frappe.get_doc("Payment Transaction", tx_name)
	tx.external_id = session_reference or reference or tx.external_id
	tx.webhook_event_id = event_id
	tx.webhook_payload = raw_body
	tx.provider_response_message = event_type or tx.provider_response_message
	tx.provider_response_code = str(payload.get("code") or tx.provider_response_code or "")

	snippe_status = (data.get("status") or "").strip().lower()
	if event_type == "payment.completed" or snippe_status == "completed":
		tx.status = "Successful"
		if not tx.completed_on:
			tx.completed_on = now_datetime()
	elif event_type == "payment.failed" or snippe_status in {"failed", "voided"}:
		tx.status = "Failed"
	elif snippe_status == "expired":
		tx.status = "Cancelled"
	else:
		tx.status = tx.status or "Pending"

	if tx.status == "Successful" and not tx.voucher and cint(settings["doc"].auto_issue_voucher):
		plan_name = (metadata.get("plan_name") or tx.plan or "").strip()
		if plan_name and frappe.db.exists("Hotspot Plan", plan_name):
			voucher = _issue_voucher(plan_name, customer=tx.customer)
			tx.voucher = voucher.name

	tx.save(ignore_permissions=True)
	frappe.db.commit()

	return _ok("Webhook processed", payment_ref=tx.payment_ref, status=tx.status, voucher=tx.voucher)
