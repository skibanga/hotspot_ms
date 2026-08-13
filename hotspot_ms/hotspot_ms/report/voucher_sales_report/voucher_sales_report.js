frappe.query_reports["Voucher Sales Report"] = {
	filters: [
		{
			fieldname: "quick_range",
			label: __("Quick Range"),
			fieldtype: "Select",
			options: [
				"",
				"Today",
				"Last 24 Hours",
				"This Week",
				"This Month",
				"This Year",
			].join("\n"),
			default: "",
			on_change: function (report) {
				const range = report.get_filter_value("quick_range");
				const today = frappe.datetime.get_today();
				let from_date = frappe.datetime.month_start();
				let to_date = today;

				if (!range || range === "This Month") {
					from_date = frappe.datetime.month_start();
					to_date = today;
				} else if (range === "Today") {
					from_date = today;
					to_date = today;
				} else if (range === "Last 24 Hours") {
					from_date = frappe.datetime.add_days(today, -1);
					to_date = today;
				} else if (range === "This Week") {
					// week starts Monday
					const now = new Date();
					const day = now.getDay(); // 0=Sun, 1=Mon ...
					const diff = day === 0 ? 6 : day - 1; // days since Monday
					const monday = new Date(now);
					monday.setDate(now.getDate() - diff);
					from_date = frappe.datetime.obj_to_str(monday);
					to_date = today;
				} else if (range === "This Month") {
					from_date = frappe.datetime.month_start();
					to_date = today;
				} else if (range === "This Year") {
					const year = new Date().getFullYear();
					from_date = `${year}-01-01`;
					to_date = today;
				}

				report.set_filter_value("from_date", from_date);
				report.set_filter_value("to_date", to_date);
			},
		},
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
			fieldname: "nas_device",
			label: __("NAS Device"),
			fieldtype: "Link",
			options: "Nas Device",
		},
		{
			fieldname: "include_complimentary",
			label: __("Include Complimentary"),
			fieldtype: "Check",
			default: 0,
		},
	],
};
