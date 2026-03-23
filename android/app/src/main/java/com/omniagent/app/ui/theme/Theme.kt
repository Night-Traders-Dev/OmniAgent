package com.omniagent.app.ui.theme

import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.graphics.Color

// Dark theme colors
val BgDark = Color(0xFF0D1117)
val CardDark = Color(0xFF161B22)
val BorderDark = Color(0xFF30363D)
val Accent = Color(0xFF58A6FF)
val TextPrimary = Color(0xFFC9D1D9)
val TextDim = Color(0xFF8B949E)
val GreenDark = Color(0xFF238636)
val YellowDark = Color(0xFFD29922)
val RedDark = Color(0xFFF85149)

// Light theme overrides
val BgLight = Color(0xFFFFFFFF)
val CardLight = Color(0xFFF6F8FA)
val BorderLight = Color(0xFFD0D7DE)
val TextPrimaryLight = Color(0xFF1F2328)
val TextDimLight = Color(0xFF656D76)

// Theme state
var isDarkTheme by mutableStateOf(true)

private val DarkColorScheme = darkColorScheme(
    primary = Accent,
    secondary = GreenDark,
    tertiary = YellowDark,
    background = BgDark,
    surface = CardDark,
    onPrimary = Color.White,
    onSecondary = Color.White,
    onBackground = TextPrimary,
    onSurface = TextPrimary,
    error = RedDark,
    outline = BorderDark,
    surfaceVariant = CardDark,
    onSurfaceVariant = TextDim,
)

private val LightColorScheme = lightColorScheme(
    primary = Accent,
    secondary = GreenDark,
    tertiary = YellowDark,
    background = BgLight,
    surface = CardLight,
    onPrimary = Color.White,
    onSecondary = Color.White,
    onBackground = TextPrimaryLight,
    onSurface = TextPrimaryLight,
    error = RedDark,
    outline = BorderLight,
    surfaceVariant = CardLight,
    onSurfaceVariant = TextDimLight,
)

@Composable
fun OmniAgentTheme(darkTheme: Boolean = isDarkTheme, content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = if (darkTheme) DarkColorScheme else LightColorScheme,
        typography = Typography(),
        content = content,
    )
}
