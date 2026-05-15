import frappe

from hotspot_ms.branding import get_portal_branding


def get_context(context):
	lang = frappe.request.cookies.get("lang") or "sw"
	frappe.local.lang = lang

	context.no_cache = 1
	context.active_page = "status"
	context.current_year = frappe.utils.now_datetime().year
	context.update(get_portal_branding())
	context.title = context.portal_status_title
	return context
