frappe.listview_settings["Nas Device"] = {
	get_indicator: function (doc) {
		if (doc.status === "Online") {
			return [__("Online"), "green", "status,=,Online"];
		} else if (doc.status === "Offline") {
			return [__("Offline"), "red", "status,=,Offline"];
		} else if (doc.status === "Degraded") {
			return [__("Degraded"), "orange", "status,=,Degraded"];
		}
		return [__("Offline"), "red", "status,=,Offline"];
	},
	formatters: {
		nas_type: function (val) {
			if (!val) return "";
			let color_map = {
				OpenWrt: "purple",
				MikroTik: "orange",
				CoovaChilli: "blue",
				Other: "gray",
			};
			let color = color_map[val] || "gray";
			return `<span class="indicator-pill ${color} font-weight-bold" style="text-transform: none;">${val}</span>`;
		},
	},
};
