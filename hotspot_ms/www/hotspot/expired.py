import frappe

from hotspot_ms.branding import get_portal_branding


def get_context(context):
	lang = frappe.request.cookies.get("lang") or "sw"
	frappe.local.lang = lang
	context.lang = lang

	context.no_cache = 1
	context.update(get_portal_branding())
	context.title = f"Session Ended | {context.portal_brand}"
	context.active_page = "expired"
	context.current_year = frappe.utils.now_datetime().year
	return context
