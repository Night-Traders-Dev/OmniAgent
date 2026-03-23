package com.omniagent.app.ui.screens

import android.Manifest
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import androidx.compose.animation.*
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.DpOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.omniagent.app.ui.ChatUiState
import com.omniagent.app.ui.ChatViewModel
import com.omniagent.app.ui.UiMessage
import com.omniagent.app.ui.theme.*

@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
fun ChatScreen(vm: ChatViewModel) {
    val state by vm.state.collectAsState()
    val listState = rememberLazyListState()
    val context = LocalContext.current

    // Request location permission on first launch, then send location to server
    val locationLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { permissions: Map<String, Boolean> ->
        if (permissions.values.any { it }) vm.sendLocation()
    }
    LaunchedEffect(Unit) {
        val hasFine = ContextCompat.checkSelfPermission(
            context, Manifest.permission.ACCESS_FINE_LOCATION
        ) == PackageManager.PERMISSION_GRANTED
        val hasCoarse = ContextCompat.checkSelfPermission(
            context, Manifest.permission.ACCESS_COARSE_LOCATION
        ) == PackageManager.PERMISSION_GRANTED
        if (!hasFine && !hasCoarse) {
            locationLauncher.launch(arrayOf(
                Manifest.permission.ACCESS_FINE_LOCATION,
                Manifest.permission.ACCESS_COARSE_LOCATION,
            ))
        } else {
            vm.sendLocation()
        }
    }

    LaunchedEffect(state.messages.size) {
        if (state.messages.isNotEmpty()) listState.animateScrollToItem(state.messages.size - 1)
    }

    Scaffold(
        topBar = { TopBar(state, onMenuClick = { vm.toggleSettings() }, onHistoryClick = { vm.toggleSessionDrawer() }, onSearchClick = { vm.toggleSearch() }) },
        bottomBar = { BottomControls(state, vm) },
        containerColor = BgDark,
    ) { padding ->
        Column(modifier = Modifier.padding(padding).fillMaxSize()) {
            // Always-visible compact metrics bar
            MetricsBar(state)
            AnimatedVisibility(visible = state.taskStartedAt != null) { StatusPill(state) }

            // Search bar
            AnimatedVisibility(visible = state.showSearch) {
                var searchQuery by remember { mutableStateOf("") }
                Row(
                    modifier = Modifier.fillMaxWidth().background(CardDark).padding(horizontal = 12.dp, vertical = 6.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    OutlinedTextField(
                        value = searchQuery,
                        onValueChange = { searchQuery = it; if (it.length >= 2) vm.searchMessages(it) },
                        modifier = Modifier.weight(1f).height(48.dp),
                        placeholder = { Text("Search messages...", color = TextDim, fontSize = 12.sp) },
                        singleLine = true,
                        colors = OutlinedTextFieldDefaults.colors(
                            focusedBorderColor = Accent, unfocusedBorderColor = BorderDark,
                            cursorColor = Accent, focusedTextColor = Color.White, unfocusedTextColor = Color.White,
                            focusedContainerColor = BgDark, unfocusedContainerColor = BgDark,
                        ),
                        shape = RoundedCornerShape(6.dp),
                        textStyle = androidx.compose.ui.text.TextStyle(fontSize = 12.sp),
                    )
                    IconButton(onClick = { vm.toggleSearch() }, modifier = Modifier.size(32.dp)) {
                        Icon(Icons.Filled.Close, contentDescription = "Close", tint = TextDim, modifier = Modifier.size(16.dp))
                    }
                }
            }

            LazyColumn(
                state = listState,
                modifier = Modifier.weight(1f).fillMaxWidth(),
                contentPadding = PaddingValues(start = 12.dp, end = 12.dp, top = 8.dp, bottom = 16.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                items(state.messages.size) { index ->
                    val msg = state.messages[index]
                    when (msg.role) {
                        "user" -> UserBubble(msg, state, context, vm, index)
                        "thinking" -> ThinkingBlock(msg) { vm.toggleThinking(index) }
                        else -> AssistantBubble(msg, context, vm, index)
                    }
                }
            }
        }
    }

    if (state.showSessionDrawer) {
        SessionDrawer(state, vm)
    }

    if (state.showSettings) SettingsSheet(state, vm)

    state.error?.let { error ->
        Snackbar(modifier = Modifier.padding(16.dp),
            action = { TextButton(onClick = { vm.dismissError() }) { Text("OK") } }) { Text(error) }
    }
}

@Composable
fun TopBar(state: ChatUiState, onMenuClick: () -> Unit, onHistoryClick: () -> Unit = {}, onSearchClick: () -> Unit = {}) {
    Surface(color = CardDark, shadowElevation = 2.dp) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 10.dp),
            horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onHistoryClick, modifier = Modifier.size(36.dp)) {
                Icon(Icons.Filled.Forum, contentDescription = "Chat History", tint = TextPrimary)
            }
            Column(modifier = Modifier.weight(1f).padding(horizontal = 4.dp)) {
                Text("OmniAgent v8.4", fontWeight = FontWeight.Bold, fontSize = 16.sp, color = TextPrimary)
                Text(state.status, fontSize = 11.sp, color = TextDim, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                Surface(shape = RoundedCornerShape(4.dp), border = BorderStroke(1.dp, YellowDark), color = Color.Transparent) {
                    Text(state.gpu, modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp),
                        fontSize = 11.sp, color = YellowDark, fontFamily = FontFamily.Monospace)
                }
                IconButton(onClick = onSearchClick, modifier = Modifier.size(36.dp)) {
                    Icon(Icons.Filled.Search, contentDescription = "Search", tint = TextDim, modifier = Modifier.size(20.dp))
                }
                IconButton(onClick = { com.omniagent.app.ui.theme.isDarkTheme = !com.omniagent.app.ui.theme.isDarkTheme }, modifier = Modifier.size(36.dp)) {
                    Icon(if (com.omniagent.app.ui.theme.isDarkTheme) Icons.Filled.LightMode else Icons.Filled.DarkMode,
                        contentDescription = "Theme", tint = TextDim, modifier = Modifier.size(20.dp))
                }
                IconButton(onClick = onMenuClick) {
                    Icon(Icons.Filled.Settings, contentDescription = "Settings", tint = TextPrimary)
                }
            }
        }
    }
}

@Composable
fun StatusPill(state: ChatUiState) {
    Surface(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 4.dp),
        shape = RoundedCornerShape(10.dp), color = CardDark, border = BorderStroke(1.dp, BorderDark),
    ) {
        Row(modifier = Modifier.padding(10.dp), horizontalArrangement = Arrangement.SpaceBetween) {
            Column(modifier = Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    Box(modifier = Modifier.size(6.dp).clip(CircleShape).background(GreenDark))
                    Text(state.status, fontSize = 11.sp, color = Accent, fontFamily = FontFamily.Monospace)
                }
                if (state.totalSteps > 0)
                    Text("${state.stepIndex}/${state.totalSteps} - ${state.currentStep}",
                        fontSize = 10.sp, color = TextDim, fontFamily = FontFamily.Monospace)
            }
            Text(state.activeModel, fontSize = 10.sp, color = TextDim, fontFamily = FontFamily.Monospace)
        }
    }
}

@Composable
fun MetricsBar(state: ChatUiState) {
    Surface(color = BgDark) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 4.dp),
            horizontalArrangement = Arrangement.SpaceEvenly,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            MetricChip("\uD83D\uDCCA ${state.tasksCompleted}")
            MetricChip("\uD83E\uDDE0 ${state.llmCalls}")
            MetricChip("\uD83D\uDCAC ${state.sessionMessages}")
            MetricChip("\u2B06 %,d".format(state.tokensIn))
            MetricChip("\u2B07 %,d".format(state.tokensOut))
            if (state.gpuWorkers > 0) MetricChip("\uD83D\uDDA5 ${state.gpuWorkers}")
        }
    }
}

@Composable
private fun MetricChip(text: String) {
    Text(
        text, fontSize = 10.sp, color = TextDim,
        fontFamily = FontFamily.Monospace,
        modifier = Modifier
            .background(CardDark, RoundedCornerShape(4.dp))
            .padding(horizontal = 6.dp, vertical = 2.dp),
    )
}

// --- User Bubble with long-press menu ---

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun UserBubble(msg: UiMessage, state: ChatUiState, context: Context, vm: ChatViewModel, msgIndex: Int = -1) {
    var showMenu by remember { mutableStateOf(false) }

    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
        Box {
            Surface(
                shape = RoundedCornerShape(12.dp), color = GreenDark,
                modifier = Modifier.widthIn(max = 300.dp).combinedClickable(
                    onClick = {},
                    onLongClick = { showMenu = true },
                ),
            ) {
                Text(msg.content, modifier = Modifier.padding(12.dp), color = Color.White, fontSize = 14.sp)
            }

            DropdownMenu(expanded = showMenu, onDismissRequest = { showMenu = false },
                containerColor = CardDark, offset = DpOffset(0.dp, 0.dp)) {
                DropdownMenuItem(
                    text = { Text("Copy", color = TextPrimary, fontSize = 13.sp) },
                    onClick = { copyToClipboard(context, msg.content); showMenu = false },
                    leadingIcon = { Icon(Icons.Filled.ContentCopy, null, tint = TextDim, modifier = Modifier.size(18.dp)) },
                )
                DropdownMenuItem(
                    text = { Text("Resend", color = TextPrimary, fontSize = 13.sp) },
                    onClick = { vm.resendMessage(msg.content); showMenu = false },
                    leadingIcon = { Icon(Icons.Filled.Refresh, null, tint = TextDim, modifier = Modifier.size(18.dp)) },
                )
                if (msgIndex >= 0) {
                    HorizontalDivider(color = BorderDark)
                    DropdownMenuItem(
                        text = { Text("Edit from here", color = Accent, fontSize = 13.sp) },
                        onClick = {
                            showMenu = false
                            val newMsg = msg.content // Could show dialog, but for now resend
                            vm.branchConversation(msgIndex, newMsg)
                        },
                        leadingIcon = { Icon(Icons.Filled.Edit, null, tint = Accent, modifier = Modifier.size(18.dp)) },
                    )
                }
                HorizontalDivider(color = BorderDark)
                Text("Resend with model:", modifier = Modifier.padding(horizontal = 12.dp, vertical = 4.dp),
                    fontSize = 11.sp, color = TextDim)
                state.experts.forEach { (role, model) ->
                    DropdownMenuItem(
                        text = { Text("$role ($model)", color = TextPrimary, fontSize = 12.sp) },
                        onClick = { vm.resendWithModel(msg.content, model); showMenu = false },
                        leadingIcon = { Icon(Icons.Filled.SmartToy, null, tint = Accent, modifier = Modifier.size(16.dp)) },
                    )
                }
            }
        }
    }
}

// --- Assistant Bubble with long-press menu + Markdown ---

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun AssistantBubble(msg: UiMessage, context: Context, vm: ChatViewModel? = null, msgIndex: Int = -1) {
    var showMenu by remember { mutableStateOf(false) }

    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Start) {
        Box {
            Surface(
                shape = RoundedCornerShape(12.dp), color = CardDark,
                border = BorderStroke(1.dp, BorderDark),
                modifier = Modifier.widthIn(max = 320.dp).combinedClickable(
                    onClick = {},
                    onLongClick = { showMenu = true },
                ),
            ) {
                Column(modifier = Modifier.padding(12.dp)) {
                    // Confidence badge for low-confidence responses
                    if (msg.content.startsWith("*Note:") && "confidence" in msg.content.lowercase()) {
                        Surface(
                            shape = RoundedCornerShape(8.dp),
                            color = RedDark.copy(alpha = 0.15f),
                            modifier = Modifier.padding(bottom = 6.dp),
                        ) {
                            Text("low confidence", fontSize = 10.sp, color = RedDark,
                                modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp))
                        }
                    }
                    MarkdownText(msg.content, context)
                    if (msg.isStreaming)
                        Text("|", color = Accent, fontSize = 14.sp, fontWeight = FontWeight.Bold)
                }
            }

            DropdownMenu(expanded = showMenu, onDismissRequest = { showMenu = false },
                containerColor = CardDark, offset = DpOffset(0.dp, 0.dp)) {
                DropdownMenuItem(
                    text = { Text("Copy", color = TextPrimary, fontSize = 13.sp) },
                    onClick = { copyToClipboard(context, msg.content); showMenu = false },
                    leadingIcon = { Icon(Icons.Filled.ContentCopy, null, tint = TextDim, modifier = Modifier.size(18.dp)) },
                )
                DropdownMenuItem(
                    text = { Text("Share", color = TextPrimary, fontSize = 13.sp) },
                    onClick = { shareText(context, msg.content); showMenu = false },
                    leadingIcon = { Icon(Icons.Filled.Share, null, tint = TextDim, modifier = Modifier.size(18.dp)) },
                )
                if (vm != null && msgIndex >= 0) {
                    DropdownMenuItem(
                        text = { Text("Pin Message", color = Accent, fontSize = 13.sp) },
                        onClick = { vm.pinMessage(msgIndex, msg.content, "assistant"); showMenu = false },
                        leadingIcon = { Icon(Icons.Filled.PushPin, null, tint = Accent, modifier = Modifier.size(18.dp)) },
                    )
                    HorizontalDivider(color = BorderDark)
                    DropdownMenuItem(
                        text = { Text("Good response", color = GreenDark, fontSize = 13.sp) },
                        onClick = { vm.rateMessage(msgIndex, "thumbs_up"); showMenu = false; Toast.makeText(context, "Thanks!", Toast.LENGTH_SHORT).show() },
                        leadingIcon = { Icon(Icons.Filled.ThumbUp, null, tint = GreenDark, modifier = Modifier.size(18.dp)) },
                    )
                    DropdownMenuItem(
                        text = { Text("Bad response", color = RedDark, fontSize = 13.sp) },
                        onClick = { vm.rateMessage(msgIndex, "thumbs_down"); showMenu = false; Toast.makeText(context, "Noted", Toast.LENGTH_SHORT).show() },
                        leadingIcon = { Icon(Icons.Filled.ThumbDown, null, tint = RedDark, modifier = Modifier.size(18.dp)) },
                    )
                }
            }
        }
    }
}

fun copyToClipboard(context: Context, text: String) {
    val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
    clipboard.setPrimaryClip(ClipData.newPlainText("OmniAgent", text))
    Toast.makeText(context, "Copied", Toast.LENGTH_SHORT).show()
}

fun shareText(context: Context, text: String) {
    val intent = Intent(Intent.ACTION_SEND).apply {
        type = "text/plain"
        putExtra(Intent.EXTRA_TEXT, text)
    }
    context.startActivity(Intent.createChooser(intent, "Share response"))
}

@Composable
fun ThinkingBlock(msg: UiMessage, onToggle: () -> Unit) {
    Surface(
        shape = RoundedCornerShape(8.dp), color = CardDark,
        border = BorderStroke(1.dp, BorderDark), modifier = Modifier.fillMaxWidth(),
    ) {
        Column {
            Row(
                modifier = Modifier.fillMaxWidth().clickable { onToggle() }.padding(10.dp),
                horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically,
            ) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                    Icon(if (msg.isExpanded) Icons.Filled.ExpandLess else Icons.Filled.ExpandMore,
                        contentDescription = null, tint = TextDim, modifier = Modifier.size(16.dp))
                    Box(modifier = Modifier.size(6.dp).clip(CircleShape).background(if (msg.isExpanded) GreenDark else Accent))
                    Text(msg.content, fontSize = 12.sp, color = TextDim)
                }
                Text(msg.thinkingElapsed, fontSize = 11.sp, color = YellowDark, fontFamily = FontFamily.Monospace)
            }
            AnimatedVisibility(visible = msg.isExpanded) {
                Column(modifier = Modifier.padding(start = 12.dp, end = 12.dp, bottom = 10.dp)) {
                    msg.thinkingSteps.forEach { step ->
                        Text(step, fontSize = 11.sp, color = TextDim, fontFamily = FontFamily.Monospace,
                            modifier = Modifier.padding(vertical = 1.dp))
                    }
                }
            }
        }
    }
}

// --- Session Drawer with long-press context menu ---

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun SessionDrawer(state: ChatUiState, vm: ChatViewModel) {
    val context = LocalContext.current
    var ctxMenuSession by remember { mutableStateOf<Map<String, String>?>(null) }

    // Scrim
    Box(
        modifier = Modifier.fillMaxSize().background(BgDark.copy(alpha = 0.6f)).clickable { vm.toggleSessionDrawer() }
    )
    // Drawer panel
    Surface(
        modifier = Modifier.fillMaxHeight().width(280.dp),
        color = CardDark,
    ) {
        Column(modifier = Modifier.fillMaxSize()) {
            Row(
                modifier = Modifier.fillMaxWidth().padding(16.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("Chats", fontWeight = FontWeight.Bold, fontSize = 16.sp, color = TextPrimary)
                Button(
                    onClick = { vm.createNewChat() },
                    shape = RoundedCornerShape(6.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = Accent),
                    contentPadding = PaddingValues(horizontal = 14.dp, vertical = 4.dp),
                ) { Text("+ New", fontSize = 12.sp) }
            }
            HorizontalDivider(color = BorderDark)

            LazyColumn(modifier = Modifier.weight(1f).padding(8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                items(state.sessionList.size) { i ->
                    val s = state.sessionList[i]
                    val isActive = s["id"] == (try { vm.api.sessionId } catch (_: Exception) { "" })
                    val isShared = s["is_shared"] == "1"

                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(8.dp))
                            .background(if (isActive) Accent.copy(alpha = 0.12f) else Color.Transparent)
                            .then(if (isActive) Modifier.border(1.dp, Accent, RoundedCornerShape(8.dp)) else Modifier)
                            .combinedClickable(
                                onClick = { vm.switchToSession(s["id"] ?: "") },
                                onLongClick = { ctxMenuSession = s },
                            )
                            .padding(10.dp)
                    ) {
                        Column {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text(
                                    s["title"] ?: "New Chat",
                                    fontSize = 13.sp, fontWeight = FontWeight.Medium, color = TextPrimary,
                                    maxLines = 1, overflow = TextOverflow.Ellipsis,
                                    modifier = Modifier.weight(1f),
                                )
                                if (isShared) {
                                    Text("\uD83D\uDD17", fontSize = 11.sp, modifier = Modifier.padding(start = 4.dp))
                                }
                            }
                            // Metrics line
                            val tokIn = s["tokens_in"] ?: "0"
                            val tokOut = s["tokens_out"] ?: "0"
                            val metricsStr = if (tokIn != "0" || tokOut != "0") " · ${tokIn}/${tokOut} tok" else ""
                            Text(
                                "${s["message_count"] ?: "0"} msgs$metricsStr",
                                fontSize = 11.sp, color = TextDim,
                            )
                            val preview = s["last_message"] ?: ""
                            if (preview.isNotBlank()) {
                                Text(preview, fontSize = 11.sp, color = TextDim, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            }
                        }
                    }
                }
            }

            HorizontalDivider(color = BorderDark)
            Column(modifier = Modifier.padding(12.dp)) {
                OutlinedButton(
                    onClick = { vm.clearSession(); vm.toggleSessionDrawer() },
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(6.dp),
                    border = BorderStroke(1.dp, RedDark),
                ) { Text("Clear Current Chat", color = RedDark, fontSize = 12.sp) }
            }
        }
    }

    // Long-press context menu dialog
    ctxMenuSession?.let { session ->
        val sid = session["id"] ?: ""
        AlertDialog(
            onDismissRequest = { ctxMenuSession = null },
            containerColor = CardDark,
            title = {
                Text(session["title"] ?: "Chat", color = TextPrimary, fontSize = 14.sp,
                    fontWeight = FontWeight.Bold, maxLines = 1, overflow = TextOverflow.Ellipsis)
            },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    SessionCtxItem(Icons.Filled.Share, "Share") {
                        ctxMenuSession = null; vm.shareChat(sid, context)
                    }
                    SessionCtxItem(Icons.Filled.PersonAdd, "Add Collaborator") {
                        ctxMenuSession = null
                        Toast.makeText(context, "Use settings to invite collaborators", Toast.LENGTH_SHORT).show()
                    }
                    HorizontalDivider(color = BorderDark, modifier = Modifier.padding(vertical = 4.dp))
                    SessionCtxItem(Icons.Filled.Archive, "Archive") {
                        ctxMenuSession = null; vm.archiveChat(sid)
                    }
                    SessionCtxItem(Icons.Filled.FileDownload, "Export") {
                        ctxMenuSession = null; vm.exportSessionChat(sid, context)
                    }
                    HorizontalDivider(color = BorderDark, modifier = Modifier.padding(vertical = 4.dp))
                    SessionCtxItem(Icons.Filled.Edit, "Rename") {
                        ctxMenuSession = null
                        val currentTitle = session["title"] ?: "New Chat"
                        // Show a simple rename via AlertDialog builder
                        val builder = android.app.AlertDialog.Builder(context)
                        val input = android.widget.EditText(context)
                        input.setText(currentTitle)
                        builder.setTitle("Rename Chat")
                        builder.setView(input)
                        builder.setPositiveButton("Save") { _, _ ->
                            val newTitle = input.text.toString().trim()
                            if (newTitle.isNotEmpty()) vm.renameChat(sid, newTitle)
                        }
                        builder.setNegativeButton("Cancel", null)
                        builder.show()
                    }
                    SessionCtxItem(Icons.Filled.Delete, "Delete", RedDark) {
                        ctxMenuSession = null; vm.deleteChat(sid)
                    }
                }
            },
            confirmButton = {
                TextButton(onClick = { ctxMenuSession = null }) { Text("Cancel", color = TextDim) }
            },
        )
    }
}

@Composable
private fun SessionCtxItem(icon: ImageVector, label: String, color: Color = TextPrimary, onClick: () -> Unit) {
    Surface(onClick = onClick, color = Color.Transparent, shape = RoundedCornerShape(6.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 10.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(icon, contentDescription = null, tint = color.copy(alpha = 0.7f), modifier = Modifier.size(20.dp))
            Text(label, fontSize = 14.sp, color = color)
        }
    }
}

// --- Bottom Controls with condensed tools popup ---

@Composable
fun BottomControls(state: ChatUiState, vm: ChatViewModel) {
    var showToolsPopup by remember { mutableStateOf(false) }
    val enabledCount = state.toolToggles.count { it.value }

    Column(modifier = Modifier.background(CardDark)) {
        // Tools popup overlay
        AnimatedVisibility(visible = showToolsPopup) {
            Surface(
                modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 4.dp),
                shape = RoundedCornerShape(12.dp), color = CardDark,
                border = BorderStroke(1.dp, BorderDark),
                shadowElevation = 8.dp,
            ) {
                Column(modifier = Modifier.padding(12.dp)) {
                    // Core tools
                    Text("TOOLS", fontSize = 11.sp, fontWeight = FontWeight.Bold, color = Accent,
                        letterSpacing = 0.5.sp, modifier = Modifier.padding(bottom = 8.dp))
                    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        val coreToggles = listOf("web_search" to "Web", "file_read" to "Read", "file_write" to "Write", "shell" to "Shell")
                        coreToggles.forEach { (tool, label) ->
                            Box(modifier = Modifier.weight(1f)) {
                                ToggleChip(label = label, isOn = state.toolToggles[tool] ?: true, onClick = { vm.toggleTool(tool) })
                            }
                        }
                    }
                    Spacer(Modifier.height(8.dp))
                    HorizontalDivider(color = BorderDark)
                    Spacer(Modifier.height(8.dp))
                    // Multimodal + Git
                    Text("MULTIMODAL & GIT", fontSize = 11.sp, fontWeight = FontWeight.Bold, color = Accent,
                        letterSpacing = 0.5.sp, modifier = Modifier.padding(bottom = 6.dp))
                    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        val extraToggles = listOf("vision" to "Vision", "image_gen" to "Image", "voice" to "Voice", "git" to "Git")
                        extraToggles.forEach { (tool, label) ->
                            Box(modifier = Modifier.weight(1f)) {
                                ToggleChip(label = label, isOn = state.toolToggles[tool] ?: true, onClick = { vm.toggleTool(tool) })
                            }
                        }
                    }
                    Spacer(Modifier.height(8.dp))
                    HorizontalDivider(color = BorderDark)
                    Spacer(Modifier.height(8.dp))
                    // Acceleration
                    Text("ACCELERATION", fontSize = 11.sp, fontWeight = FontWeight.Bold, color = Accent,
                        letterSpacing = 0.5.sp, modifier = Modifier.padding(bottom = 6.dp))
                    ToggleChip(label = "BitNet", isOn = state.bitnetEnabled, activeColor = GreenDark,
                        onClick = { vm.toggleBitNet() })
                    Spacer(Modifier.height(4.dp))
                    ToggleChip(label = "Large Model (32B)", isOn = state.largeModelRouting,
                        activeColor = Color(0xFF42A5F5), onClick = { vm.toggleLargeModel() })
                    Spacer(Modifier.height(6.dp))
                    Text("Review-Revise \u2022 Code Validation \u2022 RAG \u2022 Reasoning Chain \u2014 always active",
                        fontSize = 9.sp, color = TextDim, modifier = Modifier.padding(start = 4.dp))
                    if (state.onDeviceAI) {
                        Spacer(Modifier.height(4.dp))
                        ToggleChip(
                            label = "On-Device NPU", isOn = state.onDeviceEnabled,
                            activeColor = Color(0xFFAB47BC),
                            onClick = { vm.toggleOnDeviceAI() },
                        )
                        Text(state.onDeviceNPU, fontSize = 9.sp, color = TextDim,
                            modifier = Modifier.padding(start = 4.dp, top = 2.dp))
                    }
                }
            }
        }

        // Smart reply suggestions (from on-device AI)
        if (state.smartReplies.isNotEmpty() && !state.isSending) {
            Row(
                modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState())
                    .padding(horizontal = 12.dp, vertical = 4.dp),
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                for (suggestion in state.smartReplies) {
                    Surface(
                        onClick = { vm.useSuggestion(suggestion) },
                        shape = RoundedCornerShape(16.dp),
                        color = Color.Transparent,
                        border = BorderStroke(1.dp, Color(0xFFAB47BC).copy(alpha = 0.6f)),
                    ) {
                        Text(suggestion, fontSize = 12.sp, color = Color(0xFFCE93D8),
                            modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp))
                    }
                }
            }
        }

        HorizontalDivider(color = BorderDark, thickness = 1.dp)
        // Compact toggle row
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            ToggleChip(
                label = if (state.executionMode == "execute") "Execute" else "Teach",
                isOn = state.executionMode == "execute",
                activeColor = if (state.executionMode == "execute") Accent else YellowDark,
                onClick = { vm.toggleMode() },
            )
            Box(modifier = Modifier.width(1.dp).height(20.dp).background(BorderDark))
            // Tools button with count badge
            Surface(
                onClick = { showToolsPopup = !showToolsPopup },
                shape = RoundedCornerShape(16.dp),
                color = Color.Transparent,
                border = BorderStroke(1.dp, if (showToolsPopup) Accent else BorderDark),
            ) {
                Row(
                    modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp),
                    horizontalArrangement = Arrangement.spacedBy(5.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(Icons.Filled.Build, contentDescription = null,
                        tint = if (showToolsPopup) Accent else TextDim, modifier = Modifier.size(12.dp))
                    Text("Tools", fontSize = 11.sp, color = if (showToolsPopup) Accent else TextDim)
                    Surface(
                        shape = CircleShape, color = Accent,
                        modifier = Modifier.size(16.dp),
                    ) {
                        Box(contentAlignment = Alignment.Center, modifier = Modifier.fillMaxSize()) {
                            Text("$enabledCount", fontSize = 9.sp, color = Color.White, fontWeight = FontWeight.Bold)
                        }
                    }
                }
            }
        }
        // Input row with file upload, image picker, and voice
        val context = LocalContext.current
        var isRecording by remember { mutableStateOf(false) }

        // File picker
        val filePicker = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri: Uri? ->
            uri?.let {
                try {
                    val resolver = context.contentResolver
                    val filename = uri.lastPathSegment ?: "upload"
                    val bytes = resolver.openInputStream(uri)?.readBytes() ?: return@let
                    vm.uploadFile(filename, bytes) { msg ->
                        Toast.makeText(context, msg, Toast.LENGTH_SHORT).show()
                    }
                } catch (e: Exception) {
                    Toast.makeText(context, "Upload failed: ${e.message}", Toast.LENGTH_SHORT).show()
                }
            }
        }
        // Image picker for vision analysis
        val imagePicker = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri: Uri? ->
            uri?.let {
                try {
                    val resolver = context.contentResolver
                    val filename = uri.lastPathSegment ?: "image.jpg"
                    val bytes = resolver.openInputStream(uri)?.readBytes() ?: return@let
                    vm.uploadFile(filename, bytes) { msg ->
                        if (msg.startsWith("Uploaded")) {
                            // Auto-send image for analysis
                            val currentInput = state.inputText.trim()
                            val prompt = if (currentInput.isNotEmpty()) currentInput else "Analyze this image and describe what you see"
                            vm.updateInput("[Image: $filename] $prompt")
                            vm.sendMessage()
                        }
                        Toast.makeText(context, msg, Toast.LENGTH_SHORT).show()
                    }
                } catch (e: Exception) {
                    Toast.makeText(context, "Image upload failed: ${e.message}", Toast.LENGTH_SHORT).show()
                }
            }
        }

        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(4.dp), verticalAlignment = Alignment.Bottom,
        ) {
            // File upload button
            IconButton(
                onClick = { filePicker.launch("*/*") },
                modifier = Modifier.size(48.dp),
            ) {
                Icon(Icons.Filled.Add, contentDescription = "Upload file", tint = TextDim, modifier = Modifier.size(20.dp))
            }
            // Image picker for vision
            IconButton(
                onClick = { imagePicker.launch("image/*") },
                modifier = Modifier.size(48.dp),
            ) {
                Icon(Icons.Filled.CameraAlt, contentDescription = "Analyze image", tint = TextDim, modifier = Modifier.size(20.dp))
            }
            // Voice input button
            IconButton(
                onClick = {
                    isRecording = !isRecording
                    if (isRecording) {
                        Toast.makeText(context, "Voice input: use the server's STT endpoint", Toast.LENGTH_SHORT).show()
                        // TODO: Integrate Android MediaRecorder + send to /api/voice/transcribe
                    }
                    isRecording = false
                },
                modifier = Modifier.size(48.dp),
            ) {
                Icon(
                    Icons.Filled.Mic,
                    contentDescription = "Voice input",
                    tint = if (isRecording) RedDark else TextDim,
                    modifier = Modifier.size(20.dp),
                )
            }
            OutlinedTextField(
                value = state.inputText, onValueChange = { vm.updateInput(it) },
                modifier = Modifier.weight(1f),
                placeholder = { Text("Enter task...", color = TextDim) },
                colors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor = Accent, unfocusedBorderColor = BorderDark,
                    cursorColor = Accent, focusedTextColor = Color.White, unfocusedTextColor = Color.White,
                    focusedContainerColor = BgDark, unfocusedContainerColor = BgDark,
                ),
                shape = RoundedCornerShape(8.dp), maxLines = 4,
            )
            Button(
                onClick = { vm.sendMessage() },
                enabled = !state.isSending && state.inputText.isNotBlank(),
                shape = RoundedCornerShape(8.dp),
                colors = ButtonDefaults.buttonColors(containerColor = Accent),
                contentPadding = PaddingValues(horizontal = 20.dp, vertical = 14.dp),
            ) { Text("GO", fontWeight = FontWeight.Bold) }
        }
    }
}

@Composable
fun ToggleChip(label: String, isOn: Boolean, activeColor: Color = Accent, onClick: () -> Unit) {
    Surface(
        onClick = onClick, shape = RoundedCornerShape(16.dp),
        color = if (isOn) activeColor.copy(alpha = 0.08f) else Color.Transparent,
        border = BorderStroke(1.dp, if (isOn) activeColor else BorderDark),
    ) {
        Row(modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp),
            horizontalArrangement = Arrangement.spacedBy(5.dp), verticalAlignment = Alignment.CenterVertically) {
            Box(modifier = Modifier.size(5.dp).clip(CircleShape).background(if (isOn) activeColor else TextDim))
            Text(label, fontSize = 11.sp, color = if (isOn) activeColor else TextDim)
        }
    }
}
