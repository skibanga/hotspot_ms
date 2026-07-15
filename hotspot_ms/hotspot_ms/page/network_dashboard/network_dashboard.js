frappe.pages['network-dashboard'].on_page_load = function(wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Network Dashboard',
		single_column: true
	});

    // Add Tailwind via CDN for this page specifically to ensure premium styling
    if (!document.getElementById('tailwind-cdn')) {
        let script = document.createElement('script');
        script.id = 'tailwind-cdn';
        script.src = 'https://cdn.tailwindcss.com';
        document.head.appendChild(script);
    }

    $(wrapper).find('.layout-main-section').append(`
        <div id="noc-dashboard-app" class="p-4" style="background-color: #0f172a; min-height: 80vh; border-radius: 8px;">
            <div v-if="loading" class="flex justify-center items-center h-64 text-white">
                <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-white"></div>
            </div>
            
            <div v-else>
                <!-- KPI Cards -->
                <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8 mt-2">
                    <div class="bg-slate-800 rounded-lg p-6 shadow-lg border border-slate-700">
                        <h3 class="text-slate-400 text-sm font-semibold uppercase tracking-wider mb-2">Routers Online</h3>
                        <div class="flex items-center">
                            <span class="text-3xl font-bold text-white mr-3">{{ routers.filter(r => r.status === 'Online').length }}</span>
                            <span class="text-slate-500 text-sm">/ {{ routers.length }} Total</span>
                        </div>
                    </div>
                    <div class="bg-slate-800 rounded-lg p-6 shadow-lg border border-slate-700">
                        <h3 class="text-slate-400 text-sm font-semibold uppercase tracking-wider mb-2">Access Points Online</h3>
                        <div class="flex items-center">
                            <span class="text-3xl font-bold text-white mr-3">{{ aps.filter(a => a.status === 'Online').length }}</span>
                            <span class="text-slate-500 text-sm">/ {{ aps.length }} Total</span>
                        </div>
                    </div>
                    <div class="bg-slate-800 rounded-lg p-6 shadow-lg border border-slate-700 border-l-4 border-l-indigo-500">
                        <h3 class="text-indigo-400 text-sm font-semibold uppercase tracking-wider mb-2">Active Users Right Now</h3>
                        <div class="text-4xl font-bold text-white">{{ active_clients.length }}</div>
                    </div>
                </div>

                <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
                    <!-- Hardware Health -->
                    <div class="lg:col-span-1 space-y-6">
                        <div class="bg-slate-800 rounded-lg shadow-lg border border-slate-700 overflow-hidden">
                            <div class="px-6 py-4 border-b border-slate-700 bg-slate-800/50">
                                <h2 class="text-lg font-medium text-white">Hardware Health</h2>
                            </div>
                            <ul class="divide-y divide-slate-700">
                                <li v-for="router in routers" :key="router.name" class="px-6 py-4">
                                    <div class="flex items-center justify-between mb-2">
                                        <div class="flex items-center">
                                            <div :class="router.status === 'Online' ? 'bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.6)]' : 'bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.6)]'" class="w-3 h-3 rounded-full mr-3"></div>
                                            <span class="text-white font-medium">{{ router.device_name || router.name }}</span>
                                        </div>
                                        <span class="text-xs text-slate-400 bg-slate-700 px-2 py-1 rounded">{{ router.vpn_ip_address || 'No VPN IP' }}</span>
                                    </div>
                                    
                                    <!-- APs for this Router -->
                                    <div v-if="getApsForRouter(router.name).length" class="ml-6 mt-3 space-y-2">
                                        <div v-for="ap in getApsForRouter(router.name)" :key="ap.name" class="flex items-center justify-between text-sm">
                                            <div class="flex items-center text-slate-300">
                                                <div :class="ap.status === 'Online' ? 'bg-green-400' : 'bg-slate-600'" class="w-2 h-2 rounded-full mr-2"></div>
                                                {{ ap.ap_name }}
                                            </div>
                                            <span class="text-slate-500 text-xs">{{ ap.lan_ip }}</span>
                                        </div>
                                    </div>
                                </li>
                            </ul>
                        </div>
                    </div>

                    <!-- Live Active Users -->
                    <div class="lg:col-span-2">
                        <div class="bg-slate-800 rounded-lg shadow-lg border border-slate-700 overflow-hidden">
                            <div class="px-6 py-4 border-b border-slate-700 bg-slate-800/50 flex justify-between items-center">
                                <h2 class="text-lg font-medium text-white">Live Radar (Active Users)</h2>
                                <button @click="fetchData" class="text-indigo-400 hover:text-indigo-300 text-sm flex items-center transition-colors">
                                    <svg class="w-4 h-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path></svg>
                                    Refresh
                                </button>
                            </div>
                            <div class="overflow-x-auto">
                                <table class="w-full text-left border-collapse">
                                    <thead>
                                        <tr class="bg-slate-900/50 text-slate-400 text-xs uppercase tracking-wider">
                                            <th class="px-6 py-3 font-medium">Device MAC</th>
                                            <th class="px-6 py-3 font-medium">IP Address</th>
                                            <th class="px-6 py-3 font-medium">Data (D/U)</th>
                                            <th class="px-6 py-3 font-medium text-right">Action</th>
                                        </tr>
                                    </thead>
                                    <tbody class="divide-y divide-slate-700">
                                        <tr v-if="active_clients.length === 0">
                                            <td colspan="4" class="px-6 py-8 text-center text-slate-500 font-medium">No active users currently online.</td>
                                        </tr>
                                        <tr v-for="client in active_clients" :key="client.name" class="hover:bg-slate-700/30 transition-colors">
                                            <td class="px-6 py-4 text-white font-mono text-sm">{{ client.mac_address }}</td>
                                            <td class="px-6 py-4 text-slate-300 text-sm">{{ client.ip_address }}</td>
                                            <td class="px-6 py-4">
                                                <div class="flex flex-col space-y-1">
                                                    <span class="text-green-400 text-xs font-medium flex items-center"><svg class="w-3 h-3 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 14l-7 7m0 0l-7-7m7 7V3"></path></svg> {{ formatBytes(client.download_bytes) }}</span>
                                                    <span class="text-blue-400 text-xs font-medium flex items-center"><svg class="w-3 h-3 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 10l7-7m0 0l7 7m-7-7v18"></path></svg> {{ formatBytes(client.upload_bytes) }}</span>
                                                </div>
                                            </td>
                                            <td class="px-6 py-4 text-right">
                                                <button @click="kickUser(client)" :disabled="kicking === client.mac_address" class="px-3 py-1.5 bg-red-500/10 hover:bg-red-500/20 text-red-500 border border-red-500/30 rounded text-xs font-medium transition-colors disabled:opacity-50 flex items-center justify-end ml-auto">
                                                    <svg v-if="kicking === client.mac_address" class="animate-spin -ml-1 mr-2 h-3 w-3 text-red-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                                                        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                                                        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                                                    </svg>
                                                    {{ kicking === client.mac_address ? 'Kicking...' : 'Kick User' }}
                                                </button>
                                            </td>
                                        </tr>
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `);

    // Initialize Vue App
    new Vue({
        el: '#noc-dashboard-app',
        data: {
            loading: true,
            routers: [],
            aps: [],
            active_clients: [],
            kicking: null
        },
        mounted() {
            this.fetchData();
            // Auto refresh every 30 seconds
            setInterval(() => this.fetchData(), 30000);
        },
        methods: {
            fetchData() {
                frappe.call({
                    method: 'hotspot_ms.hotspot_ms.page.network_dashboard.network_dashboard.get_dashboard_data',
                    callback: (r) => {
                        if (r.message) {
                            this.routers = r.message.routers || [];
                            this.aps = r.message.aps || [];
                            this.active_clients = r.message.active_clients || [];
                        }
                        this.loading = false;
                    }
                });
            },
            getApsForRouter(routerName) {
                return this.aps.filter(ap => ap.nas_device === routerName);
            },
            formatBytes(bytes, decimals = 2) {
                if (!+bytes) return '0 Bytes';
                const k = 1024;
                const dm = decimals < 0 ? 0 : decimals;
                const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB'];
                const i = Math.floor(Math.log(bytes) / Math.log(k));
                return \`\${parseFloat((bytes / Math.pow(k, i)).toFixed(dm))} \${sizes[i]}\`;
            },
            kickUser(client) {
                frappe.confirm(\`Are you sure you want to instantly disconnect \${client.mac_address}?\`, () => {
                    this.kicking = client.mac_address;
                    frappe.call({
                        method: 'hotspot_ms.hotspot_ms.page.network_dashboard.network_dashboard.kick_client',
                        args: {
                            mac_address: client.mac_address,
                            nas_device_name: client.nas_device
                        },
                        callback: (r) => {
                            this.kicking = null;
                            if (!r.exc) {
                                frappe.show_alert({message: \`Successfully disconnected \${client.mac_address}\`, indicator: 'green'});
                                this.fetchData();
                            }
                        }
                    });
                });
            }
        }
    });
}