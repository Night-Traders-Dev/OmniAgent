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
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.BlendMode
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.platform.LocalDensity
import kotlin.math.PI
import kotlin.math.roundToInt
import kotlin.math.sin
import kotlin.random.Random

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
            drawRect(
                brush = Brush.verticalGradient(
                    colors = listOf(Color(8, 10, 18), Color(16, 16, 30)),
                )
            )

            val shift = sin(timeSeconds * 0.05f) * 0.5f + 0.5f
            val tintR = 20f * shift
            val tintB = 20f * (1f - shift)
            drawRect(
                color = Color(
                    red = tintR / 255f,
                    green = 0f,
                    blue = tintB / 255f,
                    alpha = 3f / 255f,
                ),
                blendMode = BlendMode.Plus,
            )

            smartHubWaves.forEach { wave ->
                drawSmartHubWave(wave = wave, timeSeconds = timeSeconds)
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
                    color = particle.color,
                    alpha = alpha,
                )
            }
        }
    }
}

private fun DrawScope.drawSmartHubWave(wave: Wave, timeSeconds: Float) {
    val phase = wave.phaseOffset + wave.speed * timeSeconds
    val baseY = wave.yBase * size.height
    val step = 2f
    var prevPoint: Offset? = null
    var x = 0f

    while (x < size.width) {
        val y = baseY +
            sin(x * wave.frequency + phase) * wave.amplitude +
            sin(x * wave.frequency * 2.3f + phase * 1.7f) * wave.amplitude * 0.3f

        drawRect(
            color = wave.color,
            topLeft = Offset(x, y.coerceIn(0f, size.height)),
            size = Size(step, (size.height - y).coerceAtLeast(0f)),
        )

        prevPoint?.let { previous ->
            drawLine(
                color = wave.color.copy(alpha = (wave.color.alpha * 3f).coerceAtMost(1f)),
                start = previous,
                end = Offset(x, y),
                strokeWidth = 2.5f,
            )
            drawLine(
                color = wave.color,
                start = previous,
                end = Offset(x, y),
                strokeWidth = 1.2f,
            )
        }

        prevPoint = Offset(x, y)
        x += step
    }
}

private fun DrawScope.drawSoftCircle(
    center: Offset,
    radius: Float,
    color: Color,
    alpha: Float,
) {
    val layers = (radius / 2f).roundToInt().coerceIn(2, 8)
    for (layer in layers downTo 0) {
        val t = layer / layers.toFloat()
        val layerRadius = radius * (0.3f + 0.7f * t)
        val layerAlpha = alpha * (1f - t * 0.8f)
        if (layerAlpha <= 0.002f) continue
        drawCircle(
            color = color.copy(alpha = layerAlpha),
            radius = layerRadius,
            center = center,
            blendMode = BlendMode.Plus,
        )
    }
}

private fun wrap(value: Float, min: Float, max: Float): Float {
    val range = max - min
    if (range <= 0f) return min
    var wrapped = (value - min) % range
    if (wrapped < 0f) wrapped += range
    return wrapped + min
}
