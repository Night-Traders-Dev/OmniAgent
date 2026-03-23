package com.omniagent.app.ui.screens

import androidx.compose.animation.core.*
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.BlendMode
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.DrawScope
import kotlin.math.*
import kotlin.random.Random

/**
 * PlayStation-style animated background with flowing sine waves and bokeh particles.
 * Port of the SmartHub C background to Jetpack Compose Canvas.
 *
 * Draws:
 *  - Dark gradient base with subtle color shift
 *  - 5 layered flowing sine waves
 *  - 60 drifting bokeh particles with pulsing glow
 */

private data class Particle(
    var x: Float, var y: Float,
    val vx: Float, val vy: Float,
    val radius: Float, val alpha: Float,
    val pulsePhase: Float,
    val color: Color,
)

private data class Wave(
    val speed: Float, val amplitude: Float,
    val frequency: Float, val yBase: Float,
    val color: Color,
)

private val palette = listOf(
    Color(100, 140, 220, 30),  // soft blue
    Color(140, 100, 200, 25),  // lavender
    Color(80, 160, 180, 20),   // teal
    Color(180, 120, 160, 22),  // rose
    Color(100, 180, 140, 18),  // mint
    Color(200, 150, 100, 20),  // warm amber
    Color(120, 130, 200, 25),  // periwinkle
    Color(160, 100, 140, 22),  // mauve
)

private val waves = listOf(
    Wave(0.15f, 40f, 0.003f, 0.75f, Color(60, 80, 160, 18)),
    Wave(0.22f, 30f, 0.005f, 0.60f, Color(100, 60, 160, 14)),
    Wave(0.10f, 55f, 0.002f, 0.85f, Color(40, 100, 140, 10)),
    Wave(0.30f, 20f, 0.008f, 0.45f, Color(120, 80, 120, 8)),
    Wave(0.18f, 35f, 0.004f, 0.55f, Color(80, 120, 100, 12)),
)

@Composable
fun AnimatedBackground(modifier: Modifier = Modifier) {
    // Time animation — infinite, smooth
    val infiniteTransition = rememberInfiniteTransition(label = "bg")
    val time by infiniteTransition.animateFloat(
        initialValue = 0f,
        targetValue = 1000f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 1000000, easing = LinearEasing),
            repeatMode = RepeatMode.Restart,
        ),
        label = "time",
    )

    // Initialize particles once
    val particles = remember {
        List(60) {
            Particle(
                x = Random.nextFloat() * 2000f,
                y = Random.nextFloat() * 2000f,
                vx = Random.nextFloat() * 16f - 8f,
                vy = Random.nextFloat() * 8f - 4f,
                radius = Random.nextFloat() * 18f + 2f,
                alpha = Random.nextFloat() * 0.12f + 0.03f,
                pulsePhase = Random.nextFloat() * 2f * PI.toFloat(),
                color = palette[Random.nextInt(palette.size)],
            )
        }.toMutableList()
    }

    Canvas(modifier = modifier.fillMaxSize()) {
        val w = size.width
        val h = size.height
        val t = time

        // Base gradient — deep dark blue-purple
        drawRect(
            brush = Brush.verticalGradient(
                colors = listOf(Color(8, 10, 18), Color(16, 16, 30)),
            )
        )

        // Subtle color shift
        val shift = sin(t * 0.05f) * 0.5f + 0.5f
        drawRect(
            color = Color(
                red = (20 * shift / 255f),
                green = 0f,
                blue = (20 * (1f - shift) / 255f),
                alpha = 0.02f,
            )
        )

        // Waves
        for (wave in waves) {
            drawWave(wave, t, w, h)
        }

        // Particles
        for (p in particles) {
            val px = (p.x + p.vx * t * 0.03f) % (w + 100f)
            val py = (p.y + p.vy * t * 0.03f) % (h + 100f)
            val pulse = 0.6f + 0.4f * sin(p.pulsePhase + t * 1.5f)
            val r = p.radius * (0.8f + 0.2f * pulse)
            val a = p.alpha * pulse

            drawCircle(
                color = p.color.copy(alpha = a),
                radius = r,
                center = Offset(px, py),
                blendMode = BlendMode.Plus,
            )
            // Soft outer glow
            drawCircle(
                color = p.color.copy(alpha = a * 0.3f),
                radius = r * 2f,
                center = Offset(px, py),
                blendMode = BlendMode.Plus,
            )
        }
    }
}

private fun DrawScope.drawWave(wave: Wave, time: Float, w: Float, h: Float) {
    val baseY = wave.yBase * h
    val phase = time * wave.speed

    // Draw wave as thin filled strips
    val step = 3f
    var x = 0f
    while (x < w) {
        val y = baseY +
            sin(x * wave.frequency + phase) * wave.amplitude +
            sin(x * wave.frequency * 2.3f + phase * 1.7f) * wave.amplitude * 0.3f

        drawRect(
            color = wave.color,
            topLeft = Offset(x, y),
            size = androidx.compose.ui.geometry.Size(step, h - y),
        )
        x += step
    }
}
