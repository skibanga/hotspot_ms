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

> **IMPORTANT: Android HTTPS Captive Portal Bug**
> If you enforce HTTPS (Let's Encrypt) on your Frappe server, Android devices will drop the `clientmac` parameter during the HTTP to HTTPS redirect. To bypass this issue and properly collect MAC addresses for all devices, you must configure OpenNDS using Mode 3 (ThemeSpec). Please follow the instructions in [OPENNDS_ROUTER_SETUP.md](OPENNDS_ROUTER_SETUP.md) for the exact script and configuration details.

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

Router session-restore flow:
- `/api/method/hotspot_ms.api.portal.restore_active_access`

Snippe payments:
- `/api/method/hotspot_ms.api.snippe.get_snippe_settings`
- `/api/method/hotspot_ms.api.snippe.create_snippe_payment`
- `/api/method/hotspot_ms.api.snippe.create_snippe_session`
- `/api/method/hotspot_ms.api.snippe.sync_snippe_payment_status`
- `/api/method/hotspot_ms.api.snippe.snippe_webhook`

Snippe setup:
1. Open `Snippe Settings` (single DocType).
2. Set `enabled=1`, `base_url=https://api.snippe.sh`, API key, and optional webhook secret.
3. Use webhook URL:
   - `https://<your-site>/api/method/hotspot_ms.api.snippe.snippe_webhook`
4. For payment/session create requests, send idempotency key (the API supports it).
5. For `card` payments, include required billing fields: `address`, `city`, `state`, `postcode`, `country`.

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

Session restore worker:

```sh
install -m 0755 /root/openwrt_restore_active_clients.sh /usr/bin/hotspot_restore_active_clients.sh
install -m 0755 /root/openwrt_hotspot_restore.init /etc/init.d/hotspot_restore

cat >/etc/hotspot_restore.conf <<'EOF'
FRAPPE_BASE_URL='https://hotspot.uniquemindpro.xyz'
NAS_IDENTIFIER='OpenWrt-Main'
NAS_SECRET='REPLACE_WITH_NAS_SHARED_SECRET'
POLL_INTERVAL='15'
EOF

/etc/init.d/hotspot_restore enable
/etc/init.d/hotspot_restore start
```

Manual one-shot test:

```sh
FRAPPE_BASE_URL='https://hotspot.uniquemindpro.xyz' \
NAS_IDENTIFIER='OpenWrt-Main' \
NAS_SECRET='<NAS_SHARED_SECRET>' \
/usr/bin/hotspot_restore_active_clients.sh --once
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

## 12) OpenWrt Hardening Bundle

Generate a router-side hardening script from the `Nas Device` form or use the helper script directly.

The generated bundle writes a standalone nftables ruleset to:

```text
/usr/share/nftables.d/table-pre/99-hotspot-hardening.nft
```

It also enables wireless client isolation across all `wifi-iface` sections.

Apply on the router:

```sh
chmod +x /root/openwrt_hotspot_hardening.sh
HOTSPOT_IFACE=br-lan CONN_LIMIT=150 TTL_VALUE=64 \
  /root/openwrt_hotspot_hardening.sh /usr/share/nftables.d/table-pre/99-hotspot-hardening.nft
/etc/init.d/firewall restart
```

## 13) Advanced Anti-Tethering & TTL Blocking

To prevent users from sharing their internet connection via mobile hotspots (Tethering), use the `trian_professional` logic. This drops packets that have been routed once (TTL 63).

### TTL Blocking (Mangle)
Add these rules to your `inet fw4` table to drop tethered traffic:

```sh
# Drop packets coming from LAN with TTL 63 (detected tethering)
nft add rule inet fw4 trian_professional iifname "eth1" ip ttl 63 counter drop
nft add rule inet fw4 trian_professional iifname "eth1" ip6 hoplimit 63 counter drop
```

### Proxy & VPN Port Blocking
Block common ports used by "NetShare" or "PDANet" apps to bypass captive portals:

```sh
# Block common proxy/VPN ports
nft add rule inet fw4 trian_professional tcp dport { 1080, 3128, 7777, 8080, 8243, 10808 } counter drop
nft add rule inet fw4 trian_professional udp dport { 1080, 3128, 7777, 8080, 8243, 10808 } counter drop
```

## 14) Troubleshooting & Verification

### Router Side (OpenWrt)
- **Check active clients**: `ndsctl status | grep "Current clients"`
- **Verify TTL drops**: `nft list chain inet fw4 trian_professional`
- **Monitor NDS logs**: `logread -f | grep -i "nds"`
- **Test server reachability**: `wget -qO- http://hotspot.uniquemindpro.xyz/hotspot/login | head -n 5`
- **ARP check**: `cat /proc/net/arp` (Look for `0x2` flags for truly active devices)

### Frappe Side
- **NAS Matching**: Ensure `Nas Device` name matches the router's `Gateway Name` (e.g., `openNDS Node:00e04c670303`).
- **FAS Key**: Ensure `opennds_fas_key` in Frappe matches `faskey` in `/etc/config/opennds`.

## License

mit
