frappe.query_reports["Voucher Sales Report"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.month_start(),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "plan",
			label: __("Plan"),
			fieldtype: "Link",
			options: "Hotspot Plan",
		},
		{
			fieldname: "include_complimentary",
			label: __("Include Complimentary"),
			fieldtype: "Check",
			default: 0,
		},
	],
};
