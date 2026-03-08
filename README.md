# Hotspot MS

Hotspot billing and captive-portal backend for OpenWrt + openNDS + Frappe.

## Architecture

```text
Clients
  -> AP / Switch
  -> OpenWrt (eth1 LAN, eth0 WAN) + openNDS
  -> Frappe (hotspot portal + voucher/session logic)
  -> Optional router worker pull/ack for deauth actions
```

## 1) Install App

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench install-app hotspot_ms
bench --site <your-site> migrate
```

Seed default plans after migrate (already hooked in `after_migrate`):

```bash
bench --site <your-site> execute hotspot_ms.defaults.after_migrate
```

Default plans inserted:
- `TSh 500 - 6 Hours`
- `TSh 1000 - 24 Hours`
- `TSh 5000 - 7 Days`

## 2) OpenWrt Network Setup (WAN + LAN USB Adapter)

Assumption:
- `eth0` = WAN (to upstream/main router)
- `eth1` = LAN (USB ethernet adapter to AP/switch)

Install USB ethernet kernel modules:

```sh
apk update
apk add kmod-usb-net kmod-usb-net-asix kmod-usb-net-rtl8152 kmod-usb-net-cdc-ether
```

Configure interfaces:

```sh
uci set network.wan=interface
uci set network.wan.device='eth0'
uci set network.wan.proto='dhcp'

uci set network.lan=interface
uci set network.lan.device='eth1'
uci set network.lan.proto='static'
uci set network.lan.ipaddr='192.168.10.1'
uci set network.lan.netmask='255.255.255.0'

uci commit network
/etc/init.d/network restart
```

Enable DHCP on LAN:

```sh
uci set dhcp.lan.interface='lan'
uci set dhcp.lan.start='100'
uci set dhcp.lan.limit='200'
uci set dhcp.lan.leasetime='12h'
uci commit dhcp
/etc/init.d/dnsmasq restart
```

Verify:

```sh
ifstatus wan
ip a
ip route
ping -c 3 8.8.8.8
```

## 3) Install and Configure openNDS

Install openNDS and dependencies:

```sh
apk add opennds ca-bundle ca-certificates php8-cli php8-mod-openssl dnsmasq-full
[ -x /usr/bin/php ] || ln -s /usr/bin/php8 /usr/bin/php
```

Configure FAS (external portal at Frappe):

```sh
uci set opennds.@opennds[0].enabled='1'
uci set opennds.@opennds[0].gatewayinterface='eth1'
uci set opennds.@opennds[0].fasremoteip='157.173.109.148'
uci set opennds.@opennds[0].fasremotefqdn='hotspot.uniquemindpro.xyz'
uci set opennds.@opennds[0].fasport='443'
uci set opennds.@opennds[0].faspath='/hotspot/login'
uci set opennds.@opennds[0].fas_secure_enabled='0'
uci set opennds.@opennds[0].fassecureenabled='0'

uci -q delete opennds.@opennds[0].preauthenticated_users
uci add_list opennds.@opennds[0].preauthenticated_users='allow tcp port 443 to 157.173.109.148'
uci add_list opennds.@opennds[0].preauthenticated_users='allow tcp port 80 to 157.173.109.148'
uci add_list opennds.@opennds[0].preauthenticated_users='allow udp port 53'
uci add_list opennds.@opennds[0].preauthenticated_users='allow tcp port 53'

uci commit opennds
/etc/init.d/opennds enable
/etc/init.d/opennds restart
```

Notes:
- On OpenWrt 25.12 + openNDS 10.3.1, `uci: Invalid argument` can appear on start/restart even when service still works.
- Real success check is:

```sh
pgrep -af opennds
ls -l /tmp/ndsctl.sock
ndsctl status
```

## 4) Link openNDS to Frappe Portal

Test router can reach portal:

```sh
wget -O /tmp/portal.html https://hotspot.uniquemindpro.xyz/hotspot/login
head -n 20 /tmp/portal.html
```

Client test:
1. Connect client to hotspot LAN/Wi-Fi.
2. Open `http://neverssl.com`.
3. You should be redirected to `https://hotspot.uniquemindpro.xyz/hotspot/login?...`.

## 5) Frappe DocTypes Used in This Integration

- `Hotspot Plan`: package definition (price, validity, limits).
- `Hotspot Voucher`: voucher code, status, device lock (`device_mac`), expiry, usage.
- `Hotspot Session`: session lifecycle, IP/MAC, counters, terminate cause.
- `Nas Device`: router identity and shared secret for pull/ack APIs.
- `Voucher Batch`: bulk voucher generation.

Important `Nas Device` example:
- `device_name`: `OpenWrt-Main`
- `ip_address`: `192.168.10.1`
- `nas_type`: `OpenWrt`
- `enabled`: `1`
- `shared_secret`: strong secret used by router workers

## 6) Frappe APIs in Use

Portal flow:
- `/api/method/hotspot_ms.api.portal.get_packages`
- `/api/method/hotspot_ms.api.portal.verify_voucher`
- `/api/method/hotspot_ms.api.portal.activate_voucher`
- `/api/method/hotspot_ms.api.portal.build_opennds_redirect`
- `/api/method/hotspot_ms.api.portal.session_status`
- `/api/method/hotspot_ms.api.portal.logout_session`

Router deauth flow:
- `/api/method/hotspot_ms.api.portal.pull_disconnect_actions`
- `/api/method/hotspot_ms.api.portal.acknowledge_disconnect_action`

## 7) Session Expiry and Deauth Queue

Scheduler task:

```text
hotspot_ms.tasks.close_expired_or_used_sessions
```

Runs every minute (see `hooks.py`) and:
- closes expired/used sessions
- updates voucher status (`Expired` / `Used`)
- marks deauth queue using `terminate_cause` prefix `DEAUTH_PENDING|`

Manual run:

```bash
bench --site hotspot.uniquemindpro.xyz execute hotspot_ms.tasks.close_expired_or_used_sessions
```

## 8) OpenWrt Worker Services (Automation)

Enabled services:

```sh
/etc/init.d/opennds enable
/etc/init.d/hotspot_deauth enable
/etc/init.d/opennds_watchdog enable
```

Check running:

```sh
pgrep -af 'opennds|hotspot_deauth_worker|opennds_watchdog'
```

## 9) Tailwind CSS (Portal UI)

Hotspot portal pages under `hotspot_ms/www/hotspot/` use local compiled Tailwind CSS:

- Source: `hotspot_ms/public/tailwind/hotspot_portal.css`
- Output: `hotspot_ms/public/css/hotspot_portal.css`
- Config: `tailwind.config.js`

Build:

```bash
cd apps/hotspot_ms
npm install
npm run build:css
```

Watch:

```bash
cd apps/hotspot_ms
npm run watch:css
```

## 10) Quick Troubleshooting Commands

OpenWrt:

```sh
/etc/init.d/opennds status
ndsctl status
logread -e opennds | tail -n 80
logread -e hotspot-deauth | tail -n 80
logread -e opennds-watchdog | tail -n 80
```

Frappe:

```bash
bench --site hotspot.uniquemindpro.xyz migrate
bench --site hotspot.uniquemindpro.xyz clear-cache
bench --site hotspot.uniquemindpro.xyz clear-website-cache
bench --site hotspot.uniquemindpro.xyz execute hotspot_ms.tasks.close_expired_or_used_sessions
```

## 11) Integration Test Commands (Frappe <-> OpenWrt)

Trigger close/expire job from Frappe:

```bash
bench --site hotspot.uniquemindpro.xyz execute hotspot_ms.tasks.close_expired_or_used_sessions
```

Pull pending disconnect actions from OpenWrt:

```sh
wget -qO- "https://hotspot.uniquemindpro.xyz/api/method/hotspot_ms.api.portal.pull_disconnect_actions?nas_identifier=OpenWrt-Main&secret=<NAS_SHARED_SECRET>"
```

Manual deauth on router:

```sh
ndsctl deauth <client_ip_or_mac>
```

Ack action to Frappe after successful deauth:

```sh
wget -qO- "https://hotspot.uniquemindpro.xyz/api/method/hotspot_ms.api.portal.acknowledge_disconnect_action?session_id=<SESSION_ID>&nas_identifier=OpenWrt-Main&secret=<NAS_SHARED_SECRET>&result=ok&note=manual_deauth"
```

Expected success path:
1. `pull_disconnect_actions` returns one or more actions.
2. Router deauth succeeds (`deauth_ok` or `already_offline`).
3. Acknowledge call succeeds.
4. Next `pull_disconnect_actions` returns `actions: []`.

## License

mit
