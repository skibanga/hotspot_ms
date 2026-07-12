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

		frm.add_custom_button(__("Generate Hardening Bundle"), async () => {
			if (frm.is_dirty()) {
				frappe.msgprint(__("Please save the document before generating the script."));
				return;
			}

			const result = await frappe.call({
				method: "hotspot_ms.hotspot_ms.doctype.nas_device.nas_device.generate_openwrt_hardening_bundle",
				args: {
					name: frm.doc.name,
					hotspot_iface: frm.doc.hotspot_iface || "br-lan",
					conn_limit: 150,
					ttl_value: 64,
				},
			});

			const bundle = result.message && result.message.bundle;
			if (!bundle) {
				frappe.msgprint(__("Could not generate hardening bundle."));
				return;
			}

			const dialog = new frappe.ui.Dialog({
				title: __("OpenWrt Hardening Bundle"),
				fields: [
					{
						fieldname: "bundle",
						fieldtype: "Code",
						label: __("Bundle"),
						options: "Shell",
						read_only: 1,
						default: bundle,
					},
				],
				size: "extra-large",
				primary_action_label: __("Copy"),
				primary_action() {
					frappe.utils.copy_to_clipboard(bundle);
					dialog.hide();
					frappe.show_alert({ message: __("Bundle copied to clipboard"), indicator: "green" });
				},
			});

			dialog.show();
		});
		frm.add_custom_button(__("Generate Provisioning Script"), async () => {
			if (frm.is_dirty()) {
				frappe.msgprint(__("Please save the document before generating the script."));
				return;
			}
			if (!frm.doc.opennds_fas_key) {
				frappe.msgprint(__("Please generate the FAS Key first."));
				return;
			}

			const result = await frappe.call({
				method: "hotspot_ms.hotspot_ms.doctype.nas_device.nas_device.generate_openwrt_provisioning_script",
				args: {
					name: frm.doc.name
				},
			});

			const script = result.message && result.message.script;
			if (!script) {
				frappe.msgprint(__("Could not generate provisioning script."));
				return;
			}

			const dialog = new frappe.ui.Dialog({
				title: __("OpenWrt Provisioning Script"),
				fields: [
					{
						fieldname: "script",
						fieldtype: "Code",
						label: __("Bash Script"),
						options: "Shell",
						read_only: 1,
						default: script,
					},
				],
				size: "extra-large",
				primary_action_label: __("Copy"),
				primary_action() {
					frappe.utils.copy_to_clipboard(script);
					dialog.hide();
					frappe.show_alert({ message: __("Script copied to clipboard"), indicator: "green" });
				},
			});

			dialog.show();
		});
	},
});
