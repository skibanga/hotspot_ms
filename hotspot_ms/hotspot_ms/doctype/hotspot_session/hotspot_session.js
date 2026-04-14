// Copyright (c) 2026, Sydney Kibanga and contributors
// For license information, please see license.txt

frappe.ui.form.on("Hotspot Session", {
	refresh(frm) {
		if (frm.is_new()) return;

		if (frm.doc.session_status === "Open") {
			frm.add_custom_button(__("Deauth Client"), () => {
				frappe.confirm(
					__("Queue this session for router-side deauthentication?"),
					() => {
						frappe.call({
							method: "hotspot_ms.api.portal.request_session_deauth",
							args: {
								session_id: frm.doc.session_id,
								reason: __("Admin requested disconnect"),
							},
							freeze: true,
							freeze_message: __("Queuing deauth..."),
							callback: (r) => {
								const message = r.message || {};
								if (!message.ok) {
									frappe.msgprint(message.message || __("Failed to queue deauth."));
									return;
								}
								frappe.show_alert({
									message: __("Deauth queued for {0}", [frm.doc.session_id]),
									indicator: "green",
								});
								frm.reload_doc();
							},
						});
					}
				);
			});
		}
	},
});
