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

## 2) Getting Started: Provisioning a Router

To connect a new OpenWrt router to your Hotspot MS backend, you must first have OpenWrt installed, register the router in ERPNext, and then deploy the automated bootstrapper.

**Step 0: Install OpenWrt (For Custom Mini-PCs)**
If you are building your own router using an x86/64 Mini-PC instead of an off-the-shelf router:
1. Download the firmware from the [OpenWrt 25.12.4 x86/64 Archive](https://archive.openwrt.org/releases/25.12.4/targets/x86/64/).
2. We highly recommend downloading the `generic-squashfs-combined-efi.img.gz` image. This supports modern UEFI booting and allows for easy factory resets via the web interface.
3. Flash the extracted `.img` file to your Mini-PC's internal drive or bootable USB using a tool like [BalenaEtcher](https://etcher.balena.io/) or Rufus.

**Step 1: Register the NAS Device**
1. Log into your ERPNext desk and search for **Nas Device**.
2. Click **Add Nas Device**.
3. Fill in the required fields:
   - **Short Name / Device Name**: Give it a recognizable name (e.g., `OpenWrt-Branch-1`).
   - **IP Address**: Leave the default `192.168.10.254` (or enter your router's specific LAN IP).
   - **NAS Type**: Select `OpenWrt`.
   - **Shared Secret**: Enter a strong, random password (this secures the API calls between the router and the cloud).
4. Save the document.
5. Click the **Generate FAS Key** button. This creates the cryptographic token used by OpenNDS to authenticate users.

**Step 2: Deploy to the Router**
1. On the saved `Nas Device` record, click the **Generate Provisioning Script** button.
2. A custom One-Liner Bootstrapper command will appear. It looks like this:

```bash
wget --no-check-certificate -qO- "https://<your-site>/api/method/hotspot_ms...download_provisioning_script?name=<Nas_Name>&secret=<Secret>" | sh
```

3. Connect to your OpenWrt router via SSH (e.g., `ssh root@192.168.1.1`).
4. Paste the command and hit Enter.

The bootstrapper will automatically:
- Install all required USB network drivers
- Configure your LAN IP address
- Setup and configure OpenNDS (FAS settings, whitelist ports)
- Install custom worker scripts (`hotspot_restore_active_clients`, `hotspot_deauth_worker`, `hotspot_sync_session_usage`)
- Apply **Advanced Anti-Tethering** and **Proxy Blocking** firewall rules
- Restart all necessary services

Your router is now fully provisioned and ready to serve the captive portal!

> **Hardware Note:** If you are using a custom device with a USB ethernet adapter (like a Mini-PC), ensure your interfaces are assigned correctly (e.g., WAN to `eth0` and LAN to `eth1`) before running the provisioning script:
> ```sh
> uci set network.lan.device='eth1'
> uci commit network
> /etc/init.d/network restart
> ```

## 3) Frappe DocTypes Used in This Integration

- `Hotspot Plan`: package definition (price, validity, limits).
- `Hotspot Voucher`: voucher code, status, device lock (`device_mac`), expiry, usage.
- `Hotspot Session`: session lifecycle, IP/MAC, counters, terminate cause.
- `Nas Device`: router identity and shared secret for pull/ack APIs.
- `Voucher Batch`: bulk voucher generation.

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
