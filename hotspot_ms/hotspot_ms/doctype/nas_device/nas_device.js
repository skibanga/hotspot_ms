// Copyright (c) 2026, Sydney Kibanga and contributors
// For license information, please see license.txt

frappe.ui.form.on("Nas Device", {
	refresh(frm) {
		if (frm.is_new()) return;

		frm.add_custom_button(__("Generate FAS Key"), async () => {
			const result = await frappe.call({
				method: "hotspot_ms.api.portal.generate_opennds_fas_key",
				args: { name: frm.doc.name },
			});

			const key = result.message && result.message.opennds_fas_key;
			if (!key) {
				frappe.msgprint(__("Could not generate FAS key."));
				return;
			}

			await frm.reload_doc();
			frappe.msgprint({
				title: __("FAS Key Generated"),
				indicator: "green",
				message: __("The openNDS FAS key has been generated and saved on this NAS Device."),
			});
		});
	},
});
