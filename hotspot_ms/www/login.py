import frappe


def get_context(context):
	context.no_cache = 1
	context.title = "Login Redirect"
	context.current_year = frappe.utils.now_datetime().year
	return context
