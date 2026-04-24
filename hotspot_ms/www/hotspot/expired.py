import frappe

from hotspot_ms.branding import get_portal_branding


def get_context(context):
	context.no_cache = 1
	context.update(get_portal_branding())
	context.title = f"Session Ended | {context.portal_brand}"
	context.active_page = "expired"
	context.current_year = frappe.utils.now_datetime().year
	return context
