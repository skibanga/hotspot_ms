import frappe


DEFAULT_PORTAL_BRAND = "Hapa Kitonga WiFi"


def _sanitize_phone_for_tel(value: str | None) -> str:
	if not value:
		return ""

	value = value.strip()
	if not value:
		return ""

	allowed = []
	for ch in value:
		if ch.isdigit() or ch == "+":
			allowed.append(ch)

	sanitized = "".join(allowed)
	return sanitized if any(ch.isdigit() for ch in sanitized) else ""


def get_portal_branding() -> dict[str, str]:
	brand = DEFAULT_PORTAL_BRAND
	customer_support_number = ""
	enable_maintenance_mode = 0
	maintenance_message = ""

	try:
		configured_brand = frappe.db.get_single_value("Hotspot Settings", "portal_brand")
		if configured_brand:
			brand = configured_brand.strip() or DEFAULT_PORTAL_BRAND

		configured_support = frappe.db.get_single_value("Hotspot Settings", "customer_support_number")
		if configured_support:
			customer_support_number = configured_support.strip()
			
		enable_maintenance_mode = frappe.db.get_single_value("Hotspot Settings", "enable_maintenance_mode") or 0
		maintenance_message = frappe.db.get_single_value("Hotspot Settings", "maintenance_message") or ""
	except Exception:
		# Keep portal pages renderable even before migrate creates the singleton.
		pass

	return {
		"portal_brand": brand,
		"portal_login_title": f"{brand} Login",
		"portal_status_title": f"Session Status | {brand}",
		"customer_support_number": customer_support_number,
		"customer_support_tel": _sanitize_phone_for_tel(customer_support_number),
		"enable_maintenance_mode": enable_maintenance_mode,
		"maintenance_message": maintenance_message,
	}
