/*
 * OmniAgent Smart Hub — Animated Background
 *
 * PS3/PS4/PS5-inspired procedural animation:
 *   - Layered flowing sine waves with soft glow
 *   - Drifting bokeh particles with gentle pulse
 *   - Deep gradient base color that subtly shifts
 *
 * Runs entirely on CPU via SDL2 renderer with alpha blending.
 * Designed to be lightweight enough for the IMG BXE-2-32 GPU
 * on the OrangePi RV2 at 30fps.
 */
#include "background.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

/* ═══ Random helpers ═══ */
static float randf(void) { return (float)rand() / (float)RAND_MAX; }
static float randf_range(float lo, float hi) { return lo + randf() * (hi - lo); }

/* ═══ Color palettes ═══ */
/* Deep ocean / aurora theme (warm-cool mix, cozy feel) */
typedef struct { Uint8 r, g, b; } RGB;
typedef struct {
    float position;
    RGB top;
    RGB bottom;
    RGB accent;
} ThemeStop;

static const RGB palette[] = {
    {100, 140, 220},  /* soft blue */
    {140, 100, 200},  /* lavender */
    {80,  160, 180},  /* teal */
    {180, 120, 160},  /* rose */
    {100, 180, 140},  /* mint */
    {200, 150, 100},  /* warm amber */
    {120, 130, 200},  /* periwinkle */
    {160, 100, 140},  /* mauve */
};
#define PALETTE_SIZE (sizeof(palette) / sizeof(palette[0]))

static const ThemeStop theme_stops[] = {
    {0.00f, {8, 10, 18}, {16, 16, 30}, {24, 18, 62}},
    {0.22f, {14, 12, 22}, {30, 18, 40}, {88, 52, 92}},
    {0.38f, {10, 14, 24}, {20, 28, 42}, {42, 94, 126}},
    {0.60f, {8, 14, 24}, {18, 26, 40}, {26, 110, 92}},
    {0.78f, {16, 11, 20}, {34, 18, 32}, {112, 66, 44}},
    {0.90f, {10, 10, 20}, {20, 14, 32}, {68, 30, 88}},
    {1.00f, {8, 10, 18}, {16, 16, 30}, {24, 18, 62}},
};
#define THEME_STOP_COUNT (sizeof(theme_stops) / sizeof(theme_stops[0]))

/* ═══ Theme helpers ═══ */

static Uint8 lerp_u8(Uint8 a, Uint8 b, float t) {
    return (Uint8)(a + (b - a) * t);
}

static RGB lerp_rgb(RGB a, RGB b, float t) {
    RGB out = {
        lerp_u8(a.r, b.r, t),
        lerp_u8(a.g, b.g, t),
        lerp_u8(a.b, b.b, t),
    };
    return out;
}

static RGB tint_rgb(RGB base, RGB accent, float amount) {
    return lerp_rgb(base, accent, amount);
}

static float current_day_progress(void) {
    time_t now = time(NULL);
    struct tm local_tm;
#if defined(_POSIX_VERSION)
    localtime_r(&now, &local_tm);
#else
    struct tm *tmp = localtime(&now);
    if (!tmp) return 0.0f;
    local_tm = *tmp;
#endif
    float seconds =
        (float)local_tm.tm_hour * 3600.0f +
        (float)local_tm.tm_min * 60.0f +
        (float)local_tm.tm_sec;
    return seconds / 86400.0f;
}

static void sample_day_theme(float progress, RGB *top, RGB *bottom, RGB *accent) {
    float clamped = progress;
    if (clamped < 0.0f) clamped = 0.0f;
    if (clamped > 1.0f) clamped = 1.0f;

    int next = 1;
    while (next < (int)THEME_STOP_COUNT && theme_stops[next].position < clamped) next++;
    if (next >= (int)THEME_STOP_COUNT) next = (int)THEME_STOP_COUNT - 1;
    int prev = next > 0 ? next - 1 : 0;

    float span = theme_stops[next].position - theme_stops[prev].position;
    float t = span > 0.0f ? (clamped - theme_stops[prev].position) / span : 0.0f;

    *top = lerp_rgb(theme_stops[prev].top, theme_stops[next].top, t);
    *bottom = lerp_rgb(theme_stops[prev].bottom, theme_stops[next].bottom, t);
    *accent = lerp_rgb(theme_stops[prev].accent, theme_stops[next].accent, t);
}

/* ═══ Initialization ═══ */

static void init_particle(BGParticle *p, int w, int h) {
    RGB c = palette[rand() % PALETTE_SIZE];
    p->x = randf() * w;
    p->y = randf() * h;
    p->vx = randf_range(-8.0f, 8.0f);
    p->vy = randf_range(-4.0f, 4.0f);
    p->radius = randf_range(2.0f, 20.0f);
    p->alpha = randf_range(0.03f, 0.15f);
    p->pulse_phase = randf() * (float)(2.0 * M_PI);
    p->r = c.r;
    p->g = c.g;
    p->b = c.b;
}

void bg_init(AnimatedBG *bg) {
    memset(bg, 0, sizeof(AnimatedBG));

    /* Deep dark blue-purple base */
    bg->bg_r = 8;
    bg->bg_g = 10;
    bg->bg_b = 18;

    /* Particles */
    bg->particle_count = BG_MAX_PARTICLES;
    for (int i = 0; i < bg->particle_count; i++) {
        init_particle(&bg->particles[i], 1920, 1080); /* max expected size */
    }

    /* Waves — layered sine waves at different depths */
    bg->wave_count = BG_MAX_WAVES;

    bg->waves[0] = (BGWave){0, 0.15f, 40.0f, 0.003f, 0.75f, 60, 80, 160, 18};
    bg->waves[1] = (BGWave){1.2f, 0.22f, 30.0f, 0.005f, 0.6f, 100, 60, 160, 14};
    bg->waves[2] = (BGWave){2.5f, 0.10f, 55.0f, 0.002f, 0.85f, 40, 100, 140, 10};
    bg->waves[3] = (BGWave){0.8f, 0.30f, 20.0f, 0.008f, 0.45f, 120, 80, 120, 8};
    bg->waves[4] = (BGWave){3.0f, 0.18f, 35.0f, 0.004f, 0.55f, 80, 120, 100, 12};

    bg->initialized = true;
}

/* ═══ Update ═══ */

void bg_update(AnimatedBG *bg, float dt) {
    bg->time += dt;

    /* Update particles */
    for (int i = 0; i < bg->particle_count; i++) {
        BGParticle *p = &bg->particles[i];
        p->x += p->vx * dt;
        p->y += p->vy * dt;
        p->pulse_phase += dt * 1.5f;

        /* Wrap around screen edges with margin */
        if (p->x < -50) p->x += 1970;
        if (p->x > 1970) p->x -= 1970;
        if (p->y < -50) p->y += 1130;
        if (p->y > 1130) p->y -= 1130;
    }

    /* Update wave phases */
    for (int i = 0; i < bg->wave_count; i++) {
        bg->waves[i].phase += bg->waves[i].speed * dt;
    }
}

/* ═══ Rendering ═══ */

static void render_soft_circle(SDL_Renderer *ren, int cx, int cy, float radius,
                                Uint8 r, Uint8 g, Uint8 b, float alpha) {
    /* Draw concentric circles with decreasing alpha for a soft glow effect */
    int layers = (int)(radius / 2.0f);
    if (layers < 2) layers = 2;
    if (layers > 8) layers = 8;

    for (int l = layers; l >= 0; l--) {
        float t = (float)l / (float)layers;
        float lr = radius * (0.3f + 0.7f * t);
        float la = alpha * (1.0f - t * 0.8f);
        Uint8 a = (Uint8)(la * 255.0f);
        if (a < 1) continue;

        SDL_SetRenderDrawBlendMode(ren, SDL_BLENDMODE_ADD);
        SDL_SetRenderDrawColor(ren, r, g, b, a);

        /* Filled circle approximation using horizontal lines */
        int ri = (int)lr;
        for (int dy = -ri; dy <= ri; dy++) {
            int dx = (int)sqrtf((float)(ri * ri - dy * dy));
            SDL_RenderDrawLine(ren, cx - dx, cy + dy, cx + dx, cy + dy);
        }
    }
}

static void render_wave(SDL_Renderer *ren, BGWave *wave, int w, int h, RGB accent) {
    SDL_SetRenderDrawBlendMode(ren, SDL_BLENDMODE_BLEND);
    RGB wave_color = tint_rgb((RGB){wave->r, wave->g, wave->b}, accent, 0.18f);
    SDL_SetRenderDrawColor(ren, wave_color.r, wave_color.g, wave_color.b, wave->a);

    float base_y = wave->y_base * h;

    /* Draw filled wave by connecting vertical strips */
    int prev_y = -1;
    for (int x = 0; x < w; x += 2) {
        float fx = (float)x;
        float y = base_y +
            sinf(fx * wave->frequency + wave->phase) * wave->amplitude +
            sinf(fx * wave->frequency * 2.3f + wave->phase * 1.7f) * wave->amplitude * 0.3f;

        int iy = (int)y;
        if (iy < 0) iy = 0;
        if (iy > h) iy = h;

        /* Fill from wave line to bottom */
        SDL_Rect strip = {x, iy, 2, h - iy};
        SDL_RenderFillRect(ren, &strip);

        /* Glow line at the wave crest */
        if (prev_y >= 0) {
            Uint8 glow_a = (Uint8)(wave->a * 3 > 255 ? 255 : wave->a * 3);
            SDL_SetRenderDrawColor(ren, wave_color.r, wave_color.g, wave_color.b, glow_a);
            SDL_RenderDrawLine(ren, x - 2, prev_y, x, iy);
            SDL_SetRenderDrawColor(ren, wave_color.r, wave_color.g, wave_color.b, wave->a);
        }
        prev_y = iy;
    }
}

void bg_render(AnimatedBG *bg, SDL_Renderer *ren, int w, int h) {
    if (!bg->initialized) return;
    RGB top_color, bottom_color, accent_color;
    sample_day_theme(current_day_progress(), &top_color, &bottom_color, &accent_color);

    /* Base gradient — dark at top, slightly lighter at bottom */
    for (int y = 0; y < h; y += 4) {
        float t = (float)y / (float)h;
        RGB row = lerp_rgb(top_color, bottom_color, t);
        Uint8 r = row.r;
        Uint8 g = row.g;
        Uint8 b = row.b;
        SDL_SetRenderDrawColor(ren, r, g, b, 255);
        SDL_Rect strip = {0, y, w, 4};
        SDL_RenderFillRect(ren, &strip);
    }

    /* Subtle color shift over time */
    float pulse = 0.85f + 0.15f * (sinf(bg->time * 0.05f) * 0.5f + 0.5f);
    SDL_SetRenderDrawBlendMode(ren, SDL_BLENDMODE_ADD);
    SDL_SetRenderDrawColor(
        ren,
        accent_color.r,
        accent_color.g,
        accent_color.b,
        (Uint8)(6.0f * pulse)
    );
    SDL_Rect full = {0, 0, w, h};
    SDL_RenderFillRect(ren, &full);

    /* Render waves (back to front) */
    for (int i = 0; i < bg->wave_count; i++) {
        render_wave(ren, &bg->waves[i], w, h, accent_color);
    }

    /* Render particles */
    for (int i = 0; i < bg->particle_count; i++) {
        BGParticle *p = &bg->particles[i];
        float pulse = 0.6f + 0.4f * sinf(p->pulse_phase);
        float alpha = p->alpha * pulse;
        float radius = p->radius * (0.8f + 0.2f * pulse);
        RGB particle_color = tint_rgb((RGB){p->r, p->g, p->b}, accent_color, 0.24f);
        render_soft_circle(ren, (int)p->x, (int)p->y, radius,
                           particle_color.r, particle_color.g, particle_color.b, alpha);
    }

    /* Reset blend mode */
    SDL_SetRenderDrawBlendMode(ren, SDL_BLENDMODE_NONE);
}
