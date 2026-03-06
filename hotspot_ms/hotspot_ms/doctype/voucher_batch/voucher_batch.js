// Copyright (c) 2026, Sydney Kibanga and contributors
// For license information, please see license.txt

frappe.ui.form.on("Voucher Batch", {
	refresh(frm) {
		if (!frm.is_new() && frm.doc.quantity > (frm.doc.generated_count || 0)) {
			frm.add_custom_button(__("Generate Vouchers"), () => {
				frappe.call({
					method: "hotspot_ms.hotspot_ms.doctype.voucher_batch.voucher_batch.generate_vouchers_for_batch",
					args: { batch: frm.doc.name },
					callback(r) {
						if (!r.exc && r.message?.ok) {
							frappe.show_alert({
								message: __("Generated {0} vouchers", [r.message.created]),
								indicator: "green",
							});
							frm.reload_doc();
						}
					},
				});
			});
		}
	},
});
