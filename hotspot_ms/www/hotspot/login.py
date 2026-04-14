import frappe

from hotspot_ms.api.portal import get_opennds_captive_context


def get_context(context):
	context.no_cache = 1
	context.title = "Hotspot Login"
	context.active_page = "login"
	context.current_year = frappe.utils.now_datetime().year
	context.captive = get_opennds_captive_context(frappe.form_dict)
	context.captive_json = frappe.as_json(context.captive or {})
	return context
