package com.omniagent.app.ui.screens

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.widget.Toast
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.*
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.DpOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.omniagent.app.ui.theme.*

/**
 * Renders markdown content in Compose. Handles:
 * - **bold**, *italic*, `inline code`
 * - ```code blocks```
 * - # headers (h1-h3)
 * - [links](url)
 * - - bullet lists
 * - > blockquotes
 */
@Composable
fun MarkdownText(
    text: String,
    context: Context = LocalContext.current,
    serverBaseUrl: String = "",
    sessionId: String = "",
) {
    val blocks = parseMarkdownBlocks(text)
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        for (block in blocks) {
            when (block) {
                is MdBlock.CodeBlock -> CodeBlockView(block.code, block.lang, context)
                is MdBlock.Header -> HeaderView(block.level, block.text, context)
                is MdBlock.Blockquote -> BlockquoteView(block.text, context)
                is MdBlock.ListItem -> ListItemView(block.text, block.ordered, block.index, context)
                is MdBlock.MediaBlock -> MediaCardView(block.url, block.name, block.type, context, serverBaseUrl, sessionId)
                is MdBlock.WeatherCard -> WeatherCardView(block)
                is MdBlock.ErrorCard -> ErrorCardView(block)
                is MdBlock.FileCard -> FileCardView(block)
                is MdBlock.GitCard -> GitCardView(block)
                is MdBlock.Paragraph -> InlineMarkdownText(block.text, context)
            }
        }
    }
}

// --- Block-level parsing ---

sealed class MdBlock {
    data class CodeBlock(val code: String, val lang: String) : MdBlock()
    data class Header(val level: Int, val text: String) : MdBlock()
    data class Blockquote(val text: String) : MdBlock()
    data class ListItem(val text: String, val ordered: Boolean, val index: Int) : MdBlock()
    data class Paragraph(val text: String) : MdBlock()
    data class MediaBlock(val url: String, val name: String, val type: String) : MdBlock()
    data class WeatherCard(val location: String, val temp: String, val feelsLike: String,
        val condition: String, val humidity: String, val wind: String,
        val forecast: List<ForecastDay>) : MdBlock()
    data class ErrorCard(val kind: String, val message: String) : MdBlock()
    data class FileCard(val path: String, val detail: String, val action: String) : MdBlock()
    data class GitCard(val files: List<GitFile>) : MdBlock()
}

data class ForecastDay(val date: String, val high: String, val low: String, val condition: String, val precip: String)
data class GitFile(val status: String, val path: String)

fun parseMarkdownBlocks(text: String): List<MdBlock> {
    val blocks = mutableListOf<MdBlock>()
    val lines = text.split("\n")
    var i = 0
    var orderedIdx = 0

    while (i < lines.size) {
        val line = lines[i]

        // Weather block — detect "WEATHER FOR ... RAW_JSON:{...}"
        if (line.startsWith("WEATHER FOR ")) {
            val weatherLines = mutableListOf(line)
            i++
            while (i < lines.size) {
                weatherLines.add(lines[i])
                if (lines[i].trim() == "}") break
                i++
            }
            i++
            val full = weatherLines.joinToString("\n")
            val jsonIdx = full.indexOf("RAW_JSON:")
            if (jsonIdx >= 0) {
                try {
                    val jsonStr = full.substring(jsonIdx + 9).trim()
                    val json = com.google.gson.JsonParser.parseString(jsonStr).asJsonObject
                    val cur = json.getAsJsonObject("current")
                    val fc = json.getAsJsonArray("forecast")?.map { it.asJsonObject }
                    blocks.add(MdBlock.WeatherCard(
                        location = cur?.get("location")?.asString ?: "",
                        temp = cur?.get("temperature_f")?.asString ?: "",
                        feelsLike = cur?.get("feels_like_f")?.asString ?: "",
                        condition = cur?.get("condition")?.asString ?: "",
                        humidity = cur?.get("humidity")?.asString ?: "",
                        wind = cur?.get("wind")?.asString ?: "",
                        forecast = fc?.map { d -> ForecastDay(
                            date = d.get("date")?.asString ?: "",
                            high = d.get("high_f")?.asString ?: "",
                            low = d.get("low_f")?.asString ?: "",
                            condition = d.get("condition")?.asString ?: "",
                            precip = d.get("precip_chance")?.asString ?: "",
                        )} ?: emptyList(),
                    ))
                    continue
                } catch (_: Throwable) {}
            }
            // Fallback: emit as paragraph
            blocks.add(MdBlock.Paragraph(full.substringBefore("RAW_JSON:").trim()))
            continue
        }

        // Error card — detect ERROR[kind]: message
        val errMatch = Regex("^ERROR\\[(\\w+)](?:\\s*\\(retryable\\))?:\\s*(.+)").find(line)
        if (errMatch != null) {
            blocks.add(MdBlock.ErrorCard(errMatch.groupValues[1], errMatch.groupValues[2]))
            i++; continue
        }

        // File operation card — detect "Wrote X bytes to path" or "Edited path"
        val writeMatch = Regex("^(?:Wrote|Written)\\s+(\\d+)\\s+bytes?\\s+to\\s+(\\S+)", RegexOption.IGNORE_CASE).find(line)
        if (writeMatch != null) {
            blocks.add(MdBlock.FileCard(writeMatch.groupValues[2], "${writeMatch.groupValues[1]} bytes written", "created"))
            i++; continue
        }
        val editMatch = Regex("^Edited\\s+(\\S+).*replaced", RegexOption.IGNORE_CASE).find(line)
        if (editMatch != null) {
            blocks.add(MdBlock.FileCard(editMatch.groupValues[1], "Text replaced", "edited"))
            i++; continue
        }

        // Git status card — detect consecutive lines like "M  src/file.py"
        val gitLineRe = Regex("^\\s*[MADURC?!]{1,2}\\s+\\S+")
        if (gitLineRe.matches(line.trim())) {
            val gitLines = mutableListOf(line)
            i++
            while (i < lines.size && gitLineRe.matches(lines[i].trim())) {
                gitLines.add(lines[i]); i++
            }
            val files = gitLines.mapNotNull { l ->
                val gm = Regex("^\\s*([MADURC?!]{1,2})\\s+(.+)").find(l.trim())
                gm?.let { GitFile(it.groupValues[1].trim(), it.groupValues[2].trim()) }
            }
            if (files.isNotEmpty()) { blocks.add(MdBlock.GitCard(files)); continue }
            // Fallback
            blocks.add(MdBlock.Paragraph(gitLines.joinToString("\n")))
            continue
        }

        // Code block (fenced)
        if (line.trimStart().startsWith("```")) {
            val lang = line.trimStart().removePrefix("```").trim()
            val codeLines = mutableListOf<String>()
            i++
            while (i < lines.size && !lines[i].trimStart().startsWith("```")) {
                codeLines.add(lines[i])
                i++
            }
            if (i < lines.size) i++ // skip closing ```
            blocks.add(MdBlock.CodeBlock(codeLines.joinToString("\n"), lang))
            orderedIdx = 0
            continue
        }

        // Header
        val headerMatch = Regex("^(#{1,3})\\s+(.+)").matchEntire(line.trim())
        if (headerMatch != null) {
            val level = headerMatch.groupValues[1].length
            blocks.add(MdBlock.Header(level, headerMatch.groupValues[2]))
            orderedIdx = 0
            i++
            continue
        }

        // Blockquote
        if (line.trimStart().startsWith("> ")) {
            blocks.add(MdBlock.Blockquote(line.trimStart().removePrefix("> ")))
            orderedIdx = 0
            i++
            continue
        }

        // Markdown image: ![alt](/uploads/xxx.png)
        val imgMatch = Regex("!\\[([^]]*)]\\((/uploads/[^)]+)\\)").find(line)
        if (imgMatch != null) {
            val url = imgMatch.groupValues[2]
            val name = url.substringAfterLast('/')
            blocks.add(MdBlock.MediaBlock(url, name, mediaTypeFromExt(name)))
            orderedIdx = 0
            i++
            continue
        }

        // Bare /uploads/ reference (e.g. "Audio generated: /uploads/tts_xxx.wav")
        val uploadMatch = Regex("(/uploads/[^\\s\"<)]+)").find(line)
        if (uploadMatch != null) {
            val url = uploadMatch.groupValues[1]
            val name = url.substringAfterLast('/')
            // Emit any text before the URL as paragraph, then the media block
            val prefix = line.substring(0, uploadMatch.range.first).trim()
            if (prefix.isNotEmpty()) blocks.add(MdBlock.Paragraph(prefix))
            blocks.add(MdBlock.MediaBlock(url, name, mediaTypeFromExt(name)))
            orderedIdx = 0
            i++
            continue
        }

        // Unordered list
        val ulMatch = Regex("^\\s*[-*+]\\s+(.+)").matchEntire(line)
        if (ulMatch != null) {
            blocks.add(MdBlock.ListItem(ulMatch.groupValues[1], ordered = false, index = 0))
            orderedIdx = 0
            i++
            continue
        }

        // Ordered list
        val olMatch = Regex("^\\s*(\\d+)[.)]+\\s+(.+)").matchEntire(line)
        if (olMatch != null) {
            orderedIdx++
            blocks.add(MdBlock.ListItem(olMatch.groupValues[2], ordered = true, index = orderedIdx))
            i++
            continue
        }

        // Empty line — skip
        if (line.isBlank()) {
            orderedIdx = 0
            i++
            continue
        }

        // Paragraph (accumulate consecutive non-blank lines)
        val paraLines = mutableListOf(line)
        i++
        while (i < lines.size && lines[i].isNotBlank()
            && !lines[i].trimStart().startsWith("```")
            && !lines[i].trimStart().startsWith("#")
            && !lines[i].trimStart().startsWith("> ")
            && !Regex("^\\s*[-*+]\\s+").containsMatchIn(lines[i])
            && !Regex("^\\s*\\d+[.)]\\s+").containsMatchIn(lines[i])
        ) {
            paraLines.add(lines[i])
            i++
        }
        blocks.add(MdBlock.Paragraph(paraLines.joinToString("\n")))
        orderedIdx = 0
    }

    return blocks
}

// --- Inline markdown (bold, italic, code, links) ---

fun parseInlineMarkdown(text: String): AnnotatedString {
    return buildAnnotatedString {
        var pos = 0
        val src = text

        while (pos < src.length) {
            // Bold: **text** or __text__
            if (pos + 1 < src.length && (src.substring(pos, pos + 2) == "**" || src.substring(pos, pos + 2) == "__")) {
                val delim = src.substring(pos, pos + 2)
                val end = src.indexOf(delim, pos + 2)
                if (end > pos + 2) {
                    withStyle(SpanStyle(fontWeight = FontWeight.Bold)) {
                        append(src.substring(pos + 2, end))
                    }
                    pos = end + 2
                    continue
                }
            }

            // Italic: *text* or _text_ (but not ** or __)
            if (src[pos] == '*' || src[pos] == '_') {
                val ch = src[pos]
                if (pos + 1 < src.length && src[pos + 1] != ch) {
                    val end = src.indexOf(ch, pos + 1)
                    if (end > pos + 1) {
                        withStyle(SpanStyle(fontStyle = FontStyle.Italic)) {
                            append(src.substring(pos + 1, end))
                        }
                        pos = end + 1
                        continue
                    }
                }
            }

            // Inline code: `text`
            if (src[pos] == '`') {
                val end = src.indexOf('`', pos + 1)
                if (end > pos + 1) {
                    withStyle(SpanStyle(
                        fontFamily = FontFamily.Monospace,
                        background = Color(0xFF1A1F29),
                        fontSize = 13.sp,
                    )) {
                        append(src.substring(pos + 1, end))
                    }
                    pos = end + 1
                    continue
                }
            }

            // Link: [text](url)
            if (src[pos] == '[') {
                val closeBracket = src.indexOf(']', pos + 1)
                if (closeBracket > pos + 1 && closeBracket + 1 < src.length && src[closeBracket + 1] == '(') {
                    val closeParen = src.indexOf(')', closeBracket + 2)
                    if (closeParen > closeBracket + 2) {
                        val linkText = src.substring(pos + 1, closeBracket)
                        val url = src.substring(closeBracket + 2, closeParen)
                        pushStringAnnotation("URL", url)
                        withStyle(SpanStyle(color = Color(0xFF58A6FF), textDecoration = TextDecoration.Underline)) {
                            append(linkText)
                        }
                        pop()
                        pos = closeParen + 1
                        continue
                    }
                }
            }

            // Bare URL
            if (pos + 7 < src.length && (src.substring(pos).startsWith("http://") || src.substring(pos).startsWith("https://"))) {
                val endUrl = run {
                    var e = pos
                    while (e < src.length && !src[e].isWhitespace() && src[e] != ')' && src[e] != ']' && src[e] != '>') e++
                    e
                }
                val url = src.substring(pos, endUrl)
                pushStringAnnotation("URL", url)
                withStyle(SpanStyle(color = Color(0xFF58A6FF), textDecoration = TextDecoration.Underline)) {
                    append(url)
                }
                pop()
                pos = endUrl
                continue
            }

            // Plain character
            append(src[pos])
            pos++
        }
    }
}

// --- Block renderers ---

@Composable
fun InlineMarkdownText(text: String, context: Context) {
    val annotated = parseInlineMarkdown(text)
    androidx.compose.foundation.text.ClickableText(
        text = annotated,
        style = TextStyle(color = TextPrimary, fontSize = 14.sp),
        onClick = { offset ->
            annotated.getStringAnnotations("URL", offset, offset).firstOrNull()?.let { anno ->
                try { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(anno.item))) }
                catch (_: Exception) {}
            }
        },
    )
}

@Composable
fun CodeBlockView(code: String, lang: String, context: Context) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .background(Color(0xFF0D1117), RoundedCornerShape(6.dp))
            .padding(1.dp)
    ) {
        Column {
            if (lang.isNotBlank()) {
                Row(
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 10.dp, vertical = 4.dp),
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    Text(lang, fontSize = 11.sp, color = TextDim, fontFamily = FontFamily.Monospace)
                    TextButton(
                        onClick = {
                            val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                            clipboard.setPrimaryClip(ClipData.newPlainText("code", code))
                            Toast.makeText(context, "Copied", Toast.LENGTH_SHORT).show()
                        },
                        contentPadding = PaddingValues(horizontal = 8.dp, vertical = 0.dp),
                    ) {
                        Text("Copy", fontSize = 11.sp, color = TextDim)
                    }
                }
            }
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .horizontalScroll(rememberScrollState())
                    .padding(horizontal = 10.dp, vertical = 8.dp)
            ) {
                Text(
                    text = code,
                    fontSize = 12.sp,
                    color = TextPrimary,
                    fontFamily = FontFamily.Monospace,
                    lineHeight = 18.sp,
                )
            }
        }
    }
}

@Composable
fun HeaderView(level: Int, text: String, context: Context) {
    val fontSize = when (level) {
        1 -> 18.sp
        2 -> 16.sp
        else -> 14.sp
    }
    val annotated = parseInlineMarkdown(text)
    androidx.compose.foundation.text.ClickableText(
        text = annotated,
        style = TextStyle(
            color = Color(0xFF58A6FF),
            fontSize = fontSize,
            fontWeight = FontWeight.Bold,
        ),
        onClick = { offset ->
            annotated.getStringAnnotations("URL", offset, offset).firstOrNull()?.let { anno ->
                try { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(anno.item))) }
                catch (_: Exception) {}
            }
        },
    )
}

@Composable
fun BlockquoteView(text: String, context: Context) {
    Row(modifier = Modifier.fillMaxWidth().height(IntrinsicSize.Min)) {
        Box(
            modifier = Modifier
                .width(3.dp)
                .fillMaxHeight()
                .background(Color(0xFF58A6FF))
        )
        Spacer(Modifier.width(8.dp))
        InlineMarkdownText(text, context)
    }
}

@Composable
fun ListItemView(text: String, ordered: Boolean, index: Int, context: Context) {
    Row(modifier = Modifier.padding(start = 12.dp)) {
        Text(
            if (ordered) "$index. " else "• ",
            fontSize = 14.sp, color = TextDim,
        )
        InlineMarkdownText(text, context)
    }
}

// --- Media helpers ---

private val imgExts = setOf(".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp")
private val audioExts = setOf(".wav", ".mp3", ".ogg", ".flac", ".m4a")
private val videoExts = setOf(".mp4", ".webm", ".mov", ".avi")

fun mediaTypeFromExt(filename: String): String {
    val ext = filename.substringAfterLast('.', "").lowercase()
    return when {
        ".$ext" in imgExts -> "image"
        ".$ext" in audioExts -> "audio"
        ".$ext" in videoExts -> "video"
        else -> "file"
    }
}

private fun resolveMediaUrl(url: String, serverBaseUrl: String, sessionId: String): String {
    val base = serverBaseUrl.trimEnd('/')
    val resolved = if (url.startsWith("/uploads/") && base.isNotEmpty()) "$base$url" else url
    if (!resolved.contains("/uploads/") || sessionId.isBlank()) return resolved
    val separator = if (resolved.contains("?")) "&" else "?"
    return resolved + separator + "session_id=" + Uri.encode(sessionId)
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun MediaCardView(
    url: String,
    name: String,
    mediaType: String,
    context: Context,
    serverBaseUrl: String,
    sessionId: String,
) {
    var showMenu by remember { mutableStateOf(false) }
    val fullUrl = resolveMediaUrl(url, serverBaseUrl, sessionId)

    Box {
        Surface(
            shape = RoundedCornerShape(8.dp),
            color = Color(0xFF0D1117),
            border = BorderStroke(1.dp, BorderDark),
            modifier = Modifier
                .fillMaxWidth()
                .combinedClickable(
                    onClick = {
                        try { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(fullUrl))) }
                        catch (_: Exception) {}
                    },
                    onLongClick = { showMenu = true },
                ),
        ) {
            Column(modifier = Modifier.padding(10.dp)) {
                val icon = when (mediaType) { "image" -> "\uD83D\uDDBC"; "audio" -> "\uD83D\uDD0A"; "video" -> "\uD83C\uDFAC"; else -> "\uD83D\uDCCE" }
                val label = when (mediaType) { "image" -> "Image \u2022 Tap to view"; "audio" -> "Audio \u2022 Tap to play"; "video" -> "Video \u2022 Tap to play"; else -> "${name.substringAfterLast('.', "").uppercase()} file \u2022 Tap to open" }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(icon, fontSize = 20.sp)
                    Spacer(Modifier.width(8.dp))
                    Column(modifier = Modifier.weight(1f)) {
                        Text(name, fontSize = 13.sp, color = TextPrimary, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text(label, fontSize = 11.sp, color = TextDim)
                    }
                }
            }
        }

        // Long-press context menu
        DropdownMenu(expanded = showMenu, onDismissRequest = { showMenu = false }, containerColor = CardDark, offset = DpOffset(0.dp, 0.dp)) {
            DropdownMenuItem(
                text = { Text("Download", color = TextPrimary, fontSize = 13.sp) },
                onClick = {
                    showMenu = false
                    try {
                        val dm = context.getSystemService(Context.DOWNLOAD_SERVICE) as android.app.DownloadManager
                        val req = android.app.DownloadManager.Request(Uri.parse(fullUrl))
                            .setTitle(name)
                            .setNotificationVisibility(android.app.DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
                            .setDestinationInExternalPublicDir(android.os.Environment.DIRECTORY_DOWNLOADS, name)
                        dm.enqueue(req)
                        Toast.makeText(context, "Downloading $name", Toast.LENGTH_SHORT).show()
                    } catch (e: Exception) {
                        Toast.makeText(context, "Download failed: ${e.message}", Toast.LENGTH_SHORT).show()
                    }
                },
                leadingIcon = { Icon(Icons.Filled.ArrowDropDown, null, tint = TextDim, modifier = Modifier.size(18.dp)) },
            )
            DropdownMenuItem(
                text = { Text("Share", color = TextPrimary, fontSize = 13.sp) },
                onClick = {
                    showMenu = false
                    val shareIntent = Intent(Intent.ACTION_SEND)
                    shareIntent.type = "text/plain"
                    shareIntent.putExtra(Intent.EXTRA_TEXT, fullUrl)
                    context.startActivity(Intent.createChooser(shareIntent, "Share"))
                },
                leadingIcon = { Icon(Icons.Filled.Share, null, tint = TextDim, modifier = Modifier.size(18.dp)) },
            )
            DropdownMenuItem(
                text = { Text("Reference in Chat", color = TextPrimary, fontSize = 13.sp) },
                onClick = {
                    showMenu = false
                    val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                    clipboard.setPrimaryClip(ClipData.newPlainText("media_ref", url))
                    Toast.makeText(context, "Copied path \u2014 paste in chat", Toast.LENGTH_SHORT).show()
                },
                leadingIcon = { Icon(Icons.Filled.Chat, null, tint = TextDim, modifier = Modifier.size(18.dp)) },
            )
            HorizontalDivider(color = BorderDark)
            DropdownMenuItem(
                text = { Text("Delete", color = RedDark, fontSize = 13.sp) },
                onClick = {
                    showMenu = false
                    Toast.makeText(context, "Delete from server not yet supported on Android", Toast.LENGTH_SHORT).show()
                },
                leadingIcon = { Icon(Icons.Filled.Delete, null, tint = RedDark, modifier = Modifier.size(18.dp)) },
            )
        }
    }
}

// ═══ Rich Card Composables ═══

private val WeatherBgTop = Color(0xFF1A2A4A)
private val WeatherBgBot = Color(0xFF1E3A5F)
private val WeatherAccent = Color(0xFF4A9EFF)
private val WeatherDim = Color(0xFF8AB4E0)
private val WeatherText = Color(0xFFCCDDEE)

private fun weatherIcon(condition: String): String {
    val c = condition.lowercase()
    return when {
        "clear" in c || "sunny" in c || "fair" in c -> "\u2600\uFE0F"
        "partly" in c -> "\u26C5"
        "overcast" in c || "cloudy" in c -> "\u2601\uFE0F"
        "thunder" in c || "storm" in c -> "\u26C8\uFE0F"
        "rain" in c || "drizzle" in c || "shower" in c -> "\uD83C\uDF27\uFE0F"
        "snow" in c || "blizzard" in c || "flurr" in c -> "\u2744\uFE0F"
        "fog" in c || "mist" in c || "haze" in c -> "\uD83C\uDF2B\uFE0F"
        "wind" in c -> "\uD83D\uDCA8"
        "sleet" in c || "ice" in c || "freez" in c -> "\uD83E\uDDCA"
        else -> "\uD83C\uDF21\uFE0F"
    }
}

private fun dayName(dateStr: String): String = try {
    val parts = dateStr.split("-")
    val cal = java.util.GregorianCalendar(parts[0].toInt(), parts[1].toInt() - 1, parts[2].toInt())
    java.text.SimpleDateFormat("EEE", java.util.Locale.getDefault()).format(cal.time)
} catch (_: Throwable) { dateStr }

private fun skyGradient(condition: String): List<Color> {
    val c = condition.lowercase()
    val hour = java.util.Calendar.getInstance().get(java.util.Calendar.HOUR_OF_DAY)
    val night = hour < 6 || hour >= 20
    val golden = (hour in 6..7) || (hour in 17..19)

    return when {
        night && ("cloud" in c || "overcast" in c) -> listOf(Color(0xFF0F1220), Color(0xFF141830), Color(0xFF192030))
        night -> listOf(Color(0xFF080C1E), Color(0xFF0C122D), Color(0xFF121937))
        "rain" in c || "drizzle" in c || "shower" in c -> listOf(Color(0xFF283240), Color(0xFF374150), Color(0xFF46505F))
        "thunder" in c || "storm" in c -> listOf(Color(0xFF191622), Color(0xFF282338), Color(0xFF373246))
        "snow" in c || "blizzard" in c -> listOf(Color(0xFF8C9BAF), Color(0xFFA0AFC3), Color(0xFFB4C3D2))
        "fog" in c || "mist" in c -> listOf(Color(0xFF50555F), Color(0xFF646973), Color(0xFF787D84))
        "overcast" in c || "cloud" in c -> listOf(Color(0xFF374150), Color(0xFF4B5564), Color(0xFF5A6473))
        golden -> listOf(Color(0xFF32508C), Color(0xFF8C6446), Color(0xFFC8823C))
        "partly" in c -> listOf(Color(0xFF2D55A0), Color(0xFF5073B4), Color(0xFF6E96C8))
        else -> listOf(Color(0xFF1E50B4), Color(0xFF3C78D2), Color(0xFF64AAF0)) // clear/sunny
    }
}

@Composable
fun WeatherCardView(card: MdBlock.WeatherCard) {
    val skyColors = skyGradient(card.condition)
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(Brush.verticalGradient(skyColors))
    ) {
        // Semi-transparent overlay at bottom for text readability
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .align(Alignment.BottomCenter)
                .height(40.dp)
                .background(Color(0, 0, 0, 60))
        )
        Column(modifier = Modifier.padding(16.dp)) {
            // Header: location + icon
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text("\uD83D\uDCCD ${card.location}", fontSize = 12.sp, color = Color(0xFFB4D4F0),
                    fontWeight = FontWeight.Medium, letterSpacing = 0.5.sp)
                Text(weatherIcon(card.condition), fontSize = 28.sp)
            }
            // Big temperature
            Row(verticalAlignment = Alignment.Bottom, modifier = Modifier.padding(vertical = 4.dp)) {
                Text(card.temp, fontSize = 36.sp, fontWeight = FontWeight.Thin, color = Color.White,
                    letterSpacing = (-2).sp)
                Spacer(Modifier.width(8.dp))
                Text(card.condition, fontSize = 14.sp, color = WeatherText,
                    modifier = Modifier.padding(bottom = 6.dp))
            }
            // Details row
            HorizontalDivider(color = Color(0xFF2A4A6A), modifier = Modifier.padding(vertical = 8.dp))
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly) {
                WeatherDetail("Feels Like", card.feelsLike)
                WeatherDetail("Humidity", card.humidity)
                WeatherDetail("Wind", card.wind)
            }
            HorizontalDivider(color = Color(0xFF2A4A6A), modifier = Modifier.padding(vertical = 8.dp))
            // Forecast
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly) {
                card.forecast.take(5).forEach { day ->
                    Column(horizontalAlignment = Alignment.CenterHorizontally,
                        modifier = Modifier
                            .background(Color(0x10FFFFFF), RoundedCornerShape(8.dp))
                            .padding(horizontal = 8.dp, vertical = 6.dp)) {
                        Text(dayName(day.date), fontSize = 10.sp, color = WeatherDim)
                        Text(weatherIcon(day.condition), fontSize = 16.sp)
                        Text(day.high, fontSize = 12.sp, color = WeatherText)
                        Text(day.low, fontSize = 11.sp, color = Color(0xFF6A8AAA))
                        Text("\uD83D\uDCA7${day.precip}", fontSize = 9.sp, color = WeatherAccent)
                    }
                }
            }
        }
    }
}

@Composable
private fun WeatherDetail(label: String, value: String) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(label, fontSize = 10.sp, color = WeatherDim)
        Text(value, fontSize = 13.sp, color = WeatherText, fontWeight = FontWeight.Medium)
    }
}

@Composable
fun ErrorCardView(card: MdBlock.ErrorCard) {
    Surface(
        shape = RoundedCornerShape(12.dp),
        color = Color(0xFF3A1A1A),
        border = BorderStroke(1.dp, Color(0xFF5A2A2A)),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(modifier = Modifier.padding(14.dp), verticalAlignment = Alignment.Top) {
            Text("\u26A0\uFE0F", fontSize = 18.sp, modifier = Modifier.padding(end = 10.dp))
            Column {
                Text(card.kind, fontSize = 13.sp, color = Color(0xFFFF8A8A), fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.height(2.dp))
                Text(card.message, fontSize = 13.sp, color = Color(0xFFCCAAAA), lineHeight = 18.sp)
            }
        }
    }
}

@Composable
fun FileCardView(card: MdBlock.FileCard) {
    val (bg, borderColor, icon) = when (card.action) {
        "created" -> Triple(Color(0xFF1A2A1A), Color(0xFF2A4A2A), "\uD83D\uDCC4")
        "edited" -> Triple(Color(0xFF2A2A1A), Color(0xFF4A4A2A), "\u270F\uFE0F")
        "deleted" -> Triple(Color(0xFF2A1A1A), Color(0xFF4A2A2A), "\uD83D\uDDD1\uFE0F")
        else -> Triple(CardDark, BorderDark, "\uD83D\uDCC4")
    }
    Surface(
        shape = RoundedCornerShape(12.dp), color = bg,
        border = BorderStroke(1.dp, borderColor),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(modifier = Modifier.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(icon, fontSize = 22.sp, modifier = Modifier.padding(end = 10.dp))
            Column {
                Text(card.path, fontSize = 13.sp, color = WeatherText, fontFamily = FontFamily.Monospace,
                    maxLines = 2, overflow = TextOverflow.Ellipsis)
                Text(card.detail, fontSize = 11.sp, color = WeatherDim)
            }
        }
    }
}

@Composable
fun GitCardView(card: MdBlock.GitCard) {
    Surface(
        shape = RoundedCornerShape(12.dp),
        color = Color(0xFF1A1A2A),
        border = BorderStroke(1.dp, Color(0xFF3A3A5A)),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(modifier = Modifier.padding(14.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(bottom = 8.dp)) {
                Text("\uD83D\uDD00", fontSize = 16.sp, modifier = Modifier.padding(end = 8.dp))
                Text("Git Status \u2014 ${card.files.size} file${if (card.files.size != 1) "s" else ""}",
                    fontSize = 13.sp, color = WeatherText, fontWeight = FontWeight.SemiBold)
            }
            card.files.forEach { f ->
                val statusColor = when (f.status.firstOrNull()) {
                    'M' -> Color(0xFFE8AB4A)
                    'A' -> Color(0xFF3FB950)
                    'D' -> Color(0xFFFF4A4A)
                    '?' -> Color(0xFF8A8A8A)
                    else -> TextDim
                }
                Row(modifier = Modifier.padding(vertical = 2.dp)) {
                    Text(f.status, fontSize = 12.sp, color = statusColor, fontWeight = FontWeight.Bold,
                        fontFamily = FontFamily.Monospace, modifier = Modifier.width(24.dp))
                    Text(f.path, fontSize = 12.sp, color = TextPrimary, fontFamily = FontFamily.Monospace,
                        maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            }
        }
    }
}
