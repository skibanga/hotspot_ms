import frappe


@frappe.whitelist()
def get_dashboard_data():
    routers = frappe.get_all(
        "Nas Device",
        filters={"enabled": 1},
        fields=["name", "device_name", "vpn_ip_address", "status", "last_heartbeat"],
    )
    aps = frappe.get_all(
        "Access Point",
        fields=["name", "ap_name", "lan_ip", "status", "last_ping", "nas_device"],
    )
    active_clients = frappe.get_all(
        "Hotspot Active Client",
        fields=[
            "name",
            "mac_address",
            "ip_address",
            "nas_device",
            "download_bytes",
            "upload_bytes",
            "connected_since",
        ],
    )
    for client in active_clients:
        voucher = frappe.db.get_value(
            "Hotspot Voucher",
            {"device_mac": client.mac_address, "status": "Active"},
            ["name", "status"],
            as_dict=True,
        )

        if voucher:
            client.voucher_code = voucher.name
            client.voucher_status = voucher.status
        else:
            client.voucher_code = "None"
            client.voucher_status = "Null"

    return {"routers": routers, "aps": aps, "active_clients": active_clients}


@frappe.whitelist()
def kick_client(mac_address, nas_device_name):
    router = frappe.get_doc("Nas Device", nas_device_name)
    if not router.vpn_ip_address:
        frappe.throw("Router does not have a VPN IP Address configured.")

    try:
        import paramiko

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(hostname=router.vpn_ip_address, username="root", timeout=5)
        stdin, stdout, stderr = ssh.exec_command(f"ndsctl deauth {mac_address}")
        output = stdout.read().decode("utf-8")
        ssh.close()

        # Remove from active clients immediately for fast UI feedback
        frappe.db.delete("Hotspot Active Client", {"mac_address": mac_address})
        frappe.db.commit()
        return {
            "status": "success",
            "message": f"User {mac_address} kicked successfully.",
        }
    except Exception as e:
        frappe.log_error(title="Failed to kick client", message=str(e))
        frappe.throw(f"Failed to connect to router: {str(e)}")


@frappe.whitelist()
def run_speedtest(nas_device_name):
    router = frappe.get_doc("Nas Device", nas_device_name)
    if not router.vpn_ip_address:
        frappe.throw("Router does not have a VPN IP Address configured.")

    try:
        import paramiko
        import json
        import re

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(hostname=router.vpn_ip_address, username="root", timeout=10)

        # Phase 1: Smart MWAN Check
        stdin, stdout, stderr = ssh.exec_command("mwan3 status")
        mwan_out = stdout.read().decode("utf-8")
        mwan_err = stderr.read().decode("utf-8")

        results = []

        if "not found" in mwan_out or "not found" in mwan_err or not mwan_out.strip():
            # Fallback: Single ISP Router
            stdin, stdout, stderr = ssh.exec_command("/usr/bin/speedtest-go --json")
            output = stdout.read().decode("utf-8")
            try:
                data = json.loads(output)
                server = data.get("servers", [{}])[0]
                user_info = data.get("user_info", {})
                results.append(
                    {
                        "interface": "wan",
                        "status": "Online",
                        "isp": user_info.get("Isp", "Unknown ISP"),
                        "ping": round(server.get("latency", 0) / 1000000, 1),
                        "download_mbps": round(server.get("dl_speed", 0) / 125000, 1),
                        "upload_mbps": round(server.get("ul_speed", 0) / 125000, 1),
                    }
                )
            except Exception as e:
                frappe.log_error(
                    title="Speedtest Parse Error", message=f"{str(e)}\nOutput: {output}"
                )
                frappe.throw(f"Failed to parse speedtest output. Error: {str(e)}")
        else:
            # Smart MWAN Multi-ISP Mode
            import re
            ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
            mwan_clean = ansi_escape.sub('', mwan_out)
            
            lines = mwan_clean.splitlines()
            for line in lines:
                match = re.search(r"interface (\S+) is (online|offline)", line)
                if match:
                    iface = match.group(1)
                    status = match.group(2)

                    if iface.endswith("6"):
                        continue  # Skip IPv6 duplicate interfaces

                    if status == "offline":
                        results.append(
                            {
                                "interface": iface,
                                "status": "Offline",
                                "isp": "Disconnected / Down",
                                "ping": 0,
                                "download_mbps": 0,
                                "upload_mbps": 0,
                            }
                        )
                    elif status == "online":
                        # Phase 2: IP Resolution
                        stdin, stdout, stderr = ssh.exec_command(f"ifstatus {iface}")
                        ifstatus_out = stdout.read().decode("utf-8")
                        try:
                            ifstatus_json = json.loads(ifstatus_out)
                            ip = None
                            if (
                                "ipv4-address" in ifstatus_json
                                and len(ifstatus_json["ipv4-address"]) > 0
                            ):
                                ip = ifstatus_json["ipv4-address"][0].get("address")

                            if ip:
                                # Phase 3: Targeted Speedtest Execution
                                stdin, stdout, stderr = ssh.exec_command(
                                    f"/usr/bin/speedtest-go --json --source={ip}"
                                )
                                st_output = stdout.read().decode("utf-8")
                                try:
                                    st_data = json.loads(st_output)
                                    server = st_data.get("servers", [{}])[0]
                                    user_info = st_data.get("user_info", {})
                                    results.append(
                                        {
                                            "interface": iface,
                                            "status": "Online",
                                            "isp": user_info.get("Isp", "Unknown ISP"),
                                            "ping": round(
                                                server.get("latency", 0) / 1000000, 1
                                            ),
                                            "download_mbps": round(
                                                server.get("dl_speed", 0) / 125000, 1
                                            ),
                                            "upload_mbps": round(
                                                server.get("ul_speed", 0) / 125000, 1
                                            ),
                                        }
                                    )
                                except Exception as st_err:
                                    results.append(
                                        {
                                            "interface": iface,
                                            "status": "Error",
                                            "isp": f"Speedtest Failed: {str(st_err)}",
                                            "ping": 0,
                                            "download_mbps": 0,
                                            "upload_mbps": 0,
                                        }
                                    )
                            else:
                                results.append(
                                    {
                                        "interface": iface,
                                        "status": "Error",
                                        "isp": f"No IPv4 Address Found",
                                        "ping": 0,
                                        "download_mbps": 0,
                                        "upload_mbps": 0,
                                    }
                                )
                        except Exception as e:
                            results.append(
                                {
                                    "interface": iface,
                                    "status": "Error",
                                    "isp": f"ifstatus Parse Error: {str(e)}",
                                    "ping": 0,
                                    "download_mbps": 0,
                                    "upload_mbps": 0,
                                }
                            )

        ssh.close()
        return {"status": "success", "results": results}

    except Exception as e:
        frappe.log_error(title="Failed to run speedtest", message=str(e))
        frappe.throw(f"Speedtest failed: {str(e)}")
