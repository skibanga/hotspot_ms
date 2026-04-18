import frappe


DEFAULT_PORTAL_BRAND = "Hapa Kitonga WiFi"


def get_portal_branding() -> dict[str, str]:
	brand = DEFAULT_PORTAL_BRAND

	try:
		configured_brand = frappe.db.get_single_value("Hotspot Settings", "portal_brand")
		if configured_brand:
			brand = configured_brand.strip() or DEFAULT_PORTAL_BRAND
	except Exception:
		# Keep portal pages renderable even before migrate creates the singleton.
		pass

	return {
		"portal_brand": brand,
		"portal_login_title": f"{brand} Login",
		"portal_status_title": f"Session Status | {brand}",
	}
