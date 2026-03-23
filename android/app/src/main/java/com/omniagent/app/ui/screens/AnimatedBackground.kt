package com.omniagent.app.ui.screens

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.BlendMode
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.platform.LocalDensity
import kotlin.math.PI
import kotlin.math.roundToInt
import kotlin.math.sin
import kotlin.random.Random
import java.util.TimeZone

/**
 * Smart Hub animated background port for Android chat.
 *
 * Mirrors the SDL implementation:
 * - deep gradient base with slow blue/rose tint shift
 * - 5 layered sine-wave fills with crest glow
 * - 80 drifting additive bokeh particles with pulse
 */

private data class Particle(
    val originX: Float,
    val originY: Float,
    val vx: Float,
    val vy: Float,
    val radius: Float,
    val alpha: Float,
    val pulsePhase: Float,
    val color: Color,
)

private data class Wave(
    val phaseOffset: Float,
    val yBase: Float,
    val amplitude: Float,
    val frequency: Float,
    val speed: Float,
    val color: Color,
)

private data class DayTheme(
    val top: Color,
    val bottom: Color,
    val accent: Color,
)

private data class DayThemeStop(
    val position: Float,
    val theme: DayTheme,
)

private val particlePalette = listOf(
    Color(100, 140, 220),
    Color(140, 100, 200),
    Color(80, 160, 180),
    Color(180, 120, 160),
    Color(100, 180, 140),
    Color(200, 150, 100),
    Color(120, 130, 200),
    Color(160, 100, 140),
)

private val smartHubWaves = listOf(
    Wave(phaseOffset = 0f, yBase = 0.15f, amplitude = 40f, frequency = 0.003f, speed = 0.75f, color = Color(60, 80, 160, 18)),
    Wave(phaseOffset = 1.2f, yBase = 0.22f, amplitude = 30f, frequency = 0.005f, speed = 0.60f, color = Color(100, 60, 160, 14)),
    Wave(phaseOffset = 2.5f, yBase = 0.10f, amplitude = 55f, frequency = 0.002f, speed = 0.85f, color = Color(40, 100, 140, 10)),
    Wave(phaseOffset = 0.8f, yBase = 0.30f, amplitude = 20f, frequency = 0.008f, speed = 0.45f, color = Color(120, 80, 120, 8)),
    Wave(phaseOffset = 3.0f, yBase = 0.18f, amplitude = 35f, frequency = 0.004f, speed = 0.55f, color = Color(80, 120, 100, 12)),
)

private val dayThemeStops = listOf(
    DayThemeStop(0f, DayTheme(Color(8, 10, 18), Color(16, 16, 30), Color(24, 18, 62))),
    DayThemeStop(0.22f, DayTheme(Color(14, 12, 22), Color(30, 18, 40), Color(88, 52, 92))),
    DayThemeStop(0.38f, DayTheme(Color(10, 14, 24), Color(20, 28, 42), Color(42, 94, 126))),
    DayThemeStop(0.60f, DayTheme(Color(8, 14, 24), Color(18, 26, 40), Color(26, 110, 92))),
    DayThemeStop(0.78f, DayTheme(Color(16, 11, 20), Color(34, 18, 32), Color(112, 66, 44))),
    DayThemeStop(0.90f, DayTheme(Color(10, 10, 20), Color(20, 14, 32), Color(68, 30, 88))),
    DayThemeStop(1f, DayTheme(Color(8, 10, 18), Color(16, 16, 30), Color(24, 18, 62))),
)

@Composable
fun AnimatedBackground(modifier: Modifier = Modifier) {
    val infiniteTransition = rememberInfiniteTransition(label = "smart_hub_background")
    val timeSeconds by infiniteTransition.animateFloat(
        initialValue = 0f,
        targetValue = 1000f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 1_000_000, easing = LinearEasing),
            repeatMode = RepeatMode.Restart,
        ),
        label = "smart_hub_time",
    )
    val density = LocalDensity.current

    BoxWithConstraints(modifier = modifier.fillMaxSize()) {
        val viewportWidth = with(density) { maxWidth.toPx() }.coerceAtLeast(1f)
        val viewportHeight = with(density) { maxHeight.toPx() }.coerceAtLeast(1f)
        val particleSeed = remember(viewportWidth.roundToInt(), viewportHeight.roundToInt()) {
            Random(1337)
        }
        val particles = remember(viewportWidth.roundToInt(), viewportHeight.roundToInt()) {
            MutableList(80) {
                Particle(
                    originX = particleSeed.nextFloat() * viewportWidth,
                    originY = particleSeed.nextFloat() * viewportHeight,
                    vx = particleSeed.nextFloat() * 16f - 8f,
                    vy = particleSeed.nextFloat() * 8f - 4f,
                    radius = particleSeed.nextFloat() * 18f + 2f,
                    alpha = particleSeed.nextFloat() * 0.12f + 0.03f,
                    pulsePhase = particleSeed.nextFloat() * (2f * PI.toFloat()),
                    color = particlePalette[particleSeed.nextInt(particlePalette.size)],
                )
            }
        }

        Canvas(modifier = Modifier.fillMaxSize()) {
            val dayTheme = currentDayTheme()
            drawRect(
                brush = Brush.verticalGradient(
                    colors = listOf(dayTheme.top, dayTheme.bottom),
                )
            )

            val overlayPulse = 0.85f + 0.15f * (sin(timeSeconds * 0.05f) * 0.5f + 0.5f)
            drawRect(
                color = dayTheme.accent.copy(alpha = (6f / 255f) * overlayPulse),
                blendMode = BlendMode.Plus,
            )

            smartHubWaves.forEach { wave ->
                drawSmartHubWave(
                    wave = wave.copy(color = tintColor(wave.color, dayTheme.accent, 0.18f)),
                    timeSeconds = timeSeconds,
                )
            }

            particles.forEach { particle ->
                val x = wrap(
                    value = particle.originX + particle.vx * timeSeconds,
                    min = -50f,
                    max = size.width + 50f,
                )
                val y = wrap(
                    value = particle.originY + particle.vy * timeSeconds,
                    min = -50f,
                    max = size.height + 50f,
                )
                val pulse = 0.6f + 0.4f * sin(particle.pulsePhase + timeSeconds * 1.5f)
                val alpha = particle.alpha * pulse
                val radius = particle.radius * (0.8f + 0.2f * pulse)
                drawSoftCircle(
                    center = Offset(x, y),
                    radius = radius,
                    color = tintColor(particle.color, dayTheme.accent, 0.24f),
                    alpha = alpha,
                )
            }
        }
    }
}

private fun DrawScope.drawSmartHubWave(wave: Wave, timeSeconds: Float) {
    val phase = wave.phaseOffset + wave.speed * timeSeconds
    val baseY = wave.yBase * size.height
    val step = 1f
    val fillPath = Path()
    val crestPath = Path()
    var x = 0f
    var firstPoint = true

    fillPath.moveTo(0f, size.height)

    while (x <= size.width + step) {
        val y = (
            baseY +
                sin(x * wave.frequency + phase) * wave.amplitude +
                sin(x * wave.frequency * 2.3f + phase * 1.7f) * wave.amplitude * 0.3f
            ).coerceIn(0f, size.height)

        if (firstPoint) {
            fillPath.lineTo(0f, y)
            crestPath.moveTo(0f, y)
            firstPoint = false
        } else {
            fillPath.lineTo(x, y)
            crestPath.lineTo(x, y)
        }

        x += step
    }

    fillPath.lineTo(size.width, size.height)
    fillPath.close()

    drawPath(
        path = fillPath,
        color = wave.color,
    )
    drawPath(
        path = crestPath,
        color = wave.color.copy(alpha = (wave.color.alpha * 3f).coerceAtMost(1f)),
        style = Stroke(
            width = 2.5f,
            cap = StrokeCap.Round,
            join = StrokeJoin.Round,
        ),
    )
    drawPath(
        path = crestPath,
        color = wave.color,
        style = Stroke(
            width = 1.2f,
            cap = StrokeCap.Round,
            join = StrokeJoin.Round,
        ),
    )
}

private fun DrawScope.drawSoftCircle(
    center: Offset,
    radius: Float,
    color: Color,
    alpha: Float,
) {
    drawCircle(
        brush = Brush.radialGradient(
            colorStops = arrayOf(
                0f to color.copy(alpha = alpha),
                0.45f to color.copy(alpha = alpha * 0.45f),
                0.8f to color.copy(alpha = alpha * 0.12f),
                1f to Color.Transparent,
            ),
            center = center,
            radius = radius,
        ),
        radius = radius,
        center = center,
        blendMode = BlendMode.Plus,
    )
    drawCircle(
        color = color.copy(alpha = alpha * 0.35f),
        radius = radius * 0.28f,
        center = center,
        blendMode = BlendMode.Plus,
    )
}

private fun wrap(value: Float, min: Float, max: Float): Float {
    val range = max - min
    if (range <= 0f) return min
    var wrapped = (value - min) % range
    if (wrapped < 0f) wrapped += range
    return wrapped + min
}

private fun currentDayTheme(nowMillis: Long = System.currentTimeMillis()): DayTheme {
    val offsetMillis = TimeZone.getDefault().getOffset(nowMillis).toLong()
    val localMillis = nowMillis + offsetMillis
    val dayProgress = ((localMillis % DAY_MILLIS) + DAY_MILLIS) % DAY_MILLIS / DAY_MILLIS.toFloat()
    return interpolateDayTheme(dayProgress)
}

private fun interpolateDayTheme(progress: Float): DayTheme {
    val clamped = progress.coerceIn(0f, 1f)
    val nextIndex = dayThemeStops.indexOfFirst { it.position >= clamped }.let { if (it == -1) dayThemeStops.lastIndex else it }
    val endStop = dayThemeStops[nextIndex]
    val startStop = dayThemeStops[(nextIndex - 1).coerceAtLeast(0)]
    val span = (endStop.position - startStop.position).takeIf { it > 0f } ?: 1f
    val t = ((clamped - startStop.position) / span).coerceIn(0f, 1f)
    return DayTheme(
        top = lerp(startStop.theme.top, endStop.theme.top, t),
        bottom = lerp(startStop.theme.bottom, endStop.theme.bottom, t),
        accent = lerp(startStop.theme.accent, endStop.theme.accent, t),
    )
}

private fun tintColor(base: Color, accent: Color, amount: Float): Color {
    val tinted = lerp(base.copy(alpha = 1f), accent.copy(alpha = 1f), amount.coerceIn(0f, 1f))
    return tinted.copy(alpha = base.alpha)
}

private const val DAY_MILLIS = 86_400_000L
