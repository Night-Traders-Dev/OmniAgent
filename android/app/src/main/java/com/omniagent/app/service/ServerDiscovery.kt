package com.omniagent.app.service

import android.content.Context
import android.net.wifi.WifiManager
import android.util.Log
import kotlinx.coroutines.*
import okhttp3.OkHttpClient
import okhttp3.Request
import com.google.gson.Gson
import com.google.gson.JsonObject
import java.net.Inet4Address
import java.net.InetSocketAddress
import java.net.NetworkInterface
import java.net.Socket
import java.util.concurrent.TimeUnit

private const val TAG = "ServerDiscovery"

data class DiscoveredServer(
    val ip: String,
    val port: Int = 8000,
    val version: String = "",
    val agents: List<String> = emptyList(),
)

class ServerDiscovery(private val context: Context) {

    private val scanClient = OkHttpClient.Builder()
        .connectTimeout(1500, TimeUnit.MILLISECONDS)
        .readTimeout(2, TimeUnit.SECONDS)
        .build()

    private val verifyClient = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(5, TimeUnit.SECONDS)
        .build()

    private val gson = Gson()

    fun getLocalIpInfo(): Pair<String, String>? {
        // Method 1: NetworkInterface
        try {
            for (iface in NetworkInterface.getNetworkInterfaces()) {
                if (iface.isLoopback || !iface.isUp) continue
                // Prefer wlan interfaces
                val name = iface.name.lowercase()
                if (name != "wlan0" && name != "wlan1" && !name.startsWith("wl")) continue
                for (addr in iface.inetAddresses) {
                    if (addr is Inet4Address && !addr.isLoopbackAddress) {
                        val ip = addr.hostAddress ?: continue
                        if (ip.startsWith("169.254") || ip.startsWith("127.")) continue
                        val parts = ip.split(".")
                        if (parts.size == 4) {
                            val prefix = "${parts[0]}.${parts[1]}.${parts[2]}"
                            Log.d(TAG, "Found IP via wlan interface: $ip (prefix: $prefix)")
                            return Pair(ip, prefix)
                        }
                    }
                }
            }
            // Fallback: any non-loopback IPv4
            for (iface in NetworkInterface.getNetworkInterfaces()) {
                if (iface.isLoopback || !iface.isUp) continue
                for (addr in iface.inetAddresses) {
                    if (addr is Inet4Address && !addr.isLoopbackAddress) {
                        val ip = addr.hostAddress ?: continue
                        if (ip.startsWith("169.254") || ip.startsWith("127.")) continue
                        val parts = ip.split(".")
                        if (parts.size == 4) {
                            val prefix = "${parts[0]}.${parts[1]}.${parts[2]}"
                            Log.d(TAG, "Found IP via fallback interface: $ip (prefix: $prefix)")
                            return Pair(ip, prefix)
                        }
                    }
                }
            }
        } catch (e: Exception) {
            Log.w(TAG, "NetworkInterface failed: ${e.message}")
        }

        // Method 2: WifiManager
        try {
            val wifiManager = context.applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
            @Suppress("DEPRECATION")
            val ipInt = wifiManager.connectionInfo.ipAddress
            if (ipInt != 0) {
                val ip = "${ipInt and 0xff}.${ipInt shr 8 and 0xff}.${ipInt shr 16 and 0xff}.${ipInt shr 24 and 0xff}"
                val prefix = "${ipInt and 0xff}.${ipInt shr 8 and 0xff}.${ipInt shr 16 and 0xff}"
                Log.d(TAG, "Found IP via WifiManager: $ip (prefix: $prefix)")
                return Pair(ip, prefix)
            }
        } catch (e: Exception) {
            Log.w(TAG, "WifiManager failed: ${e.message}")
        }

        Log.e(TAG, "Could not determine local IP address")
        return null
    }

    /**
     * Fast port scan: check if port 8000 is open without full HTTP request.
     * Much faster than HTTP-based scanning for filtering out dead hosts.
     */
    private fun isPortOpen(ip: String, port: Int, timeoutMs: Int = 500): Boolean {
        return try {
            val socket = Socket()
            socket.connect(InetSocketAddress(ip, port), timeoutMs)
            socket.close()
            true
        } catch (_: Exception) {
            false
        }
    }

    suspend fun scanNetwork(
        port: Int = 8000,
        onProgress: (Int, Int) -> Unit = { _, _ -> },
        onFound: (DiscoveredServer) -> Unit = {},
    ): List<DiscoveredServer> = withContext(Dispatchers.IO) {
        val ipInfo = getLocalIpInfo()
        if (ipInfo == null) {
            Log.e(TAG, "Cannot scan: no local IP found")
            return@withContext emptyList()
        }

        val (deviceIp, prefix) = ipInfo
        val found = mutableListOf<DiscoveredServer>()
        val total = 254

        Log.d(TAG, "Scanning $prefix.1-254 on port $port (device IP: $deviceIp)")

        // Phase 1: Fast TCP port scan to find hosts with port 8000 open
        val openHosts = mutableListOf<String>()
        (1..254).chunked(50).forEach { batch ->
            val jobs = batch.map { i ->
                async {
                    val ip = "$prefix.$i"
                    onProgress(i, total)
                    if (isPortOpen(ip, port, 500)) ip else null
                }
            }
            jobs.awaitAll().filterNotNull().forEach { ip ->
                openHosts.add(ip)
                Log.d(TAG, "Port $port open on $ip")
            }
        }

        Log.d(TAG, "Phase 1 complete: ${openHosts.size} hosts with port $port open")

        // Phase 2: Verify only the hosts that have port 8000 open
        for (ip in openHosts) {
            val server = tryConnect(ip, port, scanClient)
            if (server != null) {
                found.add(server)
                onFound(server)
                Log.d(TAG, "Verified OmniAgent at ${server.ip}:${server.port}")
            }
        }

        Log.d(TAG, "Scan complete. Found ${found.size} OmniAgent servers.")
        found
    }

    suspend fun tryConnect(ip: String, port: Int = 8000, httpClient: OkHttpClient? = null): DiscoveredServer? {
        val client = httpClient ?: verifyClient

        // Try /api/identify
        try {
            val request = Request.Builder()
                .url("http://$ip:$port/api/identify")
                .build()
            val response = client.newCall(request).execute()
            if (response.isSuccessful) {
                val body = response.body?.string() ?: return tryFallbackMetrics(ip, port, client)
                val json = gson.fromJson(body, JsonObject::class.java)
                if (json.get("service")?.asString == "OmniAgent") {
                    return DiscoveredServer(
                        ip = ip,
                        port = port,
                        version = json.get("version")?.asString ?: "unknown",
                        agents = try { json.getAsJsonArray("agents")?.map { it.asString } ?: emptyList() } catch (_: Exception) { emptyList() },
                    )
                }
            }
        } catch (e: Exception) {
            Log.d(TAG, "identify failed for $ip: ${e.message}")
        }

        return tryFallbackMetrics(ip, port, client)
    }

    private fun tryFallbackMetrics(ip: String, port: Int, client: OkHttpClient): DiscoveredServer? {
        return try {
            val request = Request.Builder()
                .url("http://$ip:$port/api/metrics")
                .build()
            val response = client.newCall(request).execute()
            if (response.isSuccessful) {
                val body = response.body?.string() ?: return null
                val json = gson.fromJson(body, JsonObject::class.java)
                if (json.has("status") && json.has("tasks_completed") && json.has("total_llm_calls")) {
                    DiscoveredServer(
                        ip = ip, port = port, version = "7.x",
                        agents = listOf("reasoner", "coder", "researcher", "planner", "tool_user", "security"),
                    )
                } else null
            } else null
        } catch (_: Exception) {
            null
        }
    }
}
