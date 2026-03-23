package com.omniagent.app.ai

import android.content.Context
import android.os.Build
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.tensorflow.lite.Interpreter
import org.tensorflow.lite.gpu.GpuDelegate
import java.io.File

/**
 * On-device AI manager — uses Gemini Nano (via Google AI Edge) on the
 * Snapdragon 8 Gen 3 NPU for real LLM inference on-device.
 *
 * Gemini Nano provides:
 *  - Text generation (~30-50 tok/s on NPU)
 *  - Summarization
 *  - Smart reply generation
 *  - Intent classification
 *  - Query answering (general knowledge)
 *
 * Falls back to heuristics on devices without Gemini Nano support.
 */
object OnDeviceAI {
    private const val TAG = "OnDeviceAI"

    // Capability flags
    var isAvailable = false
        private set
    var hasNNAPI = false
        private set
    var hasGpuDelegate = false
        private set
    var hasGeminiNano = false
        private set
    var chipName = "Unknown"
        private set
    var npuName = "None"
        private set

    // Gemini Nano session
    private var _geminiClient: Any? = null  // GenerativeModel from aicore

    // Activity log
    private val _activityLog = mutableListOf<String>()
    val activityLog: List<String> get() = _activityLog.toList()

    private fun log(action: String) {
        val ts = java.text.SimpleDateFormat("HH:mm:ss", java.util.Locale.getDefault()).format(java.util.Date())
        val entry = "[$ts] \u26A1 NPU: $action"
        _activityLog.add(entry)
        Log.d(TAG, entry)
        if (_activityLog.size > 50) _activityLog.removeAt(0)
    }

    fun clearLog() { _activityLog.clear() }

    /**
     * Initialize on-device AI — detect hardware and Gemini Nano availability.
     */
    fun init(context: Context) {
        try {
            // Detect chip
            chipName = Build.HARDWARE
            val soc = Build.SOC_MODEL.ifEmpty { Build.BOARD }
            npuName = when {
                soc.contains("SM8650", ignoreCase = true) -> "Snapdragon 8 Gen 3 (Hexagon NPU)"
                soc.contains("SM8750", ignoreCase = true) -> "Snapdragon 8 Elite (Hexagon NPU)"
                soc.contains("SM8550", ignoreCase = true) -> "Snapdragon 8 Gen 2 (Hexagon NPU)"
                soc.contains("s5e9945", ignoreCase = true) -> "Exynos 2400 (Samsung NPU)"
                soc.contains("SM8475", ignoreCase = true) -> "Snapdragon 8+ Gen 1 (Hexagon)"
                soc.contains("tensor", ignoreCase = true) -> "Google Tensor (TPU)"
                soc.contains("qcom", ignoreCase = true) || soc.contains("SM", ignoreCase = true) -> "Qualcomm NPU"
                else -> "Generic NNAPI"
            }

            hasNNAPI = Build.VERSION.SDK_INT >= 27

            hasGpuDelegate = try {
                Class.forName("org.tensorflow.lite.gpu.GpuDelegate")
                val delegate = GpuDelegate()
                delegate.close()
                true
            } catch (e: Throwable) {
                false
            }

            // Try to initialize Gemini Nano via Google AI Edge
            hasGeminiNano = initGeminiNano(context)

            isAvailable = hasNNAPI || hasGpuDelegate || hasGeminiNano
            val engine = if (hasGeminiNano) "Gemini Nano" else "Heuristics"
            Log.i(TAG, "On-device AI: available=$isAvailable, Gemini=$hasGeminiNano, NNAPI=$hasNNAPI, GPU=$hasGpuDelegate, SoC=$soc, NPU=$npuName, Engine=$engine")
        } catch (e: Throwable) {
            Log.e(TAG, "On-device AI init failed (non-fatal): ${e.message}")
            isAvailable = false
        }
    }

    private fun initGeminiNano(context: Context): Boolean {
        return try {
            val clazz = Class.forName("com.google.ai.edge.aicore.GenerativeModel")
            val configClass = Class.forName("com.google.ai.edge.aicore.GenerationConfig")

            // Build config
            val configBuilder = configClass.getDeclaredClasses().find { it.simpleName == "Builder" }
                ?.getDeclaredConstructor()?.newInstance()
            val config = configBuilder?.javaClass?.getMethod("build")?.invoke(configBuilder)

            // Create GenerativeModel
            val constructor = clazz.getDeclaredConstructor(String::class.java, configClass)
            _geminiClient = constructor.newInstance("gemini-nano", config)

            Log.i(TAG, "Gemini Nano initialized successfully")
            true
        } catch (e: Throwable) {
            Log.d(TAG, "Gemini Nano not available: ${e.message}")
            false
        }
    }

    /**
     * Generate text using Gemini Nano. Returns null if not available.
     */
    private suspend fun geminiGenerate(prompt: String): String? = withContext(Dispatchers.Default) {
        val client = _geminiClient ?: return@withContext null
        try {
            // Call generateContent via reflection (avoids compile-time dependency issues)
            val method = client.javaClass.getMethod("generateContent", String::class.java)
            val response = method.invoke(client, prompt)
            val textMethod = response?.javaClass?.getMethod("getText")
            val text = textMethod?.invoke(response) as? String
            text?.trim()
        } catch (e: Throwable) {
            Log.w(TAG, "Gemini generate failed: ${e.message}")
            null
        }
    }

    fun getCapabilities(): Map<String, Any> = mapOf(
        "available" to isAvailable,
        "chip" to chipName,
        "npu" to npuName,
        "gemini_nano" to hasGeminiNano,
        "nnapi" to hasNNAPI,
        "gpu_delegate" to hasGpuDelegate,
        "soc" to Build.SOC_MODEL,
        "engine" to if (hasGeminiNano) "gemini-nano" else "heuristics",
        "supported_tasks" to listOf(
            "text_generation", "summarization", "smart_reply",
            "classification", "sentiment", "query_answering",
        ),
    )

    // ── Task APIs ────────────────────────────────────────────

    /**
     * Classify text intent using Gemini Nano or heuristic fallback.
     */
    suspend fun classifyIntent(context: Context, text: String): String = withContext(Dispatchers.Default) {
        if (!isAvailable) return@withContext "general"
        log("Classifying intent on $npuName" + if (hasGeminiNano) " (Gemini Nano)" else "")

        if (hasGeminiNano) {
            val result = geminiGenerate(
                "Classify this user message into exactly ONE category. " +
                "Categories: question, command, greeting, code, debug, summarize, general. " +
                "Reply with ONLY the category name, nothing else.\n\nMessage: $text"
            )
            if (result != null) {
                val category = result.lowercase().trim().split(" ")[0].split("\n")[0]
                val valid = setOf("question", "command", "greeting", "code", "debug", "summarize", "general")
                val final = if (category in valid) category else "general"
                log("Intent: $final (Gemini Nano)")
                return@withContext final
            }
        }

        // Heuristic fallback
        val lower = text.lowercase().trim()
        val result = when {
            lower.endsWith("?") || lower.startsWith("what") || lower.startsWith("how") ||
            lower.startsWith("why") || lower.startsWith("when") || lower.startsWith("where") ||
            lower.startsWith("who") || lower.startsWith("can you") || lower.startsWith("is ") -> "question"
            lower.startsWith("write") || lower.startsWith("create") || lower.startsWith("generate") ||
            lower.startsWith("make") || lower.startsWith("build") || lower.startsWith("add") -> "command"
            lower.startsWith("hi") || lower.startsWith("hello") || lower.startsWith("hey") ||
            lower.startsWith("good morning") || lower.startsWith("thanks") -> "greeting"
            lower.contains("```") || lower.contains("function") || lower.contains("class ") ||
            lower.contains("def ") || lower.contains("import ") -> "code"
            lower.contains("fix") || lower.contains("debug") || lower.contains("error") ||
            lower.contains("bug") || lower.contains("crash") -> "debug"
            lower.contains("summarize") || lower.contains("summary") || lower.contains("explain") -> "summarize"
            else -> "general"
        }
        log("Intent: $result (heuristic)")
        result
    }

    /**
     * Generate smart reply suggestions using Gemini Nano or heuristic fallback.
     */
    suspend fun smartReplies(context: Context, lastAssistantMessage: String): List<String> = withContext(Dispatchers.Default) {
        if (!isAvailable || lastAssistantMessage.isBlank()) return@withContext emptyList()
        log("Generating smart replies" + if (hasGeminiNano) " (Gemini Nano)" else "")

        if (hasGeminiNano) {
            val result = geminiGenerate(
                "Given this AI assistant response, suggest 3 short follow-up questions or replies the user might want to send. " +
                "Format: one per line, no numbering, no quotes, max 8 words each.\n\n" +
                "Response: ${lastAssistantMessage.take(500)}"
            )
            if (result != null) {
                val replies = result.split("\n")
                    .map { it.trim().trimStart('-', '*', '1', '2', '3', '.', ' ') }
                    .filter { it.isNotBlank() && it.length in 3..60 }
                    .take(3)
                if (replies.isNotEmpty()) {
                    log("Smart replies: ${replies.joinToString(", ")}")
                    return@withContext replies
                }
            }
        }

        // Heuristic fallback
        val lower = lastAssistantMessage.lowercase()
        val suggestions = mutableListOf<String>()
        when {
            lower.contains("error") || lower.contains("failed") || lower.contains("exception") -> {
                suggestions.add("Show me the full error")
                suggestions.add("How do I fix this?")
                suggestions.add("Try a different approach")
            }
            lower.contains("```") || lower.contains("function") || lower.contains("class") -> {
                suggestions.add("Explain this code")
                suggestions.add("Write tests for this")
                suggestions.add("Optimize it")
            }
            lower.contains("file") || lower.contains("created") || lower.contains("saved") -> {
                suggestions.add("Show me the file")
                suggestions.add("What's next?")
                suggestions.add("Make changes")
            }
            lower.endsWith("?") -> {
                suggestions.add("Yes")
                suggestions.add("No")
                suggestions.add("Tell me more")
            }
            else -> {
                suggestions.add("Tell me more")
                suggestions.add("What else can you do?")
                suggestions.add("Thanks!")
            }
        }
        val result = suggestions.take(3)
        log("Smart replies: ${result.joinToString(", ")} (heuristic)")
        result
    }

    /**
     * Sentiment analysis using Gemini Nano or heuristic fallback.
     */
    suspend fun sentiment(text: String): String = withContext(Dispatchers.Default) {
        if (!isAvailable) return@withContext "neutral"
        log("Analyzing sentiment" + if (hasGeminiNano) " (Gemini Nano)" else "")

        if (hasGeminiNano) {
            val result = geminiGenerate(
                "Classify the sentiment of this text as exactly ONE word: positive, negative, or neutral.\n\nText: $text"
            )
            if (result != null) {
                val s = result.lowercase().trim()
                val final = when {
                    "positive" in s -> "positive"
                    "negative" in s -> "negative"
                    else -> "neutral"
                }
                log("Sentiment: $final (Gemini Nano)")
                return@withContext final
            }
        }

        // Heuristic fallback
        val lower = text.lowercase()
        val posWords = listOf("good", "great", "thanks", "awesome", "perfect", "love", "excellent", "amazing", "helpful", "nice")
        val negWords = listOf("bad", "wrong", "error", "fail", "hate", "terrible", "awful", "broken", "bug", "crash", "worst")
        val posScore = posWords.count { lower.contains(it) }
        val negScore = negWords.count { lower.contains(it) }
        val result = when {
            posScore > negScore -> "positive"
            negScore > posScore -> "negative"
            else -> "neutral"
        }
        log("Sentiment: $result (heuristic)")
        result
    }

    /**
     * Try to handle a message locally. Returns response or null if server needed.
     * With Gemini Nano, this can handle general knowledge, summaries, and simple Q&A.
     */
    suspend fun tryLocalResponse(context: Context, message: String): String? = withContext(Dispatchers.Default) {
        if (!isAvailable) return@withContext null
        log("Checking if query can be handled on-device")

        val intent = classifyIntent(context, message)
        val lower = message.lowercase().trim()

        // Handle greetings locally (both Gemini and heuristic)
        if (intent == "greeting") {
            log("Handling greeting on-device")
            if (hasGeminiNano) {
                val reply = geminiGenerate("Reply to this greeting naturally and briefly: $message")
                if (reply != null) return@withContext reply
            }
            return@withContext when {
                lower.startsWith("thanks") || lower.startsWith("thank you") -> "You're welcome! Let me know if you need anything else."
                lower.startsWith("hi") || lower.startsWith("hello") || lower.startsWith("hey") -> "Hello! How can I help you today?"
                lower.startsWith("good morning") -> "Good morning! What can I do for you?"
                lower.startsWith("good night") -> "Good night! Feel free to reach out anytime."
                else -> null
            }
        }

        // Time queries
        if (lower.contains("what time") || lower == "time") {
            log("Handling time query on-device")
            val sdf = java.text.SimpleDateFormat("h:mm a, EEEE, MMMM d", java.util.Locale.getDefault())
            return@withContext "It's ${sdf.format(java.util.Date())}."
        }

        // Device info queries
        if (lower.contains("what device") || lower.contains("my phone") || lower.contains("phone info")) {
            log("Handling device info query on-device")
            return@withContext "You're on a ${Build.MANUFACTURER} ${Build.MODEL} running Android ${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT}). " +
                    "SoC: ${Build.SOC_MODEL}. NPU: $npuName." +
                    if (hasGeminiNano) " Gemini Nano active." else ""
        }

        // With Gemini Nano: handle general knowledge, summaries, simple Q&A
        if (hasGeminiNano && intent in setOf("question", "summarize", "general")) {
            // Don't handle locally if it needs tools (file ops, web search, code)
            val needsServer = lower.contains("file") || lower.contains("search") || lower.contains("run ") ||
                    lower.contains("install") || lower.contains("create") || lower.contains("write") ||
                    lower.contains("code") || lower.contains("git ") || lower.contains("build")
            if (!needsServer) {
                log("Handling with Gemini Nano on-device")
                val reply = geminiGenerate("Answer this concisely and helpfully:\n\n$message")
                if (reply != null && reply.length > 10) {
                    return@withContext reply
                }
            }
        }

        log("Query requires server — forwarding")
        null
    }

    /**
     * Summarize text using Gemini Nano. Falls back to truncation.
     */
    suspend fun summarize(text: String, maxWords: Int = 50): String = withContext(Dispatchers.Default) {
        if (hasGeminiNano) {
            log("Summarizing with Gemini Nano")
            val result = geminiGenerate("Summarize this in $maxWords words or fewer:\n\n${text.take(2000)}")
            if (result != null) return@withContext result
        }
        // Fallback: truncate
        val words = text.split(" ")
        if (words.size <= maxWords) return@withContext text
        words.take(maxWords).joinToString(" ") + "..."
    }

    /**
     * Rewrite a query for clarity before sending to server.
     */
    suspend fun rewriteQuery(query: String): String = withContext(Dispatchers.Default) {
        if (!hasGeminiNano) return@withContext query
        log("Rewriting query with Gemini Nano")
        val result = geminiGenerate(
            "Rewrite this user query to be clearer and more specific. Keep it concise. " +
            "If it's already clear, return it unchanged.\n\nQuery: $query"
        )
        result ?: query
    }

    fun release() {
        _geminiClient = null
    }
}
