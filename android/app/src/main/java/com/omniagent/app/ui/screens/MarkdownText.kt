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
fun MarkdownText(text: String, context: Context = LocalContext.current) {
    val blocks = parseMarkdownBlocks(text)
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        for (block in blocks) {
            when (block) {
                is MdBlock.CodeBlock -> CodeBlockView(block.code, block.lang, context)
                is MdBlock.Header -> HeaderView(block.level, block.text, context)
                is MdBlock.Blockquote -> BlockquoteView(block.text, context)
                is MdBlock.ListItem -> ListItemView(block.text, block.ordered, block.index, context)
                is MdBlock.MediaBlock -> MediaCardView(block.url, block.name, block.type, context)
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
    data class MediaBlock(val url: String, val name: String, val type: String) : MdBlock() // image, audio, video, file
}

fun parseMarkdownBlocks(text: String): List<MdBlock> {
    val blocks = mutableListOf<MdBlock>()
    val lines = text.split("\n")
    var i = 0
    var orderedIdx = 0

    while (i < lines.size) {
        val line = lines[i]

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

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun MediaCardView(url: String, name: String, mediaType: String, context: Context) {
    var showMenu by remember { mutableStateOf(false) }
    val fullUrl = url // relative — resolved by caller if needed

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
