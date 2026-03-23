/*
 * OmniAgent Smart Hub — Animated Background
 * PlayStation-style flowing particles + gradient waves
 */
#ifndef BACKGROUND_H
#define BACKGROUND_H

#include <SDL2/SDL.h>
#include <stdbool.h>

#define BG_MAX_PARTICLES 80
#define BG_MAX_WAVES 5

typedef struct {
    float x, y;
    float vx, vy;
    float radius;
    float alpha;
    float pulse_phase;
    Uint8 r, g, b;
} BGParticle;

typedef struct {
    float phase;
    float speed;
    float amplitude;
    float frequency;
    float y_base;       /* 0.0 - 1.0 vertical position */
    Uint8 r, g, b, a;
} BGWave;

typedef struct {
    BGParticle particles[BG_MAX_PARTICLES];
    int particle_count;
    BGWave waves[BG_MAX_WAVES];
    int wave_count;
    float time;
    bool initialized;
    /* Color theme */
    Uint8 bg_r, bg_g, bg_b;
} AnimatedBG;

void bg_init(AnimatedBG *bg);
void bg_update(AnimatedBG *bg, float dt);
void bg_render(AnimatedBG *bg, SDL_Renderer *ren, int w, int h);

#endif
