import frappe

@frappe.whitelist()
def get_dashboard_data():
    routers = frappe.get_all("Nas Device", filters={"enabled": 1}, fields=["name", "device_name", "vpn_ip_address", "status", "last_heartbeat"])
    aps = frappe.get_all("Access Point", fields=["name", "ap_name", "lan_ip", "status", "last_ping", "nas_device"])
    active_clients = frappe.get_all("Hotspot Active Client", fields=["name", "mac_address", "ip_address", "nas_device", "download_bytes", "upload_bytes", "connected_since"])
    for client in active_clients:
        voucher = frappe.db.get_value("Hotspot Voucher", 
            {"device_mac": client.mac_address, "status": "Active"}, 
            ["name", "status"], as_dict=True)
        
        if voucher:
            client.voucher_code = voucher.name
            client.voucher_status = voucher.status
        else:
            client.voucher_code = "None"
            client.voucher_status = "Null"
            
    return {
        "routers": routers,
        "aps": aps,
        "active_clients": active_clients
    }

@frappe.whitelist()
def kick_client(mac_address, nas_device_name):
    router = frappe.get_doc("Nas Device", nas_device_name)
    if not router.vpn_ip_address:
        frappe.throw("Router does not have a VPN IP Address configured.")
        
    try:
        import paramiko
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(hostname=router.vpn_ip_address, username='root', timeout=5)
        stdin, stdout, stderr = ssh.exec_command(f'ndsctl deauth {mac_address}')
        output = stdout.read().decode('utf-8')
        ssh.close()
        
        # Remove from active clients immediately for fast UI feedback
        frappe.db.delete("Hotspot Active Client", {"mac_address": mac_address})
        frappe.db.commit()
        return {"status": "success", "message": f"User {mac_address} kicked successfully."}
    except Exception as e:
        frappe.log_error(title="Failed to kick client", message=str(e))
        frappe.throw(f"Failed to connect to router: {str(e)}")

@frappe.whitelist()
def run_speedtest(nas_device_name, source_ip=None):
    router = frappe.get_doc("Nas Device", nas_device_name)
    if not router.vpn_ip_address:
        frappe.throw("Router does not have a VPN IP Address configured.")
        
    try:
        import paramiko
        import json
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(hostname=router.vpn_ip_address, username='root', timeout=10)
        
        cmd = "/usr/bin/speedtest-go --json"
        if source_ip:
            cmd += f" --source={source_ip}"
            
        stdin, stdout, stderr = ssh.exec_command(cmd)
        output = stdout.read().decode('utf-8')
        ssh.close()
        
        try:
            data = json.loads(output)
            # speedtest-go outputs in bytes per second. Divide by 125000 to get Mbps.
            return {
                "status": "success",
                "ping": round(data.get("ping", 0), 2),
                "download_mbps": round(data.get("download", 0) / 125000, 2),
                "upload_mbps": round(data.get("upload", 0) / 125000, 2),
                "isp": data.get("client", {}).get("isp", "Unknown ISP")
            }
        except json.JSONDecodeError:
            frappe.throw(f"Failed to parse speedtest output: {output}")
            
    except Exception as e:
        frappe.log_error(title="Failed to run speedtest", message=str(e))
        frappe.throw(f"Speedtest failed: {str(e)}")
