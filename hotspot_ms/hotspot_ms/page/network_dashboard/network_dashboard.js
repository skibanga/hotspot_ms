frappe.pages['network-dashboard'].on_page_load = function(wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Network Dashboard',
		single_column: true
	});
}