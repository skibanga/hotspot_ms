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

## 2) Hardware Setup (USB Adapters)

If you are using a standard OpenWrt router, you can skip this step. 
If you are using a custom device with a USB ethernet adapter (like a Mini-PC), ensure your interfaces are assigned correctly (e.g., WAN to `eth0` and LAN to `eth1`) before provisioning:
```sh
uci set network.lan.device='eth1'
uci commit network
/etc/init.d/network restart
```

## 3) OpenWrt Automated Provisioning

The manual installation steps for OpenNDS and background worker scripts have been completely replaced by an automated installer!

Please refer to **Section 8) OpenWrt Automated Provisioning & Worker Services** below for the One-Liner Bootstrapper command that sets up everything instantly.

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

## 8) OpenWrt Automated Provisioning & Worker Services

Instead of manually installing dependencies, configuring OpenNDS, and writing worker scripts, the entire process is now fully automated using a **One-Liner Bootstrapper**.

To provision a new router:
1. Create a new `Nas Device` record in ERPNext.
2. Enter the router's details (Name, default IP `192.168.10.254`, and a strong `Shared Secret`).
3. Click the **Generate FAS Key** button to create a secure token for OpenNDS.
4. Save the document.
5. Click **Generate Provisioning Script**.

ERPNext will generate a single command:
```bash
wget --no-check-certificate -qO- "https://<your-site>/api/method/hotspot_ms.hotspot_ms.doctype.nas_device.nas_device.download_provisioning_script?name=<Nas_Name>&secret=<Secret>" | sh
```

Paste this command into your OpenWrt SSH terminal. It will automatically:
- Install required USB network drivers
- Configure your LAN IP address
- Setup and configure OpenNDS (FAS settings, whitelist ports)
- Install custom worker scripts (`hotspot_restore_active_clients.sh`, `hotspot_deauth_worker.sh`, `hotspot_sync_session_usage.sh`)
- Schedule them to run in the background
- Restart all necessary services

Verify that the background workers are running:
```sh
pgrep -af 'hotspot'
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
