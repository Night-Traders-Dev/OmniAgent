/*
 * OmniAgent Smart Hub — On-Screen Touch Keyboard
 *
 * GBoard-inspired layout:
 *   Row 1: q w e r t y u i o p
 *   Row 2:  a s d f g h j k l
 *   Row 3: [shift] z x c v b n m [backspace]
 *   Row 4: [?123] [,] [________space________] [.] [enter]
 *
 * Features:
 *   - QWERTY / Shift / Caps Lock (double-tap shift)
 *   - Numbers layer (?123)
 *   - Symbols layer (=\<)
 *   - Key popup on press
 *   - Backspace auto-repeat on long press
 *   - Themed to match OmniAgent dark UI
 */
#include "keyboard.h"
#include <string.h>
#include <stdio.h>

/* ═══ Colors (matching main UI) ═══ */
typedef struct { Uint8 r, g, b, a; } KBColor;

static const KBColor KB_BG         = {17, 24, 32, 245};
static const KBColor KB_KEY_BG     = {30, 40, 54, 255};
static const KBColor KB_KEY_PRESS  = {74, 158, 255, 255};
static const KBColor KB_KEY_SPECIAL= {22, 29, 39, 255};
static const KBColor KB_KEY_ENTER  = {74, 158, 255, 255};
static const KBColor KB_TEXT       = {224, 232, 240, 255};
static const KBColor KB_TEXT_DIM   = {106, 122, 138, 255};
static const KBColor KB_POPUP_BG   = {50, 65, 85, 255};
static const KBColor KB_BORDER     = {40, 55, 72, 255};

/* ═══ Key Layouts ═══ */

/* Row definitions for each layout */
/* Lower case */
static const char *L_ROW1[] = {"q","w","e","r","t","y","u","i","o","p", NULL};
static const char *L_ROW2[] = {"a","s","d","f","g","h","j","k","l", NULL};
static const char *L_ROW3[] = {"z","x","c","v","b","n","m", NULL};

/* Upper case */
static const char *U_ROW1[] = {"Q","W","E","R","T","Y","U","I","O","P", NULL};
static const char *U_ROW2[] = {"A","S","D","F","G","H","J","K","L", NULL};
static const char *U_ROW3[] = {"Z","X","C","V","B","N","M", NULL};

/* Numbers */
static const char *N_ROW1[] = {"1","2","3","4","5","6","7","8","9","0", NULL};
static const char *N_ROW2[] = {"@","#","$","_","&","-","+","(",")", NULL};
static const char *N_ROW3[] = {"*","\"","'",":",";","!","?", NULL};

/* Symbols */
static const char *S_ROW1[] = {"~","`","|","^","\\","{","}","[","]","%", NULL};
static const char *S_ROW2[] = {"<",">","=","/","€","£","¥","•","°", NULL};
static const char *S_ROW3[] = {"©","®","™","¶","§","¡","¿", NULL};

static void build_char_row(KBRow *row, const char **chars) {
    row->count = 0;
    for (int i = 0; chars[i] && row->count < KB_MAX_COLS; i++) {
        row->keys[row->count].label = chars[i];
        row->keys[row->count].output = chars[i];
        row->keys[row->count].width = 1.0f;
        row->keys[row->count].action = KB_ACTION_CHAR;
        row->count++;
    }
}

static void get_layout_rows(KBLayout layout, KBRow rows[KB_ROWS]) {
    const char **r1, **r2, **r3;

    switch (layout) {
    case KB_LAYOUT_UPPER:   r1 = U_ROW1; r2 = U_ROW2; r3 = U_ROW3; break;
    case KB_LAYOUT_NUMBERS: r1 = N_ROW1; r2 = N_ROW2; r3 = N_ROW3; break;
    case KB_LAYOUT_SYMBOLS: r1 = S_ROW1; r2 = S_ROW2; r3 = S_ROW3; break;
    default:                r1 = L_ROW1; r2 = L_ROW2; r3 = L_ROW3; break;
    }

    /* Row 1: characters */
    build_char_row(&rows[0], r1);

    /* Row 2: characters (slightly indented via narrower keys — handled in render) */
    build_char_row(&rows[1], r2);

    /* Row 3: [shift/symbols] chars [backspace] */
    rows[2].count = 0;
    KBKey *k;

    /* Left action key */
    k = &rows[2].keys[rows[2].count++];
    if (layout == KB_LAYOUT_LOWER || layout == KB_LAYOUT_UPPER) {
        k->label = layout == KB_LAYOUT_UPPER ? "⬆" : "⇧";
        k->output = NULL;
        k->width = 1.5f;
        k->action = KB_ACTION_SHIFT;
    } else if (layout == KB_LAYOUT_NUMBERS) {
        k->label = "=\\<";
        k->output = NULL;
        k->width = 1.5f;
        k->action = KB_ACTION_SYMBOLS;
    } else {
        k->label = "?123";
        k->output = NULL;
        k->width = 1.5f;
        k->action = KB_ACTION_NUMBERS;
    }

    /* Character keys */
    for (int i = 0; r3[i]; i++) {
        k = &rows[2].keys[rows[2].count++];
        k->label = r3[i];
        k->output = r3[i];
        k->width = 1.0f;
        k->action = KB_ACTION_CHAR;
    }

    /* Backspace */
    k = &rows[2].keys[rows[2].count++];
    k->label = "⌫";
    k->output = NULL;
    k->width = 1.5f;
    k->action = KB_ACTION_BACKSPACE;

    /* Row 4: [?123/ABC] [,] [_____space_____] [.] [enter] */
    rows[3].count = 0;

    k = &rows[3].keys[rows[3].count++];
    if (layout == KB_LAYOUT_LOWER || layout == KB_LAYOUT_UPPER) {
        k->label = "?123";
        k->output = NULL;
        k->width = 1.5f;
        k->action = KB_ACTION_NUMBERS;
    } else {
        k->label = "ABC";
        k->output = NULL;
        k->width = 1.5f;
        k->action = KB_ACTION_ABC;
    }

    k = &rows[3].keys[rows[3].count++];
    k->label = ",";
    k->output = ",";
    k->width = 1.0f;
    k->action = KB_ACTION_CHAR;

    k = &rows[3].keys[rows[3].count++];
    k->label = "space";
    k->output = " ";
    k->width = 5.0f;
    k->action = KB_ACTION_SPACE;

    k = &rows[3].keys[rows[3].count++];
    k->label = ".";
    k->output = ".";
    k->width = 1.0f;
    k->action = KB_ACTION_CHAR;

    k = &rows[3].keys[rows[3].count++];
    k->label = "⏎";
    k->output = NULL;
    k->width = 1.5f;
    k->action = KB_ACTION_ENTER;
}

/* ═══ Keyboard API ═══ */

void kb_init(Keyboard *kb) {
    memset(kb, 0, sizeof(Keyboard));
    kb->layout = KB_LAYOUT_LOWER;
    kb->pressed_row = -1;
    kb->pressed_col = -1;
}

void kb_attach(Keyboard *kb, char *buf, int *cursor, int max_len) {
    kb->target_buf = buf;
    kb->target_cursor = cursor;
    kb->target_max = max_len;
}

void kb_show(Keyboard *kb)   { kb->visible = true; }
void kb_hide(Keyboard *kb)   { kb->visible = false; kb->show_popup = false; }
void kb_toggle(Keyboard *kb) { kb->visible ? kb_hide(kb) : kb_show(kb); }
int  kb_get_height(Keyboard *kb) { return kb->visible ? KB_HEIGHT : 0; }

static void kb_insert_text(Keyboard *kb, const char *text) {
    if (!kb->target_buf || !text) return;
    size_t cur_len = strlen(kb->target_buf);
    size_t add_len = strlen(text);
    if ((int)(cur_len + add_len) >= kb->target_max - 1) return;
    strcat(kb->target_buf, text);
    if (kb->target_cursor) *kb->target_cursor = (int)strlen(kb->target_buf);
}

static void kb_do_backspace(Keyboard *kb) {
    if (!kb->target_buf) return;
    size_t len = strlen(kb->target_buf);
    if (len == 0) return;
    /* Handle UTF-8: walk back to find start of last character */
    size_t i = len - 1;
    while (i > 0 && (kb->target_buf[i] & 0xC0) == 0x80) i--;
    kb->target_buf[i] = '\0';
    if (kb->target_cursor) *kb->target_cursor = (int)i;
}

static void kb_handle_action(Keyboard *kb, KBAction action, const char *output) {
    switch (action) {
    case KB_ACTION_CHAR:
        kb_insert_text(kb, output);
        /* Auto-unshift after typing one character (like GBoard) */
        if (kb->layout == KB_LAYOUT_UPPER && !kb->shift_locked) {
            kb->layout = KB_LAYOUT_LOWER;
        }
        break;
    case KB_ACTION_SPACE:
        kb_insert_text(kb, " ");
        break;
    case KB_ACTION_BACKSPACE:
        kb_do_backspace(kb);
        break;
    case KB_ACTION_ENTER:
        /* Caller handles enter — hide keyboard */
        kb_hide(kb);
        break;
    case KB_ACTION_SHIFT:
        if (kb->layout == KB_LAYOUT_UPPER) {
            /* If already upper and pressed again → caps lock */
            kb->shift_locked = !kb->shift_locked;
            if (!kb->shift_locked) kb->layout = KB_LAYOUT_LOWER;
        } else {
            kb->layout = KB_LAYOUT_UPPER;
            kb->shift_locked = false;
        }
        break;
    case KB_ACTION_NUMBERS:
        kb->layout = KB_LAYOUT_NUMBERS;
        break;
    case KB_ACTION_SYMBOLS:
        kb->layout = KB_LAYOUT_SYMBOLS;
        break;
    case KB_ACTION_ABC:
        kb->layout = KB_LAYOUT_LOWER;
        break;
    case KB_ACTION_HIDE:
        kb_hide(kb);
        break;
    default:
        break;
    }
}

/* ═══ Hit testing ═══ */

typedef struct { int x, y, w, h; } KeyRect;

static void calc_key_rects(KBRow rows[KB_ROWS], int kb_x, int kb_y, int kb_w,
                           KeyRect rects[KB_ROWS][KB_MAX_COLS]) {
    int row_h = (KB_HEIGHT - 8) / KB_ROWS;

    for (int r = 0; r < KB_ROWS; r++) {
        /* Calculate total width units for this row */
        float total_w = 0;
        for (int c = 0; c < rows[r].count; c++) total_w += rows[r].keys[c].width;

        float unit_w = (float)(kb_w - (rows[r].count + 1) * KB_KEY_GAP) / total_w;
        /* Center row 2 (9 keys vs 10) by adding horizontal offset */
        float x_off = 0;
        if (r == 1 && rows[r].count < rows[0].count) {
            float row0_total = 0;
            for (int c = 0; c < rows[0].count; c++) row0_total += rows[0].keys[c].width;
            float unit0 = (float)(kb_w - (rows[0].count + 1) * KB_KEY_GAP) / row0_total;
            x_off = (unit0 - unit_w) * 0.5f * rows[r].count * 0.5f;
        }

        float cx = kb_x + KB_KEY_GAP + x_off;
        int cy = kb_y + 4 + r * row_h;

        for (int c = 0; c < rows[r].count; c++) {
            int kw = (int)(rows[r].keys[c].width * unit_w);
            rects[r][c].x = (int)cx;
            rects[r][c].y = cy;
            rects[r][c].w = kw;
            rects[r][c].h = row_h - KB_KEY_GAP;
            cx += kw + KB_KEY_GAP;
        }
    }
}

/* ═══ Event handling ═══ */

bool kb_handle_event(Keyboard *kb, SDL_Event *event, int screen_w, int screen_h) {
    if (!kb->visible) return false;

    int kb_x = 0;
    int kb_y = screen_h - KB_HEIGHT;
    int kb_w = screen_w;

    KBRow rows[KB_ROWS];
    get_layout_rows(kb->layout, rows);
    KeyRect rects[KB_ROWS][KB_MAX_COLS];
    calc_key_rects(rows, kb_x, kb_y, kb_w, rects);

    int tx = -1, ty = -1;

    if (event->type == SDL_MOUSEBUTTONDOWN) {
        tx = event->button.x;
        ty = event->button.y;
    } else if (event->type == SDL_FINGERDOWN) {
        tx = (int)(event->tfinger.x * screen_w);
        ty = (int)(event->tfinger.y * screen_h);
    } else if (event->type == SDL_MOUSEBUTTONUP || event->type == SDL_FINGERUP) {
        kb->pressed_row = -1;
        kb->pressed_col = -1;
        kb->show_popup = false;
        kb->repeating = false;
        return ty >= 0 && ty >= kb_y; /* Consume if in keyboard area */
    }

    /* Not a press in the keyboard region */
    if (ty < kb_y) return false;

    /* Find which key was hit */
    for (int r = 0; r < KB_ROWS; r++) {
        for (int c = 0; c < rows[r].count; c++) {
            KeyRect *kr = &rects[r][c];
            if (tx >= kr->x && tx <= kr->x + kr->w && ty >= kr->y && ty <= kr->y + kr->h) {
                kb->pressed_row = r;
                kb->pressed_col = c;
                kb->press_time = SDL_GetTicks();
                kb->repeating = false;

                /* Show popup for character keys */
                if (rows[r].keys[c].action == KB_ACTION_CHAR && rows[r].keys[c].output) {
                    kb->show_popup = true;
                    kb->popup_row = r;
                    kb->popup_col = c;
                    snprintf(kb->popup_char, sizeof(kb->popup_char), "%s", rows[r].keys[c].output);
                } else {
                    kb->show_popup = false;
                }

                /* Execute action immediately */
                kb_handle_action(kb, rows[r].keys[c].action, rows[r].keys[c].output);
                return true;
            }
        }
    }

    return true; /* Consume all touches in keyboard region */
}

/* Call this from main loop for backspace repeat */
void kb_update(Keyboard *kb) {
    if (!kb->visible || kb->pressed_row < 0) return;

    KBRow rows[KB_ROWS];
    get_layout_rows(kb->layout, rows);

    int r = kb->pressed_row, c = kb->pressed_col;
    if (r < 0 || r >= KB_ROWS || c < 0 || c >= rows[r].count) return;

    KBKey *key = &rows[r].keys[c];
    if (key->action != KB_ACTION_BACKSPACE) return;

    Uint32 held = SDL_GetTicks() - kb->press_time;
    if (!kb->repeating && held > KB_LONG_PRESS_MS) {
        kb->repeating = true;
        kb->press_time = SDL_GetTicks();
        kb_do_backspace(kb);
    } else if (kb->repeating && held > KB_REPEAT_MS) {
        kb->press_time = SDL_GetTicks();
        kb_do_backspace(kb);
    }
}

/* ═══ Rendering ═══ */

static void kb_fill_rect(SDL_Renderer *ren, int x, int y, int w, int h, KBColor c) {
    SDL_SetRenderDrawColor(ren, c.r, c.g, c.b, c.a);
    SDL_Rect r = {x, y, w, h};
    SDL_RenderFillRect(ren, &r);
}

static void kb_draw_text_centered(SDL_Renderer *ren, TTF_Font *font, const char *text,
                                  int cx, int cy, KBColor color) {
    if (!text || !text[0]) return;
    SDL_Color sc = {color.r, color.g, color.b, color.a};
    SDL_Surface *surf = TTF_RenderUTF8_Blended(font, text, sc);
    if (!surf) return;
    SDL_Texture *tex = SDL_CreateTextureFromSurface(ren, surf);
    SDL_Rect dst = {cx - surf->w / 2, cy - surf->h / 2, surf->w, surf->h};
    SDL_RenderCopy(ren, tex, NULL, &dst);
    SDL_FreeSurface(surf);
    SDL_DestroyTexture(tex);
}

void kb_render(Keyboard *kb, SDL_Renderer *ren, TTF_Font *font, TTF_Font *font_small,
               int screen_w, int screen_h) {
    if (!kb->visible) return;

    int kb_x = 0;
    int kb_y = screen_h - KB_HEIGHT;
    int kb_w = screen_w;

    /* Background */
    kb_fill_rect(ren, kb_x, kb_y, kb_w, KB_HEIGHT, KB_BG);
    /* Top border */
    kb_fill_rect(ren, kb_x, kb_y, kb_w, 1, KB_BORDER);

    KBRow rows[KB_ROWS];
    get_layout_rows(kb->layout, rows);
    KeyRect rects[KB_ROWS][KB_MAX_COLS];
    calc_key_rects(rows, kb_x, kb_y, kb_w, rects);

    /* Draw keys */
    for (int r = 0; r < KB_ROWS; r++) {
        for (int c = 0; c < rows[r].count; c++) {
            KBKey *key = &rows[r].keys[c];
            KeyRect *kr = &rects[r][c];
            bool pressed = (r == kb->pressed_row && c == kb->pressed_col);

            /* Key background color */
            KBColor bg;
            if (pressed) {
                bg = KB_KEY_PRESS;
            } else if (key->action == KB_ACTION_ENTER) {
                bg = KB_KEY_ENTER;
            } else if (key->action == KB_ACTION_SHIFT && kb->layout == KB_LAYOUT_UPPER) {
                bg = KB_KEY_PRESS; /* Highlight shift when active */
            } else if (key->action != KB_ACTION_CHAR && key->action != KB_ACTION_SPACE) {
                bg = KB_KEY_SPECIAL;
            } else {
                bg = KB_KEY_BG;
            }

            /* Draw key background (rounded-ish) */
            kb_fill_rect(ren, kr->x, kr->y, kr->w, kr->h, bg);
            /* Subtle top highlight */
            KBColor highlight = {(Uint8)(bg.r + 15), (Uint8)(bg.g + 15), (Uint8)(bg.b + 15), 255};
            kb_fill_rect(ren, kr->x, kr->y, kr->w, 1, highlight);

            /* Key label */
            KBColor text_col = KB_TEXT;
            if (pressed) { text_col.r = 0; text_col.g = 0; text_col.b = 0; text_col.a = 255; }
            else if (key->action == KB_ACTION_ENTER) { text_col.r = 0; text_col.g = 0; text_col.b = 0; text_col.a = 255; }

            TTF_Font *f = (key->action != KB_ACTION_CHAR && key->action != KB_ACTION_SPACE)
                          ? font_small : font;
            kb_draw_text_centered(ren, f, key->label,
                                  kr->x + kr->w / 2, kr->y + kr->h / 2, text_col);
        }
    }

    /* Key popup (magnified character) */
    if (kb->show_popup && kb->popup_char[0]) {
        KeyRect *kr = &rects[kb->popup_row][kb->popup_col];
        int pw = kr->w + 16;
        int ph = 52;
        int px = kr->x + kr->w / 2 - pw / 2;
        int py = kr->y - ph - 4;
        if (px < 2) px = 2;
        if (px + pw > screen_w - 2) px = screen_w - pw - 2;

        kb_fill_rect(ren, px, py, pw, ph, KB_POPUP_BG);
        kb_fill_rect(ren, px, py, pw, 1, KB_BORDER);

        /* Large character */
        SDL_Color sc = {255, 255, 255, 255};
        SDL_Surface *surf = TTF_RenderUTF8_Blended(font, kb->popup_char, sc);
        if (surf) {
            SDL_Texture *tex = SDL_CreateTextureFromSurface(ren, surf);
            /* Scale up 1.5x */
            SDL_Rect dst = {px + pw/2 - surf->w*3/4, py + ph/2 - surf->h*3/4,
                            surf->w * 3/2, surf->h * 3/2};
            SDL_RenderCopy(ren, tex, NULL, &dst);
            SDL_FreeSurface(surf);
            SDL_DestroyTexture(tex);
        }
    }

    /* Shift lock indicator (small dot) */
    if (kb->shift_locked && kb->layout == KB_LAYOUT_UPPER) {
        KeyRect *kr = &rects[2][0]; /* Shift key */
        kb_fill_rect(ren, kr->x + kr->w - 8, kr->y + 4, 4, 4, KB_TEXT);
    }
}
