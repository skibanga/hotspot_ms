import frappe

from hotspot_ms.api.portal import get_opennds_captive_context
from hotspot_ms.branding import get_portal_branding


def get_context(context):
	lang = frappe.request.cookies.get("lang") or "sw"
	frappe.local.lang = lang
	context.lang = lang

	context.no_cache = 1
	context.active_page = "login"
	context.current_year = frappe.utils.now_datetime().year
	context.captive = get_opennds_captive_context(frappe.form_dict)
	context.captive_json = frappe.as_json(context.captive or {})
	context.update(get_portal_branding())
	context.title = context.portal_login_title
	return context
