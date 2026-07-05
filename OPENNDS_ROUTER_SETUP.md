# OpenNDS Android Captive Portal HSTS Workaround

## The Problem
When deploying a Captive Portal with a securely encrypted (HTTPS) backend server (like Frappe with Let's Encrypt), mobile devices running Android frequently fail to authenticate users due to missing `clientmac` and `clientip` parameters. 

This occurs because of a built-in privacy protection mechanism in modern Android's Captive Portal Login browser (WebView).

### The "HTTPS Redirect Stripping" Bug
1. Standard OpenNDS Forwarding Authentication Service (FAS) generates an unencrypted `http://` link containing the user's MAC address (e.g., `http://hotspot.domain.com/login?fas=...`).
2. When the Android device connects, the OpenNDS router redirects it to this `http://` URL.
3. The backend server's Nginx configuration (which is enforcing HTTPS) instantly intercepts the request and responds with an HTTP `301/307 Redirect` to upgrade the connection to `https://`.
4. **The Bug:** When the Android Captive Portal browser follows this HTTP-to-HTTPS redirect, it intentionally deletes all URL query strings as a privacy measure to prevent tracking. 
5. The Frappe backend receives the HTTPS request, but the MAC address and IP are gone, causing authentication to fail.

*Note: OpenNDS itself cannot natively generate an `https://` link without crashing due to a bug in version 10 where it attempts to send unencrypted HTTP traffic to port 443, resulting in a `400 Bad Request` from Nginx.*

## The Solution (OpenNDS Mode 3 ThemeSpec)
To bypass both the Android privacy bug and the OpenNDS HTTPS bug, we utilize a custom "local theme" script on the OpenWrt router.

Instead of instructing OpenNDS to use FAS to redirect the user to the server directly, we configure OpenNDS to load a local script (`theme_click-to-continue.sh`). This script generates a tiny HTML page directly on the router.

### How it works:
1. OpenNDS redirects the unauthenticated user to the router's local web server (`http://status.client:2050`).
2. The router executes the custom `/usr/lib/opennds/theme_click-to-continue.sh` script.
3. The script injects the user's `$clientmac` and `$clientip` into a snippet of Javascript inside an HTML page.
4. The HTML page is sent to the Android phone.
5. The Android phone executes the Javascript: `window.location.replace("https://your-domain.com/hotspot/login?clientmac=...&clientip=...");`.
6. Because the redirection is performed by **Javascript** (client-side) rather than an HTTP 301 Header (server-side), Android treats it as standard web navigation and preserves the MAC address query strings perfectly.

## Configuration Details for OpenWrt Router

### 1. Create the Theme Script
SSH into your OpenWrt router and create/edit the following file:
**File:** `/usr/lib/opennds/theme_click-to-continue.sh`

**Script Contents:**
```bash
#!/bin/sh
title="theme_click-to-continue"
generate_splash_sequence() {
	echo "<!DOCTYPE html>
		<html>
		<head>
		<meta charset=\"utf-8\">
		<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">
		<title>Redirecting...</title>
		<script>
			// Replace 'hotspot.uniquemindpro.xyz' with your actual Frappe domain!
			var redirUrl = \"https://hotspot.uniquemindpro.xyz/hotspot/login?clientmac=${clientmac}&clientip=${clientip}&tok=${tok}&redir=\" + encodeURIComponent(\"${redir}\");
			window.location.replace(redirUrl);
		</script>
		</head>
		<body style=\"background-color:#101622; color:white; font-family:sans-serif; text-align:center; padding-top:50px;\">
		<p>Redirecting to secure login portal...</p>
		</body>
		</html>
	"
}
```

Make it executable:
```bash
chmod +x /usr/lib/opennds/theme_click-to-continue.sh
```

### 2. Patch OpenNDS Engine (if using OpenNDS 10.3)
Due to a configuration bug in some OpenNDS builds, you must hardcode the script path into the engine to ensure it runs properly.

Run this command on the router to patch `libopennds.sh`:
```bash
sed -i 's/themespecpath="$4"/themespecpath="\/usr\/lib\/opennds\/theme_click-to-continue.sh"/g' /usr/lib/opennds/libopennds.sh
```

### 3. Update UCI Configuration
Run these commands to remove standard FAS configurations and enable Mode 3:
```bash
# Delete standard FAS configuration
uci delete opennds.@opennds[0].faskey
uci delete opennds.@opennds[0].fasremotefqdn
uci delete opennds.@opennds[0].fasport
uci delete opennds.@opennds[0].faspath
uci delete opennds.@opennds[0].fassecureenabled
uci delete opennds.@opennds[0].fasremoteip

# Set Mode 3 (ThemeSpec) and theme path
uci set opennds.@opennds[0].login_option_enabled='3'
uci set opennds.@opennds[0].theme_spec_path='/usr/lib/opennds/theme_click-to-continue.sh'
uci commit opennds

# Restart OpenNDS to apply
/etc/init.d/opennds restart
```
