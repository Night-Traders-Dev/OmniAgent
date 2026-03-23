package com.omniagent.app.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.omniagent.app.network.OmniAgentApi
import com.omniagent.app.network.StreamEvent
import com.omniagent.app.service.DiscoveredServer
import com.omniagent.app.service.ServerDiscovery
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.launch

data class UiMessage(
    val role: String,
    val content: String,
    val isStreaming: Boolean = false,
    val thinkingSteps: List<String> = emptyList(),
    val thinkingElapsed: String = "",
    val isExpanded: Boolean = false,
)

data class ChatUiState(
    // Auth
    val authState: String = "checking", // checking, login, authenticated
    val authUsername: String = "",
    val authError: String? = null,
    val isAdmin: Boolean = false,
    // Connection
    val connectionState: String = "disconnected",
    val serverIp: String = "",
    val scanProgress: Float = 0f,
    val discoveredServers: List<DiscoveredServer> = emptyList(),
    val messages: List<UiMessage> = emptyList(),
    val inputText: String = "",
    val isSending: Boolean = false,
    val status: String = "Idle",
    val gpu: String = "--",
    val taskStartedAt: String? = null,
    val currentStep: String = "",
    val stepIndex: Int = 0,
    val totalSteps: Int = 0,
    val activeModel: String = "",
    val tasksCompleted: Int = 0,
    val llmCalls: Int = 0,
    val sessionMessages: Int = 0,
    val commandsRun: Int = 0,
    val executionMode: String = "execute",
    val toolToggles: Map<String, Boolean> = mapOf(
        "web_search" to true, "file_read" to true, "file_write" to true, "shell" to true,
        "vision" to true, "image_gen" to true, "voice" to true, "git" to true,
    ),
    val modelOverride: String = "auto",
    val systemPrompt: String = "",
    val experts: Map<String, String> = emptyMap(),
    val installedModels: List<String> = emptyList(),
    val showSettings: Boolean = false,
    val error: String? = null,
    // Integrations
    val githubConnected: Boolean = false,
    val googleConnected: Boolean = false,
    val githubAuthUrl: String = "",
    val googleAuthUrl: String = "",
    val githubOAuth: Boolean = false,
    val googleOAuth: Boolean = false,
    // Session history
    val sessionList: List<Map<String, String>> = emptyList(),
    val showSessionDrawer: Boolean = false,
    // BitNet
    val bitnetEnabled: Boolean = false,
    // Token metrics
    val tokensIn: Int = 0,
    val tokensOut: Int = 0,
    // Memory
    val memories: List<Map<String, String>> = emptyList(),
    // Plugins
    val plugins: List<Map<String, String>> = emptyList(),
    val pluginsError: String? = null,
    // Search
    val showSearch: Boolean = false,
    val searchResults: List<Map<String, String>> = emptyList(),
    // Presets & Templates
    val presets: Map<String, String> = emptyMap(),
    val templates: Map<String, String> = emptyMap(),
    // GPU Workers
    val gpuWorkers: Int = 0,
    // Advanced Reasoning
    val largeModelRouting: Boolean = false,
    // Reasoning History
    val reasoningHistory: List<String> = emptyList(),
    val showReasoningHistory: Boolean = false,
    // Changelog
    val changelogContent: String = "",
    val showChangelog: Boolean = false,
    // On-device AI
    val onDeviceAI: Boolean = false,
    val onDeviceNPU: String = "",
    val smartReplies: List<String> = emptyList(),
    val onDeviceEnabled: Boolean = true,
    // Server version (fetched from /api/version)
    val serverVersion: String = "...",
)

class ChatViewModel(app: Application) : AndroidViewModel(app) {
    val api = OmniAgentApi()
    private val discovery = ServerDiscovery(app)
    private val prefs = try {
        androidx.security.crypto.EncryptedSharedPreferences.create(
            "omni_auth_secure",
            androidx.security.crypto.MasterKeys.getOrCreate(androidx.security.crypto.MasterKeys.AES256_GCM_SPEC),
            app, androidx.security.crypto.EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            androidx.security.crypto.EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
    } catch (_: Exception) {
        // Fallback if crypto fails (e.g. old device)
        app.getSharedPreferences("omni_auth", android.content.Context.MODE_PRIVATE)
    }

    private val _state = MutableStateFlow(ChatUiState())

    init {
        // Initialize on-device AI (Snapdragon NPU / Samsung NPU)
        // Wrapped in Throwable catch — TFLite native libs can throw NoClassDefFoundError
        try {
            com.omniagent.app.ai.OnDeviceAI.init(app)
            val avail = com.omniagent.app.ai.OnDeviceAI.isAvailable
            val npu = com.omniagent.app.ai.OnDeviceAI.npuName
            _state.update { it.copy(onDeviceAI = avail, onDeviceNPU = npu) }
        } catch (_: Throwable) {}

        // Restore saved session and server
        val savedSession = prefs.getString("session_id", null)
        val savedServer = prefs.getString("server_ip", null)
        val savedPort = prefs.getInt("server_port", 8000)
        if (savedSession != null) api.sessionId = savedSession
        if (savedServer != null) {
            if (savedServer.startsWith("https://") || savedServer.startsWith("http://")) {
                api.setServerUrl(savedServer)
            } else {
                api.setServer(savedServer, savedPort)
            }
            _state.update { it.copy(connectionState = "connected", serverIp = savedServer, authState = "checking") }
            checkAuthWithRetry(savedServer)
        }
    }

    private fun checkAuthWithRetry(serverUrl: String) {
        viewModelScope.launch {
            try {
                val d = api.checkAuth()
                if (d.get("authenticated")?.asBoolean == true) {
                    _state.update {
                        it.copy(
                            authState = "authenticated",
                            authUsername = d.get("username")?.asString ?: "",
                            isAdmin = d.get("is_admin")?.asBoolean ?: false,
                        )
                    }
                    startAfterAuth()
                    return@launch
                }
                _state.update { it.copy(authState = "login") }
            } catch (e: Exception) {
                // Connection failed — if it's a tunnel URL, try re-resolving via pairing code
                val savedCode = prefs.getString("pairing_code", null)
                if (savedCode != null && serverUrl.contains("trycloudflare.com")) {
                    try {
                        val newUrl = api.resolvePairingCode(savedCode)
                        if (newUrl != null && newUrl != serverUrl) {
                            api.setServerUrl(newUrl)
                            prefs.edit().putString("server_ip", newUrl).apply()
                            _state.update { it.copy(serverIp = newUrl) }
                            // Retry auth with new URL
                            try {
                                val d2 = api.checkAuth()
                                if (d2.get("authenticated")?.asBoolean == true) {
                                    _state.update {
                                        it.copy(
                                            authState = "authenticated",
                                            authUsername = d2.get("username")?.asString ?: "",
                                            isAdmin = d2.get("is_admin")?.asBoolean ?: false,
                                        )
                                    }
                                    startAfterAuth()
                                    return@launch
                                }
                            } catch (_: Exception) {}
                        }
                    } catch (_: Exception) {}
                }
                _state.update { it.copy(authState = "login", error = "Server unreachable. Reconnect or enter new pairing code.") }
            }
        }
    }

    private fun saveAuth(sessionId: String, username: String, serverIp: String, port: Int) {
        val editor = prefs.edit()
            .putString("session_id", sessionId)
            .putString("username", username)
            .putString("server_ip", serverIp)
            .putInt("server_port", port)
        if (_rememberDevice) {
            editor.putBoolean("remember_device", true)
            // Keep existing pairing_code if set
        } else {
            editor.remove("remember_device")
            editor.remove("pairing_code")
            editor.remove("username")
        }
        editor.apply()
    }
    val state: StateFlow<ChatUiState> = _state.asStateFlow()

    private var sseJob: kotlinx.coroutines.Job? = null
    private var thinkingTimerJob: kotlinx.coroutines.Job? = null
    private var thinkingSteps = mutableListOf<String>()
    private var thinkingStartTime = 0L

    fun updateInput(text: String) {
        _state.update { it.copy(inputText = text) }
    }

    // --- Connection ---

    fun scanForServer() {
        _state.update { it.copy(connectionState = "scanning", scanProgress = 0f, discoveredServers = emptyList()) }
        viewModelScope.launch {
            val servers = discovery.scanNetwork(
                onProgress = { current, total -> _state.update { it.copy(scanProgress = current.toFloat() / total) } },
                onFound = { server -> _state.update { it.copy(discoveredServers = it.discoveredServers + server) } },
            )
            if (servers.isNotEmpty()) connectToServer(servers.first().ip, servers.first().port)
            else _state.update { it.copy(connectionState = "disconnected", error = "No OmniAgent server found") }
        }
    }

    fun connectToServer(ip: String, port: Int = 8000) {
        api.setServer(ip, port)
        // After connecting, check auth
        _state.update { it.copy(connectionState = "connected", serverIp = ip, error = null, authState = "checking") }
        checkAuth()
    }

    fun checkAuth() {
        viewModelScope.launch {
            try {
                val d = api.checkAuth()
                if (d.get("authenticated")?.asBoolean == true) {
                    _state.update {
                        it.copy(
                            authState = "authenticated",
                            authUsername = d.get("username")?.asString ?: "",
                            isAdmin = d.get("is_admin")?.asBoolean ?: false,
                        )
                    }
                    startAfterAuth()
                } else {
                    _state.update { it.copy(authState = "login") }
                }
            } catch (_: Exception) {
                _state.update { it.copy(authState = "login") }
            }
        }
    }

    fun doLogin(username: String, password: String) {
        viewModelScope.launch {
            try {
                val d = api.login(username, password)
                if (d.get("ok")?.asBoolean == true) {
                    val sid = d.get("session_id")?.asString ?: api.sessionId
                    val uname = d.get("username")?.asString ?: ""
                    api.sessionId = sid
                    saveAuth(sid, uname, _state.value.serverIp, 8000)
                    _state.update {
                        it.copy(
                            authState = "authenticated",
                            authUsername = uname,
                            authError = null,
                            isAdmin = d.get("is_admin")?.asBoolean ?: false,
                        )
                    }
                    startAfterAuth()
                } else {
                    _state.update { it.copy(authError = d.get("error")?.asString ?: "Login failed") }
                }
            } catch (e: Exception) {
                // Network error — tunnel URL may be stale. Try re-resolving via pairing code.
                val savedCode = prefs.getString("pairing_code", null)
                val serverUrl = _state.value.serverIp
                if (savedCode != null && serverUrl.contains("trycloudflare.com")) {
                    _state.update { it.copy(authError = "Tunnel expired, re-pairing...") }
                    try {
                        val newUrl = api.resolvePairingCode(savedCode)
                        if (newUrl != null && newUrl != serverUrl) {
                            api.setServerUrl(newUrl)
                            prefs.edit().putString("server_ip", newUrl).apply()
                            _state.update { it.copy(serverIp = newUrl, authError = "Reconnected! Retrying login...") }
                            // Retry login with new URL
                            try {
                                val d2 = api.login(username, password)
                                if (d2.get("ok")?.asBoolean == true) {
                                    val sid = d2.get("session_id")?.asString ?: api.sessionId
                                    val uname = d2.get("username")?.asString ?: ""
                                    api.sessionId = sid
                                    saveAuth(sid, uname, newUrl, 443)
                                    _state.update {
                                        it.copy(
                                            authState = "authenticated",
                                            authUsername = uname,
                                            authError = null,
                                            isAdmin = d2.get("is_admin")?.asBoolean ?: false,
                                        )
                                    }
                                    startAfterAuth()
                                    return@launch
                                }
                                _state.update { it.copy(authError = d2.get("error")?.asString ?: "Login failed") }
                            } catch (e2: Exception) {
                                _state.update { it.copy(authError = "Reconnected but login failed: ${e2.message}") }
                            }
                            return@launch
                        }
                    } catch (_: Exception) {}
                }
                _state.update { it.copy(authError = "Connection failed: ${e.message}") }
            }
        }
    }

    fun doRegister(username: String, password: String, inviteCode: String = "") {
        viewModelScope.launch {
            try {
                val d = api.register(username, password, inviteCode)
                if (d.get("ok")?.asBoolean == true) {
                    val sid = d.get("session_id")?.asString ?: api.sessionId
                    val uname = d.get("username")?.asString ?: ""
                    api.sessionId = sid
                    saveAuth(sid, uname, _state.value.serverIp, 8000)
                    _state.update {
                        it.copy(
                            authState = "authenticated",
                            authUsername = uname,
                            authError = null,
                            isAdmin = d.get("is_admin")?.asBoolean ?: false,
                        )
                    }
                    startAfterAuth()
                } else {
                    _state.update { it.copy(authError = d.get("error")?.asString ?: "Registration failed") }
                }
            } catch (e: Exception) {
                _state.update { it.copy(authError = "Error: ${e.message}") }
            }
        }
    }

    fun doGuestLogin() {
        _state.update { it.copy(authState = "authenticated", authUsername = "guest", isAdmin = false) }
        startAfterAuth()
    }

    private var _rememberDevice = true
    fun setRememberDevice(value: Boolean) { _rememberDevice = value }

    fun doLogout() {
        // Keep server_ip and pairing_code if "remember device" was on
        val keepServer = prefs.getString("server_ip", null)
        val keepCode = if (prefs.getBoolean("remember_device", false)) prefs.getString("pairing_code", null) else null
        prefs.edit().clear().apply()
        if (keepServer != null) prefs.edit().putString("server_ip", keepServer).apply()
        if (keepCode != null) prefs.edit().putString("pairing_code", keepCode).putBoolean("remember_device", true).apply()
        _state.update { ChatUiState(connectionState = "connected", serverIp = _state.value.serverIp, authState = "login") }
    }

    private fun startAfterAuth() {
        android.util.Log.i("OmniAuth", "startAfterAuth called — baseUrl=${api.baseUrl}, sessionId=${api.sessionId}")
        viewModelScope.launch {
            try { startStatusStream() } catch (e: Throwable) { android.util.Log.e("OmniAuth", "startStatusStream failed: ${e.message}") }
        }
        loadSettings()
        loadBitNetState()
        loadSessionList()
        loadCurrentChat()
        loadPresets()
        loadTemplates()
        sendLocation()
    }

    private fun loadCurrentChat() {
        viewModelScope.launch {
            try {
                val d = api.loadSession(api.sessionId)
                if (d.get("ok")?.asBoolean == true) {
                    val msgs = mutableListOf<UiMessage>()
                    try {
                        val arr = d.getAsJsonArray("messages")
                        if (arr != null) {
                            for (i in 0 until arr.size()) {
                                val obj = arr.get(i).asJsonObject
                                msgs.add(UiMessage(
                                    role = obj.get("role")?.asString ?: "user",
                                    content = obj.get("content")?.asString ?: "",
                                ))
                            }
                        }
                    } catch (_: Exception) {}
                    if (msgs.isNotEmpty()) {
                        _state.update { it.copy(messages = msgs) }
                    }
                }
            } catch (_: Exception) {}
        }
    }

    fun connectManual(address: String) {
        val trimmed = address.trim().trimEnd('/')
        _state.update { it.copy(connectionState = "scanning", error = null) }
        viewModelScope.launch {
            try {
                // If it's a full URL (tunnel or direct), use it as-is
                if (trimmed.startsWith("https://") || trimmed.startsWith("http://")) {
                    api.setServerUrl(trimmed)
                    try {
                        api.getSettings()
                        prefs.edit().putString("server_ip", trimmed).putInt("server_port", 443).apply()
                        _state.update { it.copy(connectionState = "connected", serverIp = trimmed, error = null, authState = "checking") }
                        checkAuth()
                    } catch (e: Exception) {
                        _state.update { it.copy(connectionState = "disconnected", error = "Cannot connect: ${e.message}") }
                    }
                    return@launch
                }
                // Otherwise treat as IP:port
                val clean = trimmed.removePrefix("http://").removePrefix("https://")
                val parts = clean.split(":")
                val ip = parts[0]
                val port = parts.getOrNull(1)?.toIntOrNull() ?: 8000
                val server = discovery.tryConnect(ip, port)
                if (server != null) { connectToServer(ip, port); return@launch }
                api.setServer(ip, port)
                try { api.getSettings(); connectToServer(ip, port) }
                catch (e: Exception) { _state.update { it.copy(connectionState = "disconnected", error = "Cannot connect: ${e.message}") } }
            } catch (e: Exception) { _state.update { it.copy(connectionState = "disconnected", error = "Failed: ${e.message}") } }
        }
    }

    fun connectWithPairingCode(code: String) {
        val cleanCode = code.trim().lowercase()
        if (cleanCode.length < 4) {
            _state.update { it.copy(error = "Pairing code must be at least 4 characters") }
            return
        }
        _state.update { it.copy(connectionState = "scanning", error = null) }
        viewModelScope.launch {
            try {
                val url = api.resolvePairingCode(cleanCode)
                if (url != null) {
                    api.setServerUrl(url)
                    // Verify the server responds
                    try {
                        api.getSettings()
                        _state.update { it.copy(connectionState = "connected", serverIp = url, error = null, authState = "checking") }
                        prefs.edit().putString("server_ip", url).putInt("server_port", 443).putString("pairing_code", cleanCode).apply()
                        checkAuth()
                    } catch (e: Exception) {
                        _state.update { it.copy(connectionState = "disconnected", error = "Server found but not responding: ${e.message}") }
                    }
                } else {
                    _state.update { it.copy(connectionState = "disconnected", error = "No server found for code '$cleanCode'. Is OmniAgent running with a tunnel?") }
                }
            } catch (e: Exception) {
                _state.update { it.copy(connectionState = "disconnected", error = "Pairing failed: ${e.message}") }
            }
        }
    }

    // --- SSE Status Stream ---

    private fun startStatusStream() {
        sseJob?.cancel()
        sseJob = viewModelScope.launch {
            // Try SSE first — if it fails to deliver events within 5s, fall back to polling
            android.util.Log.i("OmniSSE", "Trying SSE stream...")
            var sseWorked = false
            try {
                kotlinx.coroutines.withTimeout(6000) {
                    api.streamStatus().collect { event ->
                        sseWorked = true
                        android.util.Log.i("OmniSSE", "SSE working! gpu=${event.gpu}")
                        handleStreamEvent(event)
                    }
                }
            } catch (e: kotlinx.coroutines.TimeoutCancellationException) {
                android.util.Log.w("OmniSSE", "SSE timed out — falling back to polling")
            } catch (e: Exception) {
                android.util.Log.w("OmniSSE", "SSE failed: ${e.message} — falling back to polling")
            }

            if (sseWorked) {
                // SSE was working, reconnect in SSE mode
                var retries = 0
                while (_state.value.authState == "authenticated") {
                    try {
                        api.streamStatus().collect { event -> handleStreamEvent(event) }
                    } catch (_: Exception) {}
                    val delay = minOf(2000L * (1L shl minOf(retries, 3)), 15000L)
                    retries++
                    kotlinx.coroutines.delay(delay)
                }
            } else {
                // SSE doesn't work (tunnel buffering) — use polling
                android.util.Log.i("OmniSSE", "Polling mode active (2s interval)")
                var pollCount = 0
                while (_state.value.authState == "authenticated") {
                    try {
                        val snapshot = api.pollStatus()
                        if (snapshot != null) {
                            handleStreamEvent(snapshot)
                            pollCount++
                            if (pollCount <= 2) android.util.Log.d("OmniSSE", "Poll #$pollCount: gpu=${snapshot.gpu} tasks=${snapshot.tasks_completed} msgs=${snapshot.session_messages}")
                        }
                    } catch (e: Exception) {
                        if (pollCount == 0) android.util.Log.e("OmniSSE", "Poll failed: ${e.message}")
                    }
                    kotlinx.coroutines.delay(2000)
                }
            }
        }
    }

    private fun handleStreamEvent(event: StreamEvent) {
        _state.update {
            it.copy(
                status = event.status, gpu = event.gpu, taskStartedAt = event.task_started_at,
                currentStep = event.current_step, stepIndex = event.step_index,
                totalSteps = event.total_steps, activeModel = event.active_model,
                tasksCompleted = event.tasks_completed, llmCalls = event.total_llm_calls,
                sessionMessages = event.session_messages, commandsRun = event.commands_run,
                tokensIn = event.tokens_in, tokensOut = event.tokens_out,
                gpuWorkers = event.gpu_workers,
            )
        }

        // Only collect thinking steps while a task is running AND we're actively sending
        if (event.log != null && event.task_started_at != null && _state.value.isSending) {
            thinkingSteps.add(event.log)
            updateThinkingMessage()
        }

        // Finalize on task completion
        if (event.task_started_at == null && thinkingSteps.isNotEmpty()) {
            finalizeThinking()
        }
    }

    private fun formatElapsed(): String {
        if (thinkingStartTime == 0L) return "0s"
        val elapsed = (System.currentTimeMillis() - thinkingStartTime) / 1000
        return if (elapsed >= 60) "${elapsed / 60}m ${elapsed % 60}s" else "${elapsed}s"
    }

    private fun startThinkingTimer() {
        thinkingTimerJob?.cancel()
        thinkingTimerJob = viewModelScope.launch {
            while (true) {
                kotlinx.coroutines.delay(500)
                if (thinkingStartTime == 0L) break
                val msgs = _state.value.messages.toMutableList()
                val lastThinking = msgs.indexOfLast { it.role == "thinking" }
                if (lastThinking >= 0) {
                    msgs[lastThinking] = msgs[lastThinking].copy(thinkingElapsed = formatElapsed())
                    _state.update { it.copy(messages = msgs) }
                }
            }
        }
    }

    private fun updateThinkingMessage() {
        if (thinkingStartTime == 0L) {
            thinkingStartTime = System.currentTimeMillis()
            startThinkingTimer()
        }

        val msgs = _state.value.messages.toMutableList()
        val lastThinking = msgs.indexOfLast { it.role == "thinking" }
        val thinkingMsg = UiMessage(
            role = "thinking", content = "Thinking... (${thinkingSteps.size} steps)",
            thinkingSteps = thinkingSteps.toList(), thinkingElapsed = formatElapsed(), isExpanded = true,
        )
        if (lastThinking >= 0 && msgs[lastThinking].isExpanded) msgs[lastThinking] = thinkingMsg
        else msgs.add(thinkingMsg)
        _state.update { it.copy(messages = msgs) }
    }

    private fun finalizeThinking() {
        if (thinkingSteps.isEmpty()) return
        thinkingTimerJob?.cancel()
        val elapsedStr = formatElapsed()
        val msgs = _state.value.messages.toMutableList()
        val lastThinking = msgs.indexOfLast { it.role == "thinking" }
        if (lastThinking >= 0) {
            msgs[lastThinking] = msgs[lastThinking].copy(
                content = "Thought for $elapsedStr (${thinkingSteps.size} steps)", isExpanded = false,
            )
            _state.update { it.copy(messages = msgs) }
        }
        thinkingSteps = mutableListOf()
        thinkingStartTime = 0L
    }

    fun toggleThinking(index: Int) {
        val msgs = _state.value.messages.toMutableList()
        if (index in msgs.indices && msgs[index].role == "thinking") {
            msgs[index] = msgs[index].copy(isExpanded = !msgs[index].isExpanded)
            _state.update { it.copy(messages = msgs) }
        }
    }

    // --- Chat ---

    private val locationKeywords = Regex(
        "\\b(weather|forecast|temperature|temp outside|rain|snow|humidity|wind|" +
        "near me|nearby|closest|around here|local|in my area|my area|" +
        "directions to|navigate to|how far|distance to|drive to|walk to|" +
        "restaurants?|stores?|shops?|gas station|pharmacy|hospital|" +
        "sunrise|sunset|time zone|what time is it|" +
        "air quality|pollen|uv index|where am i|my location|my city|my town)\\b",
        RegexOption.IGNORE_CASE
    )

    fun sendMessage(overrideText: String? = null, overrideModel: String? = null) {
        val text = (overrideText ?: _state.value.inputText).trim()
        if (text.isEmpty() || _state.value.isSending) return

        // Try on-device AI first for simple queries (runs on NPU, instant response)
        if (_state.value.onDeviceEnabled && overrideModel == null) {
            viewModelScope.launch {
                try {
                    com.omniagent.app.ai.OnDeviceAI.clearLog()
                    val localReply = com.omniagent.app.ai.OnDeviceAI.tryLocalResponse(getApplication(), text)
                    if (localReply != null) {
                        val npuLogs = com.omniagent.app.ai.OnDeviceAI.activityLog
                        val userMsg = UiMessage(role = "user", content = text)
                        // Show NPU thinking steps
                        val thinkingMsg = UiMessage(
                            role = "thinking",
                            content = "On-device NPU (${_state.value.onDeviceNPU})",
                            thinkingSteps = npuLogs,
                            thinkingElapsed = "0s",
                            isExpanded = false,
                        )
                        val aiMsg = UiMessage(role = "assistant", content = "$localReply\n\n*\u26A1 On-device (${_state.value.onDeviceNPU})*")
                        _state.update { s: ChatUiState -> s.copy(messages = s.messages + userMsg + thinkingMsg + aiMsg, inputText = "") }
                        generateSmartReplies(localReply)
                        return@launch
                    }
                } catch (_: Exception) {}
                // Not handled locally — send to server
                sendToServer(text, overrideModel)
            }
            return
        }
        sendToServer(text, overrideModel)
    }

    private fun sendToServer(text: String, overrideModel: String? = null) {
        // Proactively request location if the message looks location-dependent
        if (locationKeywords.containsMatchIn(text)) sendLocation()

        val userMsg = UiMessage(role = "user", content = text)
        _state.update { s: ChatUiState -> s.copy(messages = s.messages + userMsg, inputText = "", isSending = true) }

        viewModelScope.launch {
            // NPU preprocessing — rewrite, classify, and analyze before sending to server
            var processedText = text
            if (_state.value.onDeviceEnabled) {
                try {
                    val app = getApplication<android.app.Application>()
                    // Rewrite vague queries for clarity (Gemini Nano on NPU)
                    val rewritten = com.omniagent.app.ai.OnDeviceAI.rewriteQuery(text)
                    if (rewritten != text && rewritten.isNotBlank()) {
                        processedText = rewritten
                    }
                    // Classify intent + sentiment — prepend as hints for faster server routing
                    val intent = com.omniagent.app.ai.OnDeviceAI.classifyIntent(app, text)
                    val mood = com.omniagent.app.ai.OnDeviceAI.sentiment(text)
                    // Attach NPU analysis as metadata so server can skip redundant classification
                    processedText = "[npu:intent=$intent,mood=$mood] $processedText"
                } catch (_: Throwable) {}
            }

            try {
                // Stream the response token-by-token
                val streamingMsg = UiMessage(role = "assistant", content = "", isStreaming = true)
                _state.update { s: ChatUiState -> s.copy(messages = s.messages + streamingMsg) }
                var fullReply = ""

                var audioUrl: String? = null
                api.streamMessage(
                    message = processedText,
                    toolFlags = _state.value.toolToggles,
                    modelOverride = overrideModel ?: _state.value.modelOverride,
                ).collect { token: String ->
                    if (token.startsWith("__AUDIO__:")) {
                        audioUrl = token.removePrefix("__AUDIO__:")
                    } else {
                        fullReply += token
                        val msgs = _state.value.messages.toMutableList()
                        val lastIdx = msgs.lastIndex
                        if (lastIdx >= 0 && msgs[lastIdx].isStreaming) {
                            msgs[lastIdx] = msgs[lastIdx].copy(content = fullReply)
                            _state.update { s: ChatUiState -> s.copy(messages = msgs) }
                        }
                    }
                }
                // Finalize
                finalizeThinking()
                val msgs = _state.value.messages.toMutableList()
                val lastIdx = msgs.lastIndex
                if (lastIdx >= 0) {
                    msgs[lastIdx] = msgs[lastIdx].copy(content = fullReply, isStreaming = false)
                }
                _state.update { s: ChatUiState -> s.copy(messages = msgs, isSending = false) }
                audioUrl?.let { playAudio(it) }
                generateSmartReplies(fullReply)
                // Post-response NPU processing — summarize long replies on-device
                if (_state.value.onDeviceEnabled && fullReply.length > 500) {
                    viewModelScope.launch {
                        try {
                            val summary = com.omniagent.app.ai.OnDeviceAI.summarize(fullReply, 40)
                            if (summary.isNotBlank() && summary.length < fullReply.length) {
                                val msgs = _state.value.messages.toMutableList()
                                val lastIdx = msgs.lastIndex
                                if (lastIdx >= 0 && msgs[lastIdx].role == "assistant") {
                                    msgs[lastIdx] = msgs[lastIdx].copy(
                                        content = msgs[lastIdx].content + "\n\n**TL;DR (on-device):** $summary"
                                    )
                                    _state.update { s -> s.copy(messages = msgs) }
                                }
                            }
                        } catch (_: Throwable) {}
                    }
                }
            } catch (e: Exception) {
                // Fallback to non-streaming on error
                try {
                    val resp = api.sendMessage(
                        message = processedText,
                        toolFlags = _state.value.toolToggles,
                        modelOverride = overrideModel ?: _state.value.modelOverride,
                    )
                    val reply = resp.get("reply")?.asString ?: "No response"
                    finalizeThinking()
                    val msgs = _state.value.messages.toMutableList()
                    if (msgs.isNotEmpty() && msgs.last().isStreaming) msgs.removeAt(msgs.lastIndex)
                    msgs.add(UiMessage(role = "assistant", content = reply))
                    _state.update { s: ChatUiState -> s.copy(messages = msgs, isSending = false) }
                    resp.get("audio_url")?.asString?.let { playAudio(it) }
                } catch (e2: Exception) {
                    finalizeThinking()
                    val msgs = _state.value.messages.toMutableList()
                    if (msgs.isNotEmpty() && msgs.last().isStreaming) msgs.removeAt(msgs.lastIndex)
                    msgs.add(UiMessage(role = "assistant", content = "Error: ${e2.message}"))
                    _state.update { s: ChatUiState -> s.copy(messages = msgs, isSending = false) }
                }
            }
        }
    }

    fun resendMessage(text: String) {
        sendMessage(overrideText = text)
    }

    fun resendWithModel(text: String, model: String) {
        sendMessage(overrideText = text, overrideModel = model)
    }

    // --- Settings ---

    fun toggleSettings() { _state.update { it.copy(showSettings = !it.showSettings) } }

    fun loadSettings() {
        viewModelScope.launch {
            try {
                val settings = api.getSettings()
                _state.update {
                    it.copy(executionMode = settings.execution_mode, toolToggles = settings.enabled_tools,
                        modelOverride = settings.model_override, systemPrompt = settings.user_system_prompt,
                        experts = settings.experts)
                }
            } catch (_: Exception) {}
            try {
                val models = api.getModels().mapNotNull { it.get("name")?.asString ?: it.get("model")?.asString }
                _state.update { it.copy(installedModels = models) }
            } catch (_: Exception) {}
            // Fetch server version from single source of truth
            try {
                val ver = api.getVersion()
                if (ver.isNotBlank()) _state.update { it.copy(serverVersion = ver) }
            } catch (_: Exception) {}
        }
    }

    fun toggleMode() {
        val newMode = if (_state.value.executionMode == "execute") "teach" else "execute"
        _state.update { it.copy(executionMode = newMode) }
        viewModelScope.launch { try { api.setMode(newMode) } catch (_: Exception) {} }
    }

    fun toggleTool(tool: String) {
        val current = _state.value.toolToggles[tool] ?: true
        _state.update { it.copy(toolToggles = it.toolToggles + (tool to !current)) }
        viewModelScope.launch { try { api.toggleTool(tool, !current) } catch (_: Exception) {} }
    }

    fun setModelOverride(model: String) {
        _state.update { it.copy(modelOverride = model) }
        viewModelScope.launch { try { api.setModelOverride(model) } catch (_: Exception) {} }
    }

    fun saveSystemPrompt(prompt: String) {
        _state.update { it.copy(systemPrompt = prompt) }
        viewModelScope.launch { try { api.setSystemPrompt(prompt) } catch (_: Exception) {} }
    }

    fun clearSession() {
        viewModelScope.launch {
            try { api.clearSession(); _state.update { it.copy(messages = emptyList()) } } catch (_: Exception) {}
        }
    }

    fun exportChat(format: String) {
        viewModelScope.launch {
            try { api.exportChat(format) } catch (_: Exception) {}
        }
    }

    fun dismissError() { _state.update { it.copy(error = null) } }

    // --- Session History ---

    fun toggleSessionDrawer() {
        _state.update { it.copy(showSessionDrawer = !it.showSessionDrawer) }
        if (_state.value.showSessionDrawer) loadSessionList()
    }

    fun loadSessionList() {
        viewModelScope.launch {
            try {
                val sessions = api.listSessions()
                val list = sessions.map { s ->
                    val metrics = try { s.getAsJsonObject("metrics") } catch (_: Exception) { null }
                    fun jsonStr(el: com.google.gson.JsonElement?): String = try { el?.asString ?: el?.toString() ?: "" } catch (_: Exception) { el?.toString() ?: "" }
                    mapOf(
                        "id" to jsonStr(s.get("id")),
                        "title" to (jsonStr(s.get("title")).ifEmpty { "New Chat" }),
                        "last_active" to jsonStr(s.get("last_active")),
                        "message_count" to (jsonStr(s.get("message_count")).ifEmpty { "0" }),
                        "last_message" to jsonStr(s.get("last_message")),
                        "is_shared" to (jsonStr(s.get("is_shared")).ifEmpty { "0" }),
                        "tokens_in" to (jsonStr(metrics?.get("tokens_in")).ifEmpty { "0" }),
                        "tokens_out" to (jsonStr(metrics?.get("tokens_out")).ifEmpty { "0" }),
                    )
                }
                _state.update { it.copy(sessionList = list) }
            } catch (_: Exception) {}
        }
    }

    fun createNewChat() {
        viewModelScope.launch {
            try {
                val d = api.createNewSession()
                if (d.get("ok")?.asBoolean == true) {
                    val newSid = d.get("session_id")?.asString ?: return@launch
                    switchToSession(newSid)
                }
            } catch (_: Exception) {}
        }
    }

    fun switchToSession(targetSid: String) {
        viewModelScope.launch {
            try {
                val d = api.loadSession(targetSid)
                if (d.get("ok")?.asBoolean == true) {
                    api.sessionId = targetSid
                    prefs.edit().putString("session_id", targetSid).apply()
                    // Load messages
                    val msgs = mutableListOf<UiMessage>()
                    try {
                        val arr = d.getAsJsonArray("messages")
                        if (arr != null) {
                            for (i in 0 until arr.size()) {
                                val obj = arr.get(i).asJsonObject
                                msgs.add(UiMessage(
                                    role = obj.get("role")?.asString ?: "user",
                                    content = obj.get("content")?.asString ?: "",
                                ))
                            }
                        }
                    } catch (_: Exception) {}
                    _state.update { it.copy(messages = msgs, showSessionDrawer = false) }
                    startStatusStream()
                    loadSessionList()
                }
            } catch (_: Exception) {}
        }
    }

    fun deleteChat(targetSid: String) {
        viewModelScope.launch {
            try {
                api.deleteSession(targetSid)
                if (targetSid == api.sessionId) createNewChat()
                else loadSessionList()
            } catch (_: Exception) {}
        }
    }

    fun renameChat(targetSid: String, newTitle: String) {
        viewModelScope.launch {
            try {
                api.renameSession(targetSid, newTitle)
                loadSessionList()
            } catch (_: Exception) {}
        }
    }

    fun inviteToChat(username: String, targetSession: String? = null) {
        viewModelScope.launch {
            try { api.inviteCollaborator(targetSession ?: api.sessionId, username) } catch (_: Exception) {}
        }
    }

    fun archiveChat(targetSid: String) {
        viewModelScope.launch {
            try {
                api.archiveSession(targetSid)
                loadSessionList()
            } catch (_: Exception) {}
        }
    }

    fun unarchiveChat(targetSid: String) {
        viewModelScope.launch {
            try {
                api.unarchiveSession(targetSid)
                loadSessionList()
            } catch (_: Exception) {}
        }
    }

    fun shareChat(targetSid: String, context: android.content.Context) {
        viewModelScope.launch {
            try {
                api.shareSession(targetSid)
                // Offer Android share sheet with the session ID
                val intent = android.content.Intent(android.content.Intent.ACTION_SEND).apply {
                    type = "text/plain"
                    putExtra(android.content.Intent.EXTRA_TEXT, "Join my OmniAgent chat: $targetSid")
                }
                context.startActivity(android.content.Intent.createChooser(intent, "Share chat"))
                loadSessionList()
            } catch (_: Exception) {}
        }
    }

    fun exportSessionChat(targetSid: String, context: android.content.Context) {
        viewModelScope.launch {
            try {
                val content = api.exportSession(targetSid, "md")
                val intent = android.content.Intent(android.content.Intent.ACTION_SEND).apply {
                    type = "text/plain"
                    putExtra(android.content.Intent.EXTRA_TEXT, content)
                    putExtra(android.content.Intent.EXTRA_SUBJECT, "OmniAgent Chat Export")
                }
                context.startActivity(android.content.Intent.createChooser(intent, "Export chat"))
            } catch (_: Exception) {}
        }
    }

    // --- BitNet ---

    fun toggleBitNet() {
        val newState = !_state.value.bitnetEnabled
        _state.update { it.copy(bitnetEnabled = newState) }
        viewModelScope.launch {
            try { api.toggleBitNet(newState) } catch (_: Exception) {}
        }
    }

    fun loadBitNetState() {
        viewModelScope.launch {
            try {
                val d = api.getBitNetStatus()
                _state.update { it.copy(bitnetEnabled = d.get("enabled")?.asBoolean ?: false) }
            } catch (_: Exception) {}
        }
    }

    // --- Integrations ---

    fun loadIntegrations() {
        viewModelScope.launch {
            try {
                val data = api.getIntegrations(api.sessionId)
                val gh = data.getAsJsonObject("github")?.get("connected")?.asBoolean ?: false
                val gd = data.getAsJsonObject("google_drive")?.get("connected")?.asBoolean ?: false
                val ghUrl = data.getAsJsonObject("auth_urls")?.get("github")?.asString ?: ""
                val gdUrl = data.getAsJsonObject("auth_urls")?.get("google")?.asString ?: ""
                val ghOAuth = data.getAsJsonObject("oauth")?.get("github")?.asBoolean ?: false
                val gdOAuth = data.getAsJsonObject("oauth")?.get("google")?.asBoolean ?: false
                _state.update { it.copy(
                    githubConnected = gh, googleConnected = gd,
                    githubAuthUrl = ghUrl, googleAuthUrl = gdUrl,
                    githubOAuth = ghOAuth, googleOAuth = gdOAuth,
                ) }
            } catch (_: Exception) {}
        }
    }

    fun oauthConnect(service: String, context: android.content.Context) {
        var url = if (service == "github") _state.value.githubAuthUrl else _state.value.googleAuthUrl
        // Fallback to manual token page if OAuth not configured
        if (url.isBlank()) {
            url = if (service == "github")
                "https://github.com/settings/tokens/new?scopes=repo,gist,read:user&description=OmniAgent"
            else
                "https://developers.google.com/oauthplayground/"
        }
        try {
            val customTabsIntent = androidx.browser.customtabs.CustomTabsIntent.Builder()
                .setShowTitle(true)
                .build()
            customTabsIntent.launchUrl(context, android.net.Uri.parse(url))
        } catch (_: Exception) {
            // Fallback to regular browser
            context.startActivity(android.content.Intent(android.content.Intent.ACTION_VIEW, android.net.Uri.parse(url)))
        }
    }

    fun connectIntegration(service: String, token: String) {
        viewModelScope.launch {
            try {
                val result = api.connectIntegration(service, token)
                if (result.get("ok")?.asBoolean == true) {
                    if (service == "github") _state.update { it.copy(githubConnected = true) }
                    else _state.update { it.copy(googleConnected = true) }
                }
            } catch (_: Exception) {}
        }
    }

    fun saveChatToService(service: String) {
        viewModelScope.launch {
            try { api.saveChatToService(service) } catch (_: Exception) {}
        }
    }

    // --- Memory ---

    fun loadMemories() {
        viewModelScope.launch {
            try {
                val memories = api.getMemories()
                val list = memories.map { m ->
                    mapOf(
                        "category" to (m.get("category")?.asString ?: ""),
                        "key" to (m.get("key")?.asString ?: ""),
                        "value" to (m.get("value")?.asString ?: ""),
                    )
                }
                _state.update { s: ChatUiState -> s.copy(memories = list) }
            } catch (_: Exception) {}
        }
    }

    fun forgetMemory(category: String, key: String) {
        viewModelScope.launch {
            try {
                api.forgetMemory(category, key)
                loadMemories()
            } catch (_: Exception) {}
        }
    }

    // --- Plugins ---

    fun loadPlugins() {
        if (!_state.value.isAdmin) {
            _state.update { s: ChatUiState -> s.copy(plugins = emptyList(), pluginsError = "Plugin management is available to server admins only.") }
            return
        }
        viewModelScope.launch {
            try {
                val plugins = api.getPlugins()
                val list = plugins.map { p ->
                    mapOf(
                        "name" to (p.get("name")?.asString ?: ""),
                        "description" to (p.get("description")?.asString ?: ""),
                    )
                }
                _state.update { s: ChatUiState -> s.copy(plugins = list, pluginsError = null) }
            } catch (e: Exception) {
                _state.update { s: ChatUiState -> s.copy(plugins = emptyList(), pluginsError = e.message ?: "Failed to load plugins") }
            }
        }
    }

    fun reloadPlugins() {
        if (!_state.value.isAdmin) {
            _state.update { s: ChatUiState -> s.copy(pluginsError = "Plugin management is available to server admins only.") }
            return
        }
        viewModelScope.launch {
            try {
                api.reloadPlugins()
                loadPlugins()
            } catch (e: Exception) {
                _state.update { s: ChatUiState -> s.copy(pluginsError = e.message ?: "Failed to reload plugins") }
            }
        }
    }

    // --- File Upload ---

    fun uploadFile(filename: String, bytes: ByteArray, onResult: (String) -> Unit) {
        viewModelScope.launch {
            try {
                val d = api.uploadFile(filename, bytes)
                val path = d.get("path")?.asString ?: ""
                if (path.isNotEmpty()) {
                    _state.update { s: ChatUiState -> s.copy(inputText = s.inputText + (if (s.inputText.isEmpty()) "" else " ") + path) }
                    onResult("Uploaded: $filename")
                } else {
                    onResult(d.get("error")?.asString ?: "Upload failed")
                }
            } catch (e: Exception) {
                onResult("Error: ${e.message}")
            }
        }
    }

    // --- Message Ratings ---

    fun rateMessage(messageIndex: Int, rating: String) {
        viewModelScope.launch {
            try { api.rateMessage(messageIndex, rating) } catch (_: Exception) {}
        }
    }

    // --- Conversation Search ---

    fun searchMessages(query: String) {
        viewModelScope.launch {
            try {
                val d = api.searchChat(query)
                val results = mutableListOf<Map<String, String>>()
                try {
                    val arr = d.getAsJsonArray("results")
                    if (arr != null) {
                        for (i in 0 until arr.size()) {
                            val obj = arr.get(i).asJsonObject
                            results.add(mapOf(
                                "index" to (obj.get("index")?.asString ?: "0"),
                                "role" to (obj.get("role")?.asString ?: ""),
                                "content" to (obj.get("content")?.asString ?: ""),
                            ))
                        }
                    }
                } catch (_: Exception) {}
                _state.update { s: ChatUiState -> s.copy(searchResults = results) }
            } catch (_: Exception) {}
        }
    }

    fun clearSearch() {
        _state.update { s: ChatUiState -> s.copy(searchResults = emptyList(), showSearch = false) }
    }

    fun toggleSearch() {
        _state.update { s: ChatUiState -> s.copy(showSearch = !s.showSearch, searchResults = emptyList()) }
    }

    // --- Audio Playback ---

    private fun playAudio(relativeUrl: String) {
        try {
            val fullUrl = "${api.baseUrl}$relativeUrl"
            val player = android.media.MediaPlayer()
            player.setDataSource(fullUrl)
            player.setOnPreparedListener { it.start() }
            player.setOnCompletionListener { it.release() }
            player.prepareAsync()
        } catch (_: Exception) {}
    }

    // --- Location ---

    @android.annotation.SuppressLint("MissingPermission")
    fun sendLocation() {
        val app = getApplication<Application>()
        val hasFine = androidx.core.content.ContextCompat.checkSelfPermission(
            app, android.Manifest.permission.ACCESS_FINE_LOCATION
        ) == android.content.pm.PackageManager.PERMISSION_GRANTED
        val hasCoarse = androidx.core.content.ContextCompat.checkSelfPermission(
            app, android.Manifest.permission.ACCESS_COARSE_LOCATION
        ) == android.content.pm.PackageManager.PERMISSION_GRANTED
        if (!hasFine && !hasCoarse) return
        val lm = app.getSystemService(android.content.Context.LOCATION_SERVICE) as android.location.LocationManager
        val loc = lm.getLastKnownLocation(android.location.LocationManager.GPS_PROVIDER)
            ?: lm.getLastKnownLocation(android.location.LocationManager.NETWORK_PROVIDER)
            ?: lm.getLastKnownLocation(android.location.LocationManager.PASSIVE_PROVIDER)
        if (loc != null) {
            viewModelScope.launch {
                try { api.setLocation(loc.latitude, loc.longitude) } catch (_: Exception) {}
            }
        }
    }

    // --- On-Device AI ---

    private fun generateSmartReplies(lastReply: String) {
        if (!_state.value.onDeviceEnabled) return
        viewModelScope.launch {
            try {
                val replies = com.omniagent.app.ai.OnDeviceAI.smartReplies(getApplication(), lastReply)
                _state.update { s -> s.copy(smartReplies = replies) }
            } catch (_: Exception) {}
        }
    }

    fun toggleOnDeviceAI() {
        _state.update { s -> s.copy(onDeviceEnabled = !s.onDeviceEnabled, smartReplies = emptyList()) }
    }

    fun useSuggestion(text: String) {
        sendMessage(overrideText = text)
        _state.update { s -> s.copy(smartReplies = emptyList()) }
    }

    // --- Large Model Routing ---

    fun toggleLargeModel() {
        val newVal = !_state.value.largeModelRouting
        _state.update { s -> s.copy(largeModelRouting = newVal) }
        viewModelScope.launch {
            try { api.setLargeModelRouting(newVal) } catch (_: Exception) {}
        }
    }

    // --- OAuth Config ---

    fun saveOAuthConfig(service: String, clientId: String, clientSecret: String) {
        viewModelScope.launch {
            try {
                api.saveOAuthConfig(service, clientId, clientSecret)
                loadIntegrations() // Refresh to pick up new OAuth URLs
            } catch (_: Exception) {}
        }
    }

    // --- Theme Toggle ---

    fun toggleTheme() {
        com.omniagent.app.ui.theme.isDarkTheme = !com.omniagent.app.ui.theme.isDarkTheme
    }

    // --- Global Search ---

    fun globalSearch(query: String) {
        viewModelScope.launch {
            try {
                val r = okhttp3.Request.Builder()
                    .url("${api.baseUrl}/api/search/global?q=${java.net.URLEncoder.encode(query, "UTF-8")}&session_id=${api.sessionId}")
                    .build()
                val resp = okhttp3.OkHttpClient().newCall(r).execute()
                val body = resp.body?.string() ?: "{}"
                val obj = com.google.gson.Gson().fromJson(body, com.google.gson.JsonObject::class.java)
                val arr = obj.getAsJsonArray("results")
                val results = mutableListOf<Map<String, String>>()
                if (arr != null) {
                    for (i in 0 until arr.size()) {
                        val item = arr.get(i).asJsonObject
                        results.add(mapOf(
                            "session_id" to (item.get("session_id")?.asString ?: ""),
                            "role" to (item.get("role")?.asString ?: ""),
                            "content" to (item.get("content")?.asString ?: ""),
                            "session_title" to (item.get("session_title")?.asString ?: ""),
                        ))
                    }
                }
                _state.update { s -> s.copy(searchResults = results) }
            } catch (_: Exception) {}
        }
    }

    // --- Pin Message ---

    fun pinMessage(messageIndex: Int, content: String, role: String = "assistant") {
        viewModelScope.launch {
            try {
                api.pinMessage(api.sessionId, messageIndex, content, role)
                android.widget.Toast.makeText(getApplication(), "Message pinned", android.widget.Toast.LENGTH_SHORT).show()
            } catch (_: Exception) {}
        }
    }

    // --- Conversation Tree ---

    fun loadConversationTree() {
        viewModelScope.launch {
            try {
                val r = okhttp3.Request.Builder()
                    .url("${api.baseUrl}/api/chat/tree/${api.sessionId}")
                    .build()
                val resp = okhttp3.OkHttpClient().newCall(r).execute()
                val body = resp.body?.string() ?: "{}"
                val obj = com.google.gson.Gson().fromJson(body, com.google.gson.JsonObject::class.java)
                val nodes = obj.getAsJsonArray("nodes")
                val lines = mutableListOf<String>()
                if (nodes != null) {
                    for (i in 0 until nodes.size()) {
                        val n = nodes.get(i).asJsonObject
                        val role = n.get("role")?.asString ?: "?"
                        val preview = n.get("preview")?.asString ?: ""
                        val indent = if (role == "assistant") "  " else ""
                        val icon = if (role == "user") "\u25B8" else "\u25C2"
                        lines.add("$indent$icon [$role] $preview")
                    }
                }
                _state.update { s -> s.copy(reasoningHistory = lines, showReasoningHistory = true) }
            } catch (_: Exception) {}
        }
    }

    // --- Task History ---

    fun loadTaskHistory() {
        viewModelScope.launch {
            try {
                val r = okhttp3.Request.Builder().url("${api.baseUrl}/api/tasks/list?session_id=${api.sessionId}").build()
                val resp = okhttp3.OkHttpClient.Builder().build().newCall(r).execute()
                val body = resp.body?.string() ?: "{}"
                val obj = com.google.gson.Gson().fromJson(body, com.google.gson.JsonObject::class.java)
                val tasks = obj.getAsJsonArray("tasks")
                val lines = mutableListOf<String>()
                if (tasks != null && tasks.size() > 0) {
                    for (i in 0 until tasks.size()) {
                        val t = tasks.get(i).asJsonObject
                        val title = t.get("title")?.asString ?: "Untitled"
                        val status = t.get("status")?.asString ?: "?"
                        val phase = t.get("current_phase")?.asInt ?: 0
                        val total = t.get("total_phases")?.asInt ?: 0
                        val created = t.get("created_at")?.asString ?: ""
                        lines.add("[$status] $title — Phase $phase/$total ($created)")
                    }
                } else {
                    lines.add("No tasks yet. Complex requests are automatically broken into multi-phase tasks.")
                }
                _state.update { s -> s.copy(reasoningHistory = lines, showReasoningHistory = true) }
            } catch (_: Exception) {}
        }
    }

    // --- Reasoning History ---

    fun loadReasoningHistory() {
        viewModelScope.launch {
            try {
                val entries = api.getReasoningHistory(api.sessionId)
                // Also prepend any local NPU logs
                val npuLogs = try { com.omniagent.app.ai.OnDeviceAI.activityLog } catch (_: Throwable) { emptyList() }
                val all = npuLogs + entries
                _state.update { s -> s.copy(reasoningHistory = all, showReasoningHistory = true) }
            } catch (_: Exception) {}
        }
    }

    fun dismissReasoningHistory() {
        _state.update { s -> s.copy(showReasoningHistory = false) }
    }

    // --- Changelog ---

    fun loadChangelog() {
        viewModelScope.launch {
            try {
                val content = api.getChangelog()
                _state.update { s -> s.copy(changelogContent = content, showChangelog = true) }
            } catch (_: Exception) {}
        }
    }

    fun dismissChangelog() {
        _state.update { s -> s.copy(showChangelog = false) }
    }

    // --- Presets & Templates ---

    fun loadPresets() {
        viewModelScope.launch {
            try {
                val d = api.getPresets()
                val presets = mutableMapOf<String, String>()
                val obj = d.getAsJsonObject("presets")
                if (obj != null) {
                    for (entry in obj.entrySet()) {
                        presets[entry.key] = entry.value.asString
                    }
                }
                _state.update { s -> s.copy(presets = presets) }
            } catch (_: Exception) {}
        }
    }

    fun loadTemplates() {
        viewModelScope.launch {
            try {
                val d = api.getTemplates()
                val templates = mutableMapOf<String, String>()
                val obj = d.getAsJsonObject("templates")
                if (obj != null) {
                    for (entry in obj.entrySet()) {
                        val title = try { entry.value.asJsonObject.get("title")?.asString ?: entry.key } catch (_: Exception) { entry.key }
                        val message = try { entry.value.asJsonObject.get("message")?.asString ?: "" } catch (_: Exception) { "" }
                        templates[title] = message
                    }
                }
                _state.update { s -> s.copy(templates = templates) }
            } catch (_: Exception) {}
        }
    }

    fun applyPreset(preset: String) {
        viewModelScope.launch {
            try {
                val d = api.applyPreset(preset)
                val prompt = d.get("prompt")?.asString ?: ""
                _state.update { s -> s.copy(systemPrompt = prompt) }
            } catch (_: Exception) {}
        }
    }

    fun useTemplate(message: String) {
        _state.update { s -> s.copy(inputText = message) }
    }

    // --- Conversation Branching ---

    fun branchConversation(fromIndex: Int, newMessage: String) {
        viewModelScope.launch {
            try {
                api.branchChat(fromIndex, newMessage)
                loadCurrentChat()
            } catch (_: Exception) {}
        }
    }
}
