frappe.pages['network-dashboard'].on_page_load = function(wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Network Dashboard',
		single_column: true
	});

    if (!document.getElementById('tailwind-cdn')) {
        let script = document.createElement('script');
        script.id = 'tailwind-cdn';
        script.src = 'https://cdn.tailwindcss.com';
        document.head.appendChild(script);
    }

    $(wrapper).find('.layout-main-section').append(`
        <div id="noc-dashboard-app" class="p-6 bg-slate-50 min-h-screen">
            <div v-if="loading && firstLoad" class="flex justify-center items-center h-64">
                <div class="animate-spin rounded-full h-10 w-10 border-b-2 border-indigo-600"></div>
            </div>
            
            <div v-else>
                <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
                    <div class="bg-white rounded-xl p-6 shadow-sm border border-slate-200 transition-all hover:shadow-md">
                        <div class="flex items-center justify-between">
                            <div>
                                <p class="text-sm font-medium text-slate-500 mb-1">Routers Online</p>
                                <div class="flex items-baseline">
                                    <h3 class="text-3xl font-bold text-slate-800">{{ routers.filter(r => r.status === 'Online').length }}</h3>
                                    <span class="ml-2 text-sm font-medium text-slate-500">/ {{ routers.length }} Total</span>
                                </div>
                            </div>
                            <div class="p-3 bg-indigo-50 rounded-lg">
                                <svg class="w-6 h-6 text-indigo-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2m-2-4h.01M17 16h.01"></path></svg>
                            </div>
                        </div>
                    </div>
                    
                    <div class="bg-white rounded-xl p-6 shadow-sm border border-slate-200 transition-all hover:shadow-md">
                        <div class="flex items-center justify-between">
                            <div>
                                <p class="text-sm font-medium text-slate-500 mb-1">Access Points Online</p>
                                <div class="flex items-baseline">
                                    <h3 class="text-3xl font-bold text-slate-800">{{ aps.filter(a => a.status === 'Online').length }}</h3>
                                    <span class="ml-2 text-sm font-medium text-slate-500">/ {{ aps.length }} Total</span>
                                </div>
                            </div>
                            <div class="p-3 bg-emerald-50 rounded-lg">
                                <svg class="w-6 h-6 text-emerald-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.111 16.404a5.5 5.5 0 017.778 0M12 20h.01m-7.08-7.071c3.904-3.905 10.236-3.905 14.141 0M1.394 9.393c5.857-5.857 15.355-5.857 21.213 0"></path></svg>
                            </div>
                        </div>
                    </div>

                    <div class="bg-gradient-to-br from-indigo-600 to-indigo-800 rounded-xl p-6 shadow-md text-white">
                        <div class="flex items-center justify-between">
                            <div>
                                <p class="text-indigo-100 text-sm font-medium mb-1">Active Users Right Now</p>
                                <h3 class="text-4xl font-bold">{{ active_clients.length }}</h3>
                            </div>
                            <div class="p-3 bg-white/20 rounded-lg backdrop-blur-sm">
                                <svg class="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z"></path></svg>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
                    <div class="lg:col-span-1 space-y-6">
                        <div class="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
                            <div class="px-6 py-4 border-b border-slate-100 bg-slate-50/50">
                                <h2 class="text-base font-semibold text-slate-800">Hardware Health</h2>
                            </div>
                            <ul class="divide-y divide-slate-100">
                                <li v-for="router in routers" :key="router.name" class="px-6 py-4 hover:bg-slate-50 transition-colors">
                                    <div class="flex items-center justify-between mb-2">
                                        <div class="flex items-center">
                                            <span class="relative flex h-3 w-3 mr-3">
                                              <span v-if="router.status === 'Online'" class="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                                              <span :class="router.status === 'Online' ? 'bg-emerald-500' : 'bg-rose-500'" class="relative inline-flex rounded-full h-3 w-3"></span>
                                            </span>
                                            <span class="text-slate-700 font-semibold">{{ router.device_name || router.name }}</span>
                                        </div>
                                        <span class="text-xs font-mono text-slate-500 bg-slate-100 px-2.5 py-1 rounded-md">{{ router.vpn_ip_address || 'No VPN IP' }}</span>
                                    </div>
                                    
                                    <div v-if="getApsForRouter(router.name).length" class="ml-6 mt-3 space-y-2">
                                        <div v-for="ap in getApsForRouter(router.name)" :key="ap.name" class="flex items-center justify-between text-sm">
                                            <div class="flex items-center text-slate-600">
                                                <div :class="ap.status === 'Online' ? 'bg-emerald-400' : 'bg-slate-300'" class="w-2 h-2 rounded-full mr-2"></div>
                                                {{ ap.ap_name }}
                                            </div>
                                            <span class="text-slate-400 font-mono text-xs">{{ ap.lan_ip }}</span>
                                        </div>
                                    </div>
                                </li>
                            </ul>
                        </div>
                    </div>

                    <div class="lg:col-span-2">
                        <div class="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
                            <div class="px-6 py-4 border-b border-slate-100 bg-slate-50/50 flex justify-between items-center">
                                <h2 class="text-base font-semibold text-slate-800">Live Radar (Active Users)</h2>
                                <button @click="fetchData" :disabled="loading" class="text-indigo-600 hover:text-indigo-800 hover:bg-indigo-50 px-3 py-1.5 rounded-md text-sm font-medium flex items-center transition-all disabled:opacity-50">
                                    <svg :class="{'animate-spin': loading}" class="w-4 h-4 mr-1.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path></svg>
                                    {{ loading ? 'Refreshing...' : 'Refresh' }}
                                </button>
                            </div>
                            <div class="overflow-x-auto">
                                <table class="w-full text-left border-collapse">
                                    <thead>
                                        <tr class="bg-white text-slate-500 text-xs uppercase tracking-wider border-b border-slate-200">
                                            <th class="px-6 py-4 font-semibold">Device MAC</th>
                                            <th class="px-6 py-4 font-semibold">IP Address</th>
                                            <th class="px-6 py-4 font-semibold">Voucher</th>
                                            <th class="px-6 py-4 font-semibold">Data (D/U)</th>
                                            <th class="px-6 py-4 font-semibold text-right">Action</th>
                                        </tr>
                                    </thead>
                                    <tbody class="divide-y divide-slate-100">
                                        <tr v-if="active_clients.length === 0">
                                            <td colspan="5" class="px-6 py-12 text-center text-slate-500">
                                                <div class="flex flex-col items-center">
                                                    <svg class="w-12 h-12 text-slate-300 mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z"></path></svg>
                                                    <p class="font-medium">No active users currently online.</p>
                                                    <p class="text-sm mt-1 text-slate-400">Clients will appear here automatically when they connect.</p>
                                                </div>
                                            </td>
                                        </tr>
                                        <tr v-for="client in active_clients" :key="client.name" class="hover:bg-slate-50 transition-colors group">
                                            <td class="px-6 py-4 text-slate-700 font-mono text-sm">{{ client.mac_address }}</td>
                                            <td class="px-6 py-4 text-slate-600 text-sm font-medium">{{ client.ip_address }}</td>
                                            <td class="px-6 py-4">
                                                <div class="flex flex-col">
                                                    <span class="text-sm font-semibold text-slate-700">{{ client.voucher_code }}</span>
                                                    <span v-if="client.voucher_status === 'Null'" class="text-[10px] font-bold text-rose-500 uppercase tracking-wider mt-0.5">Ghost MAC / No Voucher</span>
                                                    <span v-else class="text-[10px] font-bold text-emerald-500 uppercase tracking-wider mt-0.5">{{ client.voucher_status }}</span>
                                                </div>
                                            </td>
                                            <td class="px-6 py-4">
                                                <div class="flex items-center space-x-3">
                                                    <span class="text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded text-xs font-semibold flex items-center border border-emerald-100">
                                                        <svg class="w-3 h-3 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 14l-7 7m0 0l-7-7m7 7V3"></path></svg> 
                                                        {{ formatBytes(client.download_bytes * 1024) }}
                                                    </span>
                                                    <span class="text-blue-600 bg-blue-50 px-2 py-0.5 rounded text-xs font-semibold flex items-center border border-blue-100">
                                                        <svg class="w-3 h-3 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 10l7-7m0 0l7 7m-7-7v18"></path></svg> 
                                                        {{ formatBytes(client.upload_bytes * 1024) }}
                                                    </span>
                                                </div>
                                            </td>
                                            <td class="px-6 py-4 text-right">
                                                <button @click="kickUser(client)" :disabled="kicking === client.mac_address" class="px-3 py-1.5 bg-white hover:bg-rose-50 text-rose-600 border border-rose-200 hover:border-rose-300 rounded-md text-xs font-semibold transition-all disabled:opacity-50 flex items-center justify-end ml-auto shadow-sm group-hover:shadow">
                                                    <svg v-if="kicking === client.mac_address" class="animate-spin -ml-1 mr-2 h-3 w-3 text-rose-600" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                                                        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                                                        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                                                    </svg>
                                                    <svg v-else class="w-3.5 h-3.5 mr-1.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636"></path></svg>
                                                    {{ kicking === client.mac_address ? 'Disconnecting...' : 'Kick' }}
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

    frappe.require('https://cdn.jsdelivr.net/npm/vue@2.6.14/dist/vue.js', () => {
        new Vue({
            el: '#noc-dashboard-app',
            data: {
                loading: true,
                firstLoad: true,
                routers: [],
                aps: [],
                active_clients: [],
                kicking: null
            },
            mounted() {
                this.fetchData();
                setInterval(() => this.fetchData(), 30000);
            },
            methods: {
                fetchData() {
                    this.loading = true;
                    frappe.call({
                        method: 'hotspot_ms.hotspot_ms.page.network_dashboard.network_dashboard.get_dashboard_data',
                        callback: (r) => {
                            if (r.message) {
                                this.routers = r.message.routers || [];
                                this.aps = r.message.aps || [];
                                this.active_clients = r.message.active_clients || [];
                            }
                            this.loading = false;
                            this.firstLoad = false;
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
                    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(dm))} ${sizes[i]}`;
                },
                kickUser(client) {
                    frappe.confirm(`Are you sure you want to instantly disconnect ${client.mac_address}?`, () => {
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
                                    frappe.show_alert({message: `Successfully disconnected ${client.mac_address}`, indicator: 'green'});
                                    this.fetchData();
                                }
                            }
                        });
                    });
                }
            }
        });
    });
}