/*
 * OmniAgent Smart Hub — On-Screen Touch Keyboard
 * GBoard-style layout: QWERTY, symbols, numbers
 */
#ifndef KEYBOARD_H
#define KEYBOARD_H

#include <SDL2/SDL.h>
#include <SDL2/SDL_ttf.h>
#include <stdbool.h>

/* Keyboard dimensions */
#define KB_ROWS 4
#define KB_MAX_COLS 11
#define KB_HEIGHT 220
#define KB_KEY_GAP 4
#define KB_KEY_RADIUS 6
#define KB_LONG_PRESS_MS 500
#define KB_REPEAT_MS 80

typedef enum {
    KB_LAYOUT_LOWER,
    KB_LAYOUT_UPPER,
    KB_LAYOUT_NUMBERS,
    KB_LAYOUT_SYMBOLS,
} KBLayout;

typedef enum {
    KB_ACTION_NONE,
    KB_ACTION_CHAR,       /* Insert character */
    KB_ACTION_BACKSPACE,
    KB_ACTION_ENTER,
    KB_ACTION_SPACE,
    KB_ACTION_SHIFT,
    KB_ACTION_SYMBOLS,
    KB_ACTION_NUMBERS,
    KB_ACTION_ABC,
    KB_ACTION_HIDE,
} KBAction;

typedef struct {
    const char *label;     /* Display text */
    const char *output;    /* Character(s) to insert (NULL for action keys) */
    float width;           /* Relative width (1.0 = standard key) */
    KBAction action;
} KBKey;

typedef struct {
    KBKey keys[KB_MAX_COLS];
    int count;
} KBRow;

typedef struct {
    bool visible;
    KBLayout layout;
    bool shift_locked;

    /* Target text buffer */
    char *target_buf;
    int *target_cursor;
    int target_max;

    /* Rendering state */
    int x, y, w, h;
    int pressed_row, pressed_col;
    Uint32 press_time;
    bool repeating;

    /* Popup state */
    bool show_popup;
    int popup_row, popup_col;
    char popup_char[8];
} Keyboard;

/* Initialize keyboard state */
void kb_init(Keyboard *kb);

/* Attach keyboard to a text buffer */
void kb_attach(Keyboard *kb, char *buf, int *cursor, int max_len);

/* Show/hide */
void kb_show(Keyboard *kb);
void kb_hide(Keyboard *kb);
void kb_toggle(Keyboard *kb);

/* Event handling — returns true if event was consumed */
bool kb_handle_event(Keyboard *kb, SDL_Event *event, int screen_w, int screen_h);

/* Render the keyboard */
void kb_render(Keyboard *kb, SDL_Renderer *renderer, TTF_Font *font, TTF_Font *font_small,
               int screen_w, int screen_h);

/* Update keyboard state (call every frame for backspace repeat) */
void kb_update(Keyboard *kb);

/* Get keyboard height (0 if hidden) */
int kb_get_height(Keyboard *kb);

#endif /* KEYBOARD_H */