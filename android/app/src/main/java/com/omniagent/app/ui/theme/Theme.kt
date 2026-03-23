package com.omniagent.app.ui.theme

import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

val BgDark = Color(0xFF0D1117)
val CardDark = Color(0xFF161B22)
val BorderDark = Color(0xFF30363D)
val Accent = Color(0xFF58A6FF)
val TextPrimary = Color(0xFFC9D1D9)
val TextDim = Color(0xFF8B949E)
val GreenDark = Color(0xFF238636)
val YellowDark = Color(0xFFD29922)
val RedDark = Color(0xFFF85149)

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

@Composable
fun OmniAgentTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = DarkColorScheme,
        typography = Typography(),
        content = content,
    )
}
