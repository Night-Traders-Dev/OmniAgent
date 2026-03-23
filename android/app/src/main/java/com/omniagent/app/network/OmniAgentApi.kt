package com.omniagent.app.network

import com.google.gson.Gson
import com.google.gson.JsonObject
import com.google.gson.reflect.TypeToken
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.withContext
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.sse.EventSource
import okhttp3.sse.EventSourceListener
import okhttp3.sse.EventSources
import java.io.BufferedReader
import java.util.concurrent.TimeUnit

data class ChatMessage(val role: String, val content: String)
data class ServerSettings(
    val experts: Map<String, String>,
    val enabled_tools: Map<String, Boolean>,
    val model_override: String,
    val execution_mode: String,
    val user_system_prompt: String,
    val session_messages: Int,
    val commands_run: Int,
)
data class StreamEvent(
    val status: String = "",
    val gpu: String = "",
    val log: String? = null,
    val task_started_at: String? = null,
    val current_step: String = "",
    val step_index: Int = 0,
    val total_steps: Int = 0,
    val active_model: String = "",
    val active_agents: List<String> = emptyList(),
    val tasks_completed: Int = 0,
    val total_llm_calls: Int = 0,
    val session_messages: Int = 0,
    val commands_run: Int = 0,
    val tokens_in: Int = 0,
    val tokens_out: Int = 0,
    val gpu_workers: Int = 0,
)
data class AgentInfo(val name: String, val role: String, val model_key: String, val model: String, val has_tools: Boolean, val max_steps: Int)

class OmniAgentApi(var baseUrl: String = "") {

    private val client = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()

    private val sseClient = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.SECONDS) // SSE: no timeout
        .build()

    private val gson = Gson()
    private val json = "application/json".toMediaType()

    var sessionId: String = java.util.UUID.randomUUID().toString().replace("-", "")

    fun setServer(ip: String, port: Int = 8000) {
        baseUrl = "http://$ip:$port"
    }

    fun setServerUrl(url: String) {
        baseUrl = url.trimEnd('/')
    }

    /**
     * Resolve a pairing code to a tunnel URL via ntfy.sh.
     * This works from ANYWHERE — no LAN needed.
     */
    suspend fun resolvePairingCode(code: String): String? = withContext(Dispatchers.IO) {
        try {
            val topic = "omniagent-$code"
            val request = Request.Builder()
                .url("https://ntfy.sh/$topic/json?poll=1&since=2h")
                .header("Accept", "application/json")
                .build()
            val response = client.newCall(request).execute()
            val body = response.body?.string() ?: return@withContext null
            // Parse newline-delimited JSON, get last URL message
            val lines = body.trim().split("\n")
            for (line in lines.reversed()) {
                if (line.isBlank()) continue
                try {
                    val msg = gson.fromJson(line, JsonObject::class.java)
                    val message = msg.get("message")?.asString ?: continue
                    if ((message as CharSequence).startsWith("https://")) return@withContext message
                } catch (_: Exception) {}
            }
            null
        } catch (_: Exception) { null }
    }

    // --- Chat ---

    suspend fun sendMessage(
        message: String,
        toolFlags: Map<String, Boolean>? = null,
        modelOverride: String? = null,
    ): JsonObject = withContext(Dispatchers.IO) {
        val body = JsonObject().apply {
            addProperty("message", message)
            addProperty("session_id", sessionId)
            toolFlags?.let {
                val flags = JsonObject()
                it.forEach { (k, v) -> flags.addProperty(k, v) }
                add("tool_flags", flags)
            }
            modelOverride?.let { addProperty("model_override", it) }
        }
        val request = Request.Builder()
            .url("$baseUrl/chat")
            .post(gson.toJson(body).toRequestBody(json))
            .build()
        val response = client.newCall(request).execute()
        val respBody = response.body?.string() ?: "{}"
        gson.fromJson(respBody, JsonObject::class.java)
    }

    fun streamMessage(
        message: String,
        toolFlags: Map<String, Boolean>? = null,
        modelOverride: String? = null,
    ): Flow<String> = callbackFlow {
        val body = JsonObject().apply {
            addProperty("message", message)
            addProperty("session_id", sessionId)
            toolFlags?.let {
                val flags = JsonObject()
                it.forEach { (k, v) -> flags.addProperty(k, v) }
                add("tool_flags", flags)
            }
            modelOverride?.let { addProperty("model_override", it) }
        }
        val request = Request.Builder()
            .url("$baseUrl/chat/stream")
            .post(gson.toJson(body).toRequestBody(json))
            .build()

        val call = sseClient.newCall(request)
        val thread = Thread {
            try {
                val response = call.execute()
                val reader = response.body?.source()?.inputStream()?.bufferedReader()
                    ?: return@Thread
                reader.forEachLine { line ->
                    if (line.startsWith("data: ")) {
                        try {
                            val data = gson.fromJson(line.substring(6), JsonObject::class.java)
                            val token = data.get("token")?.asString
                            val audioUrl = data.get("audio_url")?.asString
                            val done = data.get("done")?.asBoolean ?: false
                            if (token != null) trySend(token)
                            if (audioUrl != null) trySend("__AUDIO__:$audioUrl")
                            if (done) close()
                        } catch (_: Exception) {}
                    }
                }
                close()
            } catch (e: Exception) {
                close(e)
            }
        }
        thread.start()
        awaitClose { call.cancel() }
    }

    // --- Status Stream (SSE) ---

    fun streamStatus(): Flow<StreamEvent> = callbackFlow {
        val url = "$baseUrl/stream?session_id=$sessionId"
        android.util.Log.i("OmniSSE", "Connecting: $url")
        val request = Request.Builder().url(url).build()
        val call = sseClient.newCall(request)
        val thread = Thread {
            try {
                val response = call.execute()
                android.util.Log.i("OmniSSE", "HTTP ${response.code}")
                if (!response.isSuccessful) {
                    close(Exception("SSE HTTP ${response.code}"))
                    return@Thread
                }
                // Read byte-by-byte to handle tunnel buffering
                // Cloudflare tunnels can hold chunks — we need to read as bytes arrive
                val stream = response.body?.byteStream()
                    ?: run { close(Exception("SSE: no body")); return@Thread }
                val buf = StringBuilder()
                var eventCount = 0
                var b: Int
                while (stream.read().also { b = it } != -1) {
                    val ch = b.toChar()
                    if (ch == '\n') {
                        val line = buf.toString()
                        buf.clear()
                        if (line.startsWith("data: ")) {
                            try {
                                val event = gson.fromJson(line.substring(6), StreamEvent::class.java)
                                trySend(event)
                                eventCount++
                                if (eventCount <= 2) android.util.Log.d("OmniSSE", "Event #$eventCount gpu=${event.gpu} tasks=${event.tasks_completed}")
                            } catch (_: Exception) {}
                        }
                        // Skip empty lines and ": keepalive" comments
                    } else {
                        buf.append(ch)
                    }
                }
                android.util.Log.i("OmniSSE", "Stream closed after $eventCount events")
                close()
            } catch (e: Exception) {
                android.util.Log.e("OmniSSE", "Error: ${e.javaClass.simpleName}: ${e.message}")
                close(e)
            }
        }
        thread.start()
        awaitClose { call.cancel() }
    }

    // --- Status Polling (fallback when SSE is blocked by tunnels) ---

    suspend fun pollStatus(): StreamEvent? = withContext(Dispatchers.IO) {
        try {
            val request = Request.Builder().url("$baseUrl/api/metrics?session_id=$sessionId").build()
            val response = client.newCall(request).execute()
            val body = response.body?.string() ?: return@withContext null
            gson.fromJson(body, StreamEvent::class.java)
        } catch (_: Exception) { null }
    }

    // --- Settings ---

    suspend fun getSettings(): ServerSettings = withContext(Dispatchers.IO) {
        val request = Request.Builder().url("$baseUrl/api/settings").build()
        val response = client.newCall(request).execute()
        gson.fromJson(response.body?.string(), ServerSettings::class.java)
    }

    suspend fun updateModels(models: Map<String, String>) = withContext(Dispatchers.IO) {
        val body = gson.toJson(models).toRequestBody(json)
        val request = Request.Builder().url("$baseUrl/api/settings").post(body).build()
        client.newCall(request).execute()
    }

    suspend fun setMode(mode: String) = withContext(Dispatchers.IO) {
        val body = """{"mode":"$mode"}""".toRequestBody(json)
        val request = Request.Builder().url("$baseUrl/api/mode").post(body).build()
        client.newCall(request).execute()
    }

    suspend fun setSystemPrompt(prompt: String) = withContext(Dispatchers.IO) {
        val body = """{"prompt":${gson.toJson(prompt)}}""".toRequestBody(json)
        val request = Request.Builder().url("$baseUrl/api/system-prompt").post(body).build()
        client.newCall(request).execute()
    }

    suspend fun toggleTool(tool: String, enabled: Boolean) = withContext(Dispatchers.IO) {
        val body = """{"tool":"$tool","enabled":$enabled}""".toRequestBody(json)
        val request = Request.Builder().url("$baseUrl/api/tools/toggle").post(body).build()
        client.newCall(request).execute()
    }

    suspend fun setModelOverride(model: String) = withContext(Dispatchers.IO) {
        val body = """{"model":"$model"}""".toRequestBody(json)
        val request = Request.Builder().url("$baseUrl/api/model-override").post(body).build()
        client.newCall(request).execute()
    }

    // --- Models ---

    suspend fun getModels(): List<JsonObject> = withContext(Dispatchers.IO) {
        val request = Request.Builder().url("$baseUrl/api/models").build()
        val response = client.newCall(request).execute()
        val parsed = gson.fromJson(response.body?.string(), JsonObject::class.java)
        val type = object : TypeToken<List<JsonObject>>() {}.type
        gson.fromJson(parsed.getAsJsonArray("models"), type) ?: emptyList()
    }

    suspend fun getAgents(): List<AgentInfo> = withContext(Dispatchers.IO) {
        val request = Request.Builder().url("$baseUrl/api/agents").build()
        val response = client.newCall(request).execute()
        val parsed = gson.fromJson(response.body?.string(), JsonObject::class.java)
        val type = object : TypeToken<List<AgentInfo>>() {}.type
        gson.fromJson(parsed.getAsJsonArray("agents"), type) ?: emptyList()
    }

    // --- Auth ---

    private fun safeParseJson(raw: String?): JsonObject {
        if (raw.isNullOrBlank()) return JsonObject().apply { addProperty("error", "Empty response") }
        return try {
            val el = gson.fromJson(raw, com.google.gson.JsonElement::class.java)
            if (el.isJsonObject) el.asJsonObject
            else JsonObject().apply { addProperty("error", raw) }
        } catch (_: Exception) {
            JsonObject().apply { addProperty("error", raw) }
        }
    }

    suspend fun login(username: String, password: String): JsonObject = withContext(Dispatchers.IO) {
        val body = """{"username":${gson.toJson(username)},"password":${gson.toJson(password)}}""".toRequestBody(json)
        val request = Request.Builder().url("$baseUrl/api/auth/login").post(body).build()
        val response = client.newCall(request).execute()
        safeParseJson(response.body?.string())
    }

    suspend fun register(username: String, password: String): JsonObject = withContext(Dispatchers.IO) {
        val body = """{"username":${gson.toJson(username)},"password":${gson.toJson(password)}}""".toRequestBody(json)
        val request = Request.Builder().url("$baseUrl/api/auth/register").post(body).build()
        val response = client.newCall(request).execute()
        safeParseJson(response.body?.string())
    }

    suspend fun checkAuth(): JsonObject = withContext(Dispatchers.IO) {
        val request = Request.Builder().url("$baseUrl/api/auth/user?session_id=$sessionId").build()
        val response = client.newCall(request).execute()
        safeParseJson(response.body?.string())
    }

    // --- Session Management ---

    suspend fun clearSession() = withContext(Dispatchers.IO) {
        val request = Request.Builder().url("$baseUrl/api/clear-session")
            .post("".toRequestBody(json)).build()
        client.newCall(request).execute()
    }

    suspend fun exportChat(format: String): String = withContext(Dispatchers.IO) {
        val request = Request.Builder().url("$baseUrl/api/export/$format").build()
        client.newCall(request).execute().body?.string() ?: ""
    }

    suspend fun listSessions(): List<JsonObject> = withContext(Dispatchers.IO) {
        val request = Request.Builder().url("$baseUrl/api/auth/sessions?session_id=$sessionId").build()
        val response = client.newCall(request).execute()
        val parsed = safeParseJson(response.body?.string())
        val type = object : TypeToken<List<JsonObject>>() {}.type
        try { gson.fromJson(parsed.getAsJsonArray("sessions"), type) ?: emptyList() }
        catch (_: Exception) { emptyList() }
    }

    suspend fun createNewSession(title: String = "New Chat"): JsonObject = withContext(Dispatchers.IO) {
        val body = """{"session_id":"$sessionId","title":${gson.toJson(title)}}""".toRequestBody(json)
        val request = Request.Builder().url("$baseUrl/api/auth/sessions/new").post(body).build()
        safeParseJson(client.newCall(request).execute().body?.string())
    }

    suspend fun loadSession(targetSession: String): JsonObject = withContext(Dispatchers.IO) {
        val body = """{"session_id":"$sessionId","target_session":"$targetSession"}""".toRequestBody(json)
        val request = Request.Builder().url("$baseUrl/api/auth/sessions/load").post(body).build()
        safeParseJson(client.newCall(request).execute().body?.string())
    }

    suspend fun renameSession(targetSession: String, title: String) = withContext(Dispatchers.IO) {
        val body = """{"session_id":"$sessionId","target_session":"$targetSession","title":${gson.toJson(title)}}""".toRequestBody(json)
        val request = Request.Builder().url("$baseUrl/api/auth/sessions/rename").post(body).build()
        client.newCall(request).execute()
    }

    suspend fun deleteSession(targetSession: String) = withContext(Dispatchers.IO) {
        val body = """{"session_id":"$sessionId","target_session":"$targetSession"}""".toRequestBody(json)
        val request = Request.Builder().url("$baseUrl/api/auth/sessions/delete").post(body).build()
        client.newCall(request).execute()
    }

    suspend fun inviteCollaborator(targetSession: String, username: String): JsonObject = withContext(Dispatchers.IO) {
        val body = """{"session_id":"$sessionId","target_session":"$targetSession","username":${gson.toJson(username)}}""".toRequestBody(json)
        val request = Request.Builder().url("$baseUrl/api/collab/invite").post(body).build()
        safeParseJson(client.newCall(request).execute().body?.string())
    }

    suspend fun shareSession(targetSession: String): JsonObject = withContext(Dispatchers.IO) {
        val body = """{"session_id":"$sessionId","target_session":"$targetSession"}""".toRequestBody(json)
        val request = Request.Builder().url("$baseUrl/api/collab/share").post(body).build()
        safeParseJson(client.newCall(request).execute().body?.string())
    }

    suspend fun archiveSession(targetSession: String) = withContext(Dispatchers.IO) {
        val body = """{"session_id":"$sessionId","target_session":"$targetSession"}""".toRequestBody(json)
        val request = Request.Builder().url("$baseUrl/api/auth/sessions/archive").post(body).build()
        client.newCall(request).execute()
    }

    suspend fun unarchiveSession(targetSession: String) = withContext(Dispatchers.IO) {
        val body = """{"session_id":"$sessionId","target_session":"$targetSession"}""".toRequestBody(json)
        val request = Request.Builder().url("$baseUrl/api/auth/sessions/unarchive").post(body).build()
        client.newCall(request).execute()
    }

    suspend fun getArchivedSessions(): List<JsonObject> = withContext(Dispatchers.IO) {
        val request = Request.Builder().url("$baseUrl/api/auth/sessions/archived?session_id=$sessionId").build()
        val response = client.newCall(request).execute()
        val parsed = safeParseJson(response.body?.string())
        val type = object : TypeToken<List<JsonObject>>() {}.type
        try { gson.fromJson(parsed.getAsJsonArray("sessions"), type) ?: emptyList() }
        catch (_: Exception) { emptyList() }
    }

    suspend fun exportSession(targetSession: String, format: String = "md"): String = withContext(Dispatchers.IO) {
        val request = Request.Builder().url("$baseUrl/api/export/$format?session_id=$targetSession").build()
        client.newCall(request).execute().body?.string() ?: ""
    }

    suspend fun toggleBitNet(enabled: Boolean) = withContext(Dispatchers.IO) {
        val body = """{"enabled":$enabled}""".toRequestBody(json)
        val request = Request.Builder().url("$baseUrl/api/bitnet").post(body).build()
        client.newCall(request).execute()
    }

    suspend fun getBitNetStatus(): JsonObject = withContext(Dispatchers.IO) {
        val request = Request.Builder().url("$baseUrl/api/bitnet").build()
        safeParseJson(client.newCall(request).execute().body?.string())
    }

    // --- Integrations ---

    suspend fun getIntegrations(sid: String = ""): JsonObject = withContext(Dispatchers.IO) {
        val s = sid.ifEmpty { sessionId }
        val request = Request.Builder().url("$baseUrl/api/integrations?session_id=$s").build()
        val response = client.newCall(request).execute()
        gson.fromJson(response.body?.string(), JsonObject::class.java)
    }

    suspend fun connectIntegration(service: String, token: String): JsonObject = withContext(Dispatchers.IO) {
        val body = """{"service":"$service","token":${gson.toJson(token)}}""".toRequestBody(json)
        val request = Request.Builder().url("$baseUrl/api/integrations/connect").post(body).build()
        val response = client.newCall(request).execute()
        gson.fromJson(response.body?.string(), JsonObject::class.java)
    }

    suspend fun saveChatToService(service: String, title: String = "OmniAgent Chat Export"): JsonObject = withContext(Dispatchers.IO) {
        val body = """{"service":"$service","title":${gson.toJson(title)}}""".toRequestBody(json)
        val request = Request.Builder().url("$baseUrl/api/integrations/save-chat").post(body).build()
        val response = client.newCall(request).execute()
        gson.fromJson(response.body?.string(), JsonObject::class.java)
    }

    // --- Memory ---

    suspend fun getMemories(): List<JsonObject> = withContext(Dispatchers.IO) {
        val request = Request.Builder().url("$baseUrl/api/memory?session_id=$sessionId").build()
        val response = client.newCall(request).execute()
        val parsed = safeParseJson(response.body?.string())
        val type = object : TypeToken<List<JsonObject>>() {}.type
        try { gson.fromJson(parsed.getAsJsonArray("memories"), type) ?: emptyList() }
        catch (_: Exception) { emptyList() }
    }

    suspend fun forgetMemory(category: String, key: String) = withContext(Dispatchers.IO) {
        val body = """{"session_id":"$sessionId","category":${gson.toJson(category)},"key":${gson.toJson(key)}}""".toRequestBody(json)
        val request = Request.Builder().url("$baseUrl/api/memory/forget").post(body).build()
        client.newCall(request).execute()
    }

    // --- Plugins ---

    suspend fun getPlugins(): List<JsonObject> = withContext(Dispatchers.IO) {
        val request = Request.Builder().url("$baseUrl/api/plugins").build()
        val response = client.newCall(request).execute()
        val parsed = safeParseJson(response.body?.string())
        val type = object : TypeToken<List<JsonObject>>() {}.type
        try { gson.fromJson(parsed.getAsJsonArray("plugins"), type) ?: emptyList() }
        catch (_: Exception) { emptyList() }
    }

    suspend fun reloadPlugins(): JsonObject = withContext(Dispatchers.IO) {
        val request = Request.Builder().url("$baseUrl/api/plugins/reload")
            .post("".toRequestBody(json)).build()
        safeParseJson(client.newCall(request).execute().body?.string())
    }

    // --- Vision ---

    suspend fun analyzeImage(imagePath: String, prompt: String = "Describe this image in detail."): JsonObject = withContext(Dispatchers.IO) {
        val body = """{"image_path":${gson.toJson(imagePath)},"prompt":${gson.toJson(prompt)}}""".toRequestBody(json)
        val request = Request.Builder().url("$baseUrl/api/vision/analyze").post(body).build()
        safeParseJson(client.newCall(request).execute().body?.string())
    }

    // --- Image Generation ---

    suspend fun generateImage(prompt: String, negPrompt: String = "", width: Int = 512, height: Int = 512): JsonObject = withContext(Dispatchers.IO) {
        val body = """{"prompt":${gson.toJson(prompt)},"negative_prompt":${gson.toJson(negPrompt)},"width":$width,"height":$height}""".toRequestBody(json)
        val request = Request.Builder().url("$baseUrl/api/image/generate").post(body).build()
        safeParseJson(client.newCall(request).execute().body?.string())
    }

    // --- Voice ---

    suspend fun transcribeAudio(audioBytes: ByteArray, filename: String = "recording.webm"): JsonObject = withContext(Dispatchers.IO) {
        val fileBody = audioBytes.toRequestBody("audio/webm".toMediaType())
        val multipart = MultipartBody.Builder()
            .setType(MultipartBody.FORM)
            .addFormDataPart("file", filename, fileBody)
            .build()
        val request = Request.Builder().url("$baseUrl/api/voice/transcribe").post(multipart).build()
        safeParseJson(client.newCall(request).execute().body?.string())
    }

    suspend fun speak(text: String): JsonObject = withContext(Dispatchers.IO) {
        val body = """{"text":${gson.toJson(text)}}""".toRequestBody(json)
        val request = Request.Builder().url("$baseUrl/api/voice/speak").post(body).build()
        safeParseJson(client.newCall(request).execute().body?.string())
    }

    // --- Capabilities ---

    suspend fun getCapabilities(): JsonObject = withContext(Dispatchers.IO) {
        val request = Request.Builder().url("$baseUrl/api/capabilities").build()
        safeParseJson(client.newCall(request).execute().body?.string())
    }

    // --- Search ---

    suspend fun searchChat(query: String): JsonObject = withContext(Dispatchers.IO) {
        val request = Request.Builder().url("$baseUrl/api/chat/search?session_id=$sessionId&q=${java.net.URLEncoder.encode(query, "UTF-8")}").build()
        safeParseJson(client.newCall(request).execute().body?.string())
    }

    // --- Ratings ---

    suspend fun rateMessage(messageIndex: Int, rating: String) = withContext(Dispatchers.IO) {
        val body = """{"session_id":"$sessionId","message_index":$messageIndex,"rating":"$rating"}""".toRequestBody(json)
        val request = Request.Builder().url("$baseUrl/api/chat/rate").post(body).build()
        client.newCall(request).execute()
    }

    // --- Branching ---

    suspend fun branchChat(branchFromIndex: Int, newMessage: String): JsonObject = withContext(Dispatchers.IO) {
        val body = """{"session_id":"$sessionId","branch_from_index":$branchFromIndex,"new_message":${gson.toJson(newMessage)}}""".toRequestBody(json)
        val request = Request.Builder().url("$baseUrl/api/chat/branch").post(body).build()
        safeParseJson(client.newCall(request).execute().body?.string())
    }

    // --- Background Tasks ---

    suspend fun getBackgroundTasks(): JsonObject = withContext(Dispatchers.IO) {
        val request = Request.Builder().url("$baseUrl/api/tasks/background?session_id=$sessionId").build()
        safeParseJson(client.newCall(request).execute().body?.string())
    }

    suspend fun cancelTask(taskId: String) = withContext(Dispatchers.IO) {
        val body = """{"task_id":"$taskId"}""".toRequestBody(json)
        val request = Request.Builder().url("$baseUrl/api/tasks/cancel").post(body).build()
        client.newCall(request).execute()
    }

    // --- Permissions ---

    suspend fun getPermissions(): JsonObject = withContext(Dispatchers.IO) {
        val request = Request.Builder().url("$baseUrl/api/permissions?session_id=$sessionId").build()
        safeParseJson(client.newCall(request).execute().body?.string())
    }

    suspend fun setPermission(tool: String, level: String) = withContext(Dispatchers.IO) {
        val body = """{"session_id":"$sessionId","tool":"$tool","level":"$level"}""".toRequestBody(json)
        val request = Request.Builder().url("$baseUrl/api/permissions").post(body).build()
        client.newCall(request).execute()
    }

    // --- Location ---

    suspend fun setLocation(latitude: Double, longitude: Double) = withContext(Dispatchers.IO) {
        val body = """{"latitude":$latitude,"longitude":$longitude,"session_id":"$sessionId"}""".toRequestBody(json)
        val request = Request.Builder().url("$baseUrl/api/location").post(body).build()
        safeParseJson(client.newCall(request).execute().body?.string())
    }

    // --- Presets ---

    suspend fun getPresets(): JsonObject = withContext(Dispatchers.IO) {
        val request = Request.Builder().url("$baseUrl/api/presets").build()
        safeParseJson(client.newCall(request).execute().body?.string())
    }

    suspend fun applyPreset(preset: String): JsonObject = withContext(Dispatchers.IO) {
        val body = """{"preset":"$preset"}""".toRequestBody(json)
        val request = Request.Builder().url("$baseUrl/api/presets/apply").post(body).build()
        safeParseJson(client.newCall(request).execute().body?.string())
    }

    suspend fun getTemplates(): JsonObject = withContext(Dispatchers.IO) {
        val request = Request.Builder().url("$baseUrl/api/templates").build()
        safeParseJson(client.newCall(request).execute().body?.string())
    }

    // --- Reasoning Config ---

    suspend fun setLargeModelRouting(enabled: Boolean) = withContext(Dispatchers.IO) {
        val body = """{"large_model_routing":$enabled}""".toRequestBody(json)
        val request = Request.Builder().url("$baseUrl/api/reasoning").post(body).build()
        client.newCall(request).execute()
    }

    // --- OAuth Config ---

    suspend fun saveOAuthConfig(service: String, clientId: String, clientSecret: String) = withContext(Dispatchers.IO) {
        val body = JsonObject().apply {
            addProperty("service", service)
            addProperty("client_id", clientId)
            addProperty("client_secret", clientSecret)
        }
        val request = Request.Builder().url("$baseUrl/api/oauth/config")
            .post(gson.toJson(body).toRequestBody(json)).build()
        client.newCall(request).execute()
    }

    // --- Reasoning History ---

    suspend fun getReasoningHistory(sid: String = ""): List<String> = withContext(Dispatchers.IO) {
        try {
            val s = sid.ifEmpty { sessionId }
            val request = Request.Builder().url("$baseUrl/api/reasoning/history?session_id=$s").build()
            val response = client.newCall(request).execute()
            val body = response.body?.string() ?: "{}"
            val obj = gson.fromJson(body, JsonObject::class.java)
            val arr = obj.getAsJsonArray("entries")
            if (arr != null) arr.map { it.asString } else emptyList()
        } catch (_: Exception) { emptyList() }
    }

    // --- Changelog ---

    suspend fun getChangelog(): String = withContext(Dispatchers.IO) {
        try {
            val request = Request.Builder().url("$baseUrl/api/changelog").build()
            val response = client.newCall(request).execute()
            val body = response.body?.string() ?: "{}"
            val obj = gson.fromJson(body, JsonObject::class.java)
            obj.get("content")?.asString ?: "Changelog not available."
        } catch (e: Exception) { "Failed to load changelog: ${e.message}" }
    }

    // --- File Upload ---

    suspend fun uploadFile(filename: String, bytes: ByteArray): JsonObject = withContext(Dispatchers.IO) {
        val fileBody = bytes.toRequestBody("application/octet-stream".toMediaType())
        val multipart = MultipartBody.Builder()
            .setType(MultipartBody.FORM)
            .addFormDataPart("file", filename, fileBody)
            .build()
        val request = Request.Builder().url("$baseUrl/api/upload").post(multipart).build()
        safeParseJson(client.newCall(request).execute().body?.string())
    }
}
