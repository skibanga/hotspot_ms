import frappe
import json
import paramiko

def execute():
    """
    Scheduled task that connects to each enabled OpenWrt NAS Device
    over WireGuard and fetches the real-time openNDS client json.
    """
    routers = frappe.get_all("Nas Device", filters={"enabled": 1, "nas_type": "OpenWrt"}, fields=["name", "vpn_ip_address", "ip_address"])
    
    for router in routers:
        if not router.vpn_ip_address:
            continue
            
        try:
            # 1. SSH into the router
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            # Note: For production, use SSH Keys instead of password, or fetch a secure password from a secret manager.
            # Here we assume passwordless SSH keys are set up between Frappe and the router.
            ssh.connect(hostname=router.vpn_ip_address, username='root', timeout=5)
            
            # 2. Run ndsctl json
            stdin, stdout, stderr = ssh.exec_command('ndsctl json')
            output = stdout.read().decode('utf-8')
            ssh.close()
            
            # 3. Parse JSON
            nds_data = json.loads(output)
            clients = nds_data.get('clients', {})
            
            # Clear old active clients for this router
            frappe.db.delete("Hotspot Active Client", {"nas_device": router.name})
            
            # 4. Insert real-time active clients and update Sessions
            for mac, data in clients.items():
                if data.get('state') == 'Authenticated':
                    # Create active client record
                    frappe.get_doc({
                        "doctype": "Hotspot Active Client",
                        "mac_address": mac,
                        "ip_address": data.get('ip'),
                        "nas_device": router.name,
                        "download_bytes": data.get('downloaded'),
                        "upload_bytes": data.get('uploaded'),
                        "connected_since": frappe.utils.now()
                    }).insert(ignore_permissions=True)
                    
                    # Optional: Sync usage back to the open Hotspot Session based on MAC
                    session = frappe.get_all("Hotspot Session", filters={"device_mac": mac, "status": "Open"}, limit=1)
                    if session:
                        frappe.db.set_value("Hotspot Session", session[0].name, {
                            "download_bytes": data.get('downloaded'),
                            "upload_bytes": data.get('uploaded')
                        })
                        
            # Mark router as Online
            frappe.db.set_value("Nas Device", router.name, {"status": "Online", "last_heartbeat": frappe.utils.now()})
            frappe.db.commit()
            
        except Exception as e:
            frappe.log_error(title=f"Failed to sync router {router.name}", message=str(e))
            frappe.db.set_value("Nas Device", router.name, {"status": "Offline", "last_heartbeat": frappe.utils.now()})
            frappe.db.commit()
