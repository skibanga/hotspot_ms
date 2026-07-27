# OpenNDS Direct Remote FAS Integration Guide

## Direct Remote FAS Architecture

OpenNDS (Forwarding Authentication Service) allows OpenWrt routers to redirect unauthenticated Wi-Fi / LAN clients directly to your secure cloud-hosted Frappe portal (`https://your-domain.com/hotspot/login`).

```text
Clients (Wi-Fi / LAN)
   ├──> OpenWrt (openNDS listening on LAN port)
   └──> Direct FAS HTTP Redirect (fasport 80) ──> Nginx SSL (443) ──> Frappe Hotspot Portal
```

---

## 1. How Direct FAS Port 80 Works

1. OpenNDS redirects unauthenticated users to `http://your-domain.com:80/hotspot/login?fas=...`.
2. Server-side Nginx listening on port 80 accepts the request and returns an HTTP `301/307 Redirect` upgrading it to `https://your-domain.com/hotspot/login?fas=...`.
3. The client's browser follows the redirect to `https://` and loads the Frappe portal seamlessly without needing local theme scripts on the router.

> [!NOTE]
> Setting `fasport '80'` avoids Nginx's `400 Bad Request: Plain HTTP request sent to HTTPS port` error that occurs when openNDS attempts to send unencrypted HTTP payloads directly to port 443.

---

## 2. OpenWrt UCI Configuration (`/etc/config/opennds`)

```uci
config opennds
	option enabled '1'
	option gatewayinterface 'br-lan'
	option gatewayname 'OpenWrt-Branch-1'
	option gatewayport '2050'

	# Direct Remote FAS Settings
	option fasremoteip '157.173.109.148'
	option fasremotefqdn 'your-domain.com'
	option fasport '80'
	option faspath '/hotspot/login'
	option fassecureenabled '1'
	option faskey 'YOUR_GENERATED_FAS_KEY'

	# Whitelist DNS and Cloud Portal IP
	list preauthenticated_users 'allow udp port 53'
	list preauthenticated_users 'allow tcp port 53'
	list preauthenticated_users 'allow tcp port 443 to 157.173.109.148'
	list preauthenticated_users 'allow tcp port 80 to 157.173.109.148'
```

---

## 3. Automated Provisioning

You can automatically generate and deploy this configuration to any OpenWrt router by clicking **Generate Provisioning Script** on the **Nas Device** record in Frappe Desk!
