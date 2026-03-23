package com.omniagent.app.ui.screens

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.omniagent.app.ui.ChatUiState
import com.omniagent.app.ui.ChatViewModel
import com.omniagent.app.ui.theme.*

@Composable
fun SettingsSheet(state: ChatUiState, vm: ChatViewModel) {
    var sysPrompt by remember(state.systemPrompt) { mutableStateOf(state.systemPrompt) }

    LaunchedEffect(Unit) { vm.loadIntegrations() }

    Surface(
        modifier = Modifier.fillMaxSize(),
        color = BgDark.copy(alpha = 0.95f),
    ) {
        Column(modifier = Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
            // Header
            Row(
                modifier = Modifier.fillMaxWidth().background(CardDark).padding(16.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("Settings & Metrics", fontWeight = FontWeight.Bold, fontSize = 16.sp)
                IconButton(onClick = { vm.toggleSettings() }) {
                    Icon(Icons.Filled.Close, contentDescription = "Close", tint = TextDim)
                }
            }

            // Metrics
            SettingsSection("Live Metrics") {
                MetricRow("Tasks Completed", "${state.tasksCompleted}")
                MetricRow("LLM Calls", "${state.llmCalls}")
                MetricRow("Session Messages", "${state.sessionMessages}")
                MetricRow("Commands Run", "${state.commandsRun}")
                MetricRow("Tokens In", "%,d".format(state.tokensIn))
                MetricRow("Tokens Out", "%,d".format(state.tokensOut))
                MetricRow("GPU", state.gpu)
                MetricRow("GPU Workers", "${state.gpuWorkers}")
                MetricRow("Server", state.serverIp)
                if (state.onDeviceAI) {
                    MetricRow("On-Device NPU", state.onDeviceNPU)
                    MetricRow("NPU Offload", if (state.onDeviceEnabled) "Enabled" else "Disabled")
                }
            }

            // Presets
            SettingsSection("System Presets") {
                LaunchedEffect(Unit) { vm.loadPresets() }
                if (state.presets.isEmpty()) {
                    Text("No presets available", fontSize = 12.sp, color = TextDim)
                } else {
                    Row(modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                        horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        for (entry in state.presets) {
                            SettingsButton(entry.key.replaceFirstChar { c -> c.uppercase() }, Color.Transparent) {
                                vm.applyPreset(entry.key)
                                sysPrompt = state.systemPrompt
                            }
                        }
                    }
                }
            }

            // Templates
            SettingsSection("Quick Templates") {
                LaunchedEffect(Unit) { vm.loadTemplates() }
                if (state.templates.isEmpty()) {
                    Text("No templates available", fontSize = 12.sp, color = TextDim)
                } else {
                    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        for (entry in state.templates) {
                            SettingsButton(entry.key, Color.Transparent) {
                                vm.useTemplate(entry.value)
                                vm.toggleSettings()
                            }
                        }
                    }
                }
            }

            // System Prompt
            SettingsSection("System Prompt") {
                OutlinedTextField(
                    value = sysPrompt,
                    onValueChange = { sysPrompt = it },
                    modifier = Modifier.fillMaxWidth(),
                    placeholder = { Text("Custom instructions...", color = TextDim) },
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = Accent, unfocusedBorderColor = BorderDark,
                        cursorColor = Accent, focusedTextColor = TextPrimary, unfocusedTextColor = TextPrimary,
                        focusedContainerColor = BgDark, unfocusedContainerColor = BgDark,
                    ),
                    minLines = 2, maxLines = 4,
                    shape = RoundedCornerShape(6.dp),
                )
                Spacer(Modifier.height(6.dp))
                SettingsButton("Save Prompt", Accent) { vm.saveSystemPrompt(sysPrompt) }
            }

            // Expert Models
            SettingsSection("Expert Models") {
                state.experts.forEach { (role, model) ->
                    Text(role.replaceFirstChar { it.uppercase() }, fontSize = 11.sp, color = TextDim)
                    Text(model, fontSize = 13.sp, color = TextPrimary, fontFamily = FontFamily.Monospace,
                        modifier = Modifier.padding(bottom = 8.dp))
                }
            }

            // Installed Models
            SettingsSection("Installed Models") {
                Row(modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                    horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                    state.installedModels.forEach { model ->
                        Surface(
                            shape = RoundedCornerShape(4.dp),
                            border = BorderStroke(1.dp, BorderDark),
                            color = BgDark,
                        ) {
                            Text(model, modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp),
                                fontSize = 11.sp, fontFamily = FontFamily.Monospace, color = TextPrimary)
                        }
                    }
                }
            }

            // Export
            SettingsSection("Export Chat") {
                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    listOf("json", "md", "txt", "csv", "html").forEach { fmt ->
                        SettingsButton(fmt.uppercase(), Color.Transparent, Modifier.weight(1f)) {
                            vm.exportChat(fmt)
                        }
                    }
                }
            }

            // OAuth Setup (one-time)
            if (!state.githubOAuth || !state.googleOAuth) {
                SettingsSection("OAuth Setup (one-time)") {
                    Text("Register OAuth apps to enable one-click Connect:", fontSize = 12.sp, color = TextDim)
                    Spacer(Modifier.height(4.dp))
                    val context2 = LocalContext.current
                    // GitHub setup
                    if (!state.githubOAuth) {
                        var ghId by remember { mutableStateOf("") }
                        var ghSecret by remember { mutableStateOf("") }
                        Text("GitHub", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = TextPrimary)
                        SettingsButton("Create GitHub OAuth App", Color.Transparent) {
                            context2.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://github.com/settings/developers")))
                        }
                        Spacer(Modifier.height(4.dp))
                        OutlinedTextField(value = ghId, onValueChange = { ghId = it }, modifier = Modifier.fillMaxWidth(),
                            placeholder = { Text("Client ID", color = TextDim, fontSize = 12.sp) }, singleLine = true,
                            colors = OutlinedTextFieldDefaults.colors(focusedBorderColor = Accent, unfocusedBorderColor = BorderDark,
                                focusedTextColor = TextPrimary, unfocusedTextColor = TextPrimary, cursorColor = Accent,
                                focusedContainerColor = BgDark, unfocusedContainerColor = BgDark),
                            shape = RoundedCornerShape(6.dp), textStyle = androidx.compose.ui.text.TextStyle(fontSize = 12.sp))
                        Spacer(Modifier.height(4.dp))
                        OutlinedTextField(value = ghSecret, onValueChange = { ghSecret = it }, modifier = Modifier.fillMaxWidth(),
                            placeholder = { Text("Client Secret", color = TextDim, fontSize = 12.sp) }, singleLine = true,
                            visualTransformation = androidx.compose.ui.text.input.PasswordVisualTransformation(),
                            colors = OutlinedTextFieldDefaults.colors(focusedBorderColor = Accent, unfocusedBorderColor = BorderDark,
                                focusedTextColor = TextPrimary, unfocusedTextColor = TextPrimary, cursorColor = Accent,
                                focusedContainerColor = BgDark, unfocusedContainerColor = BgDark),
                            shape = RoundedCornerShape(6.dp), textStyle = androidx.compose.ui.text.TextStyle(fontSize = 12.sp))
                        Spacer(Modifier.height(4.dp))
                        SettingsButton("Save GitHub OAuth", GreenDark) {
                            if (ghId.isNotBlank() && ghSecret.isNotBlank()) {
                                vm.saveOAuthConfig("github", ghId.trim(), ghSecret.trim())
                                ghId = ""; ghSecret = ""
                            }
                        }
                        Spacer(Modifier.height(12.dp))
                    }
                    // Google setup
                    if (!state.googleOAuth) {
                        var gId by remember { mutableStateOf("") }
                        var gSecret by remember { mutableStateOf("") }
                        Text("Google", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = TextPrimary)
                        SettingsButton("Create Google OAuth Client", Color.Transparent) {
                            context2.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://console.cloud.google.com/apis/credentials")))
                        }
                        Spacer(Modifier.height(4.dp))
                        OutlinedTextField(value = gId, onValueChange = { gId = it }, modifier = Modifier.fillMaxWidth(),
                            placeholder = { Text("Client ID", color = TextDim, fontSize = 12.sp) }, singleLine = true,
                            colors = OutlinedTextFieldDefaults.colors(focusedBorderColor = Accent, unfocusedBorderColor = BorderDark,
                                focusedTextColor = TextPrimary, unfocusedTextColor = TextPrimary, cursorColor = Accent,
                                focusedContainerColor = BgDark, unfocusedContainerColor = BgDark),
                            shape = RoundedCornerShape(6.dp), textStyle = androidx.compose.ui.text.TextStyle(fontSize = 12.sp))
                        Spacer(Modifier.height(4.dp))
                        OutlinedTextField(value = gSecret, onValueChange = { gSecret = it }, modifier = Modifier.fillMaxWidth(),
                            placeholder = { Text("Client Secret", color = TextDim, fontSize = 12.sp) }, singleLine = true,
                            visualTransformation = androidx.compose.ui.text.input.PasswordVisualTransformation(),
                            colors = OutlinedTextFieldDefaults.colors(focusedBorderColor = Accent, unfocusedBorderColor = BorderDark,
                                focusedTextColor = TextPrimary, unfocusedTextColor = TextPrimary, cursorColor = Accent,
                                focusedContainerColor = BgDark, unfocusedContainerColor = BgDark),
                            shape = RoundedCornerShape(6.dp), textStyle = androidx.compose.ui.text.TextStyle(fontSize = 12.sp))
                        Spacer(Modifier.height(4.dp))
                        SettingsButton("Save Google OAuth", GreenDark) {
                            if (gId.isNotBlank() && gSecret.isNotBlank()) {
                                vm.saveOAuthConfig("google", gId.trim(), gSecret.trim())
                                gId = ""; gSecret = ""
                            }
                        }
                    }
                }
            }

            // Integrations
            SettingsSection("Integrations") {
                val context = LocalContext.current
                var githubToken by remember { mutableStateOf("") }
                var googleToken by remember { mutableStateOf("") }

                // GitHub
                var showGhManual by remember { mutableStateOf(false) }
                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                    Text("GitHub", fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = TextPrimary)
                    Text(if (state.githubConnected) "Connected" else "Not connected",
                        fontSize = 11.sp, color = if (state.githubConnected) GreenDark else TextDim)
                }
                Spacer(Modifier.height(6.dp))
                SettingsButton("Connect with GitHub", Accent) {
                    vm.oauthConnect("github", context)
                }
                TextButton(onClick = { showGhManual = !showGhManual }) {
                    Text(if (showGhManual) "Hide token input" else "Use token instead",
                        fontSize = 11.sp, color = TextDim)
                }
                if (showGhManual) {
                    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        OutlinedTextField(
                            value = githubToken, onValueChange = { githubToken = it },
                            modifier = Modifier.weight(1f),
                            placeholder = { Text("ghp_...", color = TextDim, fontSize = 12.sp) },
                            singleLine = true,
                            colors = OutlinedTextFieldDefaults.colors(
                                focusedBorderColor = Accent, unfocusedBorderColor = BorderDark,
                                focusedTextColor = TextPrimary, unfocusedTextColor = TextPrimary,
                                cursorColor = Accent, focusedContainerColor = BgDark, unfocusedContainerColor = BgDark,
                            ),
                            shape = RoundedCornerShape(6.dp),
                            textStyle = androidx.compose.ui.text.TextStyle(fontSize = 12.sp),
                        )
                        SettingsButton("Connect", GreenDark, Modifier.width(80.dp)) {
                            if (githubToken.isNotBlank()) { vm.connectIntegration("github", githubToken); githubToken = "" }
                        }
                    }
                }

                Spacer(Modifier.height(16.dp))

                // Google
                var showGoogleManual by remember { mutableStateOf(false) }
                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                    Text("Google (Drive, Gmail, Tasks)", fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = TextPrimary)
                    Text(if (state.googleConnected) "Connected" else "Not connected",
                        fontSize = 11.sp, color = if (state.googleConnected) GreenDark else TextDim)
                }
                Spacer(Modifier.height(6.dp))
                SettingsButton("Connect with Google", Accent) {
                    vm.oauthConnect("google", context)
                }
                TextButton(onClick = { showGoogleManual = !showGoogleManual }) {
                    Text(if (showGoogleManual) "Hide token input" else "Use token instead",
                        fontSize = 11.sp, color = TextDim)
                }
                if (showGoogleManual) {
                    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        OutlinedTextField(
                            value = googleToken, onValueChange = { googleToken = it },
                            modifier = Modifier.weight(1f),
                            placeholder = { Text("ya29...", color = TextDim, fontSize = 12.sp) },
                            singleLine = true,
                            colors = OutlinedTextFieldDefaults.colors(
                                focusedBorderColor = Accent, unfocusedBorderColor = BorderDark,
                                focusedTextColor = TextPrimary, unfocusedTextColor = TextPrimary,
                                cursorColor = Accent, focusedContainerColor = BgDark, unfocusedContainerColor = BgDark,
                            ),
                            shape = RoundedCornerShape(6.dp),
                            textStyle = androidx.compose.ui.text.TextStyle(fontSize = 12.sp),
                        )
                        SettingsButton("Connect", GreenDark, Modifier.width(80.dp)) {
                            if (googleToken.isNotBlank()) { vm.connectIntegration("google", googleToken); googleToken = "" }
                        }
                    }
                }

                Spacer(Modifier.height(12.dp))
                Text("Save Chat To:", fontSize = 11.sp, color = TextDim)
                Spacer(Modifier.height(4.dp))
                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    SettingsButton("GitHub Gist", Color.Transparent, Modifier.weight(1f)) { vm.saveChatToService("gist") }
                    SettingsButton("Drive", Color.Transparent, Modifier.weight(1f)) { vm.saveChatToService("drive") }
                    SettingsButton("Tasks", Color.Transparent, Modifier.weight(1f)) { vm.saveChatToService("tasks") }
                }
            }

            // Agent Memory
            SettingsSection("Agent Memory") {
                LaunchedEffect(Unit) { vm.loadMemories() }
                if (state.memories.isEmpty()) {
                    Text("No memories yet. The agent learns from your corrections and preferences.",
                        fontSize = 12.sp, color = TextDim)
                } else {
                    state.memories.forEach { m ->
                        Row(
                            modifier = Modifier.fillMaxWidth().padding(vertical = 2.dp),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Column(modifier = Modifier.weight(1f)) {
                                Text(m["category"] ?: "", fontSize = 10.sp, color = Accent,
                                    fontWeight = FontWeight.Bold)
                                Text((m["key"] ?: "").take(40), fontSize = 12.sp, color = TextPrimary)
                            }
                            IconButton(onClick = { vm.forgetMemory(m["category"] ?: "", m["key"] ?: "") },
                                modifier = Modifier.size(24.dp)) {
                                Icon(Icons.Filled.Close, contentDescription = "Delete",
                                    tint = RedDark, modifier = Modifier.size(14.dp))
                            }
                        }
                    }
                }
                Spacer(Modifier.height(4.dp))
                SettingsButton("Refresh Memories", Accent) { vm.loadMemories() }
            }

            // Plugins
            SettingsSection("Plugins") {
                LaunchedEffect(Unit) { vm.loadPlugins() }
                if (state.plugins.isEmpty()) {
                    Text("No plugins loaded. Drop .py files in ~/.omniagent/tools/",
                        fontSize = 12.sp, color = TextDim)
                } else {
                    state.plugins.forEach { p ->
                        Row(modifier = Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
                            Text(p["name"] ?: "", fontSize = 12.sp, color = TextPrimary,
                                fontWeight = FontWeight.Medium, modifier = Modifier.weight(1f))
                            Text(p["description"]?.take(30) ?: "", fontSize = 11.sp, color = TextDim)
                        }
                    }
                }
                Spacer(Modifier.height(4.dp))
                SettingsButton("Reload Plugins", Accent) { vm.reloadPlugins() }
            }

            // History
            SettingsSection("History") {
                SettingsButton("Reasoning / Thinking Log", Accent) { vm.loadReasoningHistory() }
            }

            // About
            SettingsSection("About") {
                MetricRow("Version", "8.0")
                SettingsButton("View Changelog", Accent) { vm.loadChangelog() }
            }

            // Session
            SettingsSection("Account") {
                MetricRow("Logged in as", state.authUsername.ifEmpty { "guest" })
                SettingsButton("Logout", RedDark) { vm.doLogout() }
            }

            Spacer(Modifier.height(32.dp))
        }
    }

    // Reasoning History — full-screen overlay
    if (state.showReasoningHistory) {
        Surface(modifier = Modifier.fillMaxSize(), color = BgDark.copy(alpha = 0.97f)) {
            Column(modifier = Modifier.fillMaxSize()) {
                Row(
                    modifier = Modifier.fillMaxWidth().background(CardDark).padding(16.dp),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text("Reasoning / Thinking Log", fontWeight = FontWeight.Bold, fontSize = 16.sp, color = Accent)
                    IconButton(onClick = { vm.dismissReasoningHistory() }) {
                        Icon(Icons.Filled.Close, contentDescription = "Close", tint = TextDim)
                    }
                }
                if (state.reasoningHistory.isEmpty()) {
                    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                        Text("No reasoning entries yet.\nSend a message to generate some.",
                            fontSize = 14.sp, color = TextDim, modifier = Modifier.padding(32.dp))
                    }
                } else {
                    Column(
                        modifier = Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(12.dp),
                        verticalArrangement = Arrangement.spacedBy(2.dp),
                    ) {
                        Text("${state.reasoningHistory.size} entries", fontSize = 11.sp, color = TextDim,
                            modifier = Modifier.padding(bottom = 8.dp))
                        for (entry in state.reasoningHistory) {
                            val color = when {
                                entry.contains("BitNet") -> Color(0xFF4FC3F7)
                                entry.contains("NPU") -> Color(0xFFCE93D8)
                                entry.contains("error", ignoreCase = true) || entry.contains("failed", ignoreCase = true) -> RedDark
                                entry.contains("Review") || entry.contains("Chain") -> Color(0xFFFFB74D)
                                entry.contains("complete") || entry.contains("approved") || entry.contains("passed") -> GreenDark
                                else -> TextPrimary
                            }
                            Text(entry, fontSize = 12.sp, color = color, fontFamily = FontFamily.Monospace,
                                modifier = Modifier.fillMaxWidth().padding(vertical = 3.dp))
                            HorizontalDivider(color = BorderDark.copy(alpha = 0.3f))
                        }
                    }
                }
            }
        }
    }

    // Changelog — full-screen overlay (AlertDialog can't scroll long content)
    if (state.showChangelog) {
        Surface(
            modifier = Modifier.fillMaxSize(),
            color = BgDark.copy(alpha = 0.97f),
        ) {
            Column(modifier = Modifier.fillMaxSize()) {
                // Header
                Row(
                    modifier = Modifier.fillMaxWidth().background(CardDark).padding(16.dp),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text("Changelog", fontWeight = FontWeight.Bold, fontSize = 16.sp, color = Accent)
                    IconButton(onClick = { vm.dismissChangelog() }) {
                        Icon(Icons.Filled.Close, contentDescription = "Close", tint = TextDim)
                    }
                }
                // Scrollable content
                Column(
                    modifier = Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
                ) {
                    MarkdownText(state.changelogContent)
                }
            }
        }
    }
}

@Composable
fun SettingsSection(title: String, content: @Composable ColumnScope.() -> Unit) {
    Column(modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp)) {
        Text(title, fontSize = 11.sp, fontWeight = FontWeight.Bold, color = Accent,
            letterSpacing = 0.5.sp, modifier = Modifier.padding(bottom = 8.dp))
        content()
    }
    HorizontalDivider(color = BorderDark, thickness = 1.dp)
}

@Composable
fun MetricRow(label: String, value: String) {
    Row(modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
        horizontalArrangement = Arrangement.SpaceBetween) {
        Text(label, fontSize = 13.sp, color = TextDim)
        Text(value, fontSize = 13.sp, color = TextPrimary, fontFamily = FontFamily.Monospace)
    }
}

@Composable
fun SettingsButton(label: String, color: Color, modifier: Modifier = Modifier, onClick: () -> Unit) {
    OutlinedButton(
        onClick = onClick,
        modifier = modifier.fillMaxWidth(),
        border = BorderStroke(1.dp, if (color == Color.Transparent) BorderDark else color),
        shape = RoundedCornerShape(6.dp),
        colors = ButtonDefaults.outlinedButtonColors(contentColor = if (color == Color.Transparent) TextPrimary else color),
    ) {
        Text(label, fontSize = 12.sp)
    }
}
