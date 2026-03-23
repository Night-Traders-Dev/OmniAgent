/*
 * OmniAgent Smart Hub — Context Menu
 * Frosted glass popup that appears on long-press.
 */
#include "menu.h"
#include <string.h>

typedef struct { Uint8 r, g, b, a; } MColor;
static const MColor M_BG       = {20, 28, 42, 240};
static const MColor M_HOVER    = {50, 65, 90, 255};
static const MColor M_TEXT     = {224, 232, 240, 255};
static const MColor M_RED      = {240, 90, 90, 255};
static const MColor M_DIM      = {100, 115, 135, 255};
static const MColor M_BORDER   = {45, 58, 78, 200};
static const MColor M_DIVIDER  = {40, 52, 70, 150};

void menu_hide(ContextMenu *menu) {
    menu->visible = false;
    menu->count = 0;
    menu->hovered = -1;
    menu->context_type = 0;
}

void menu_show(ContextMenu *menu, int x, int y) {
    menu->visible = true;
    menu->x = x;
    menu->y = y;
    menu->hovered = -1;
}

void menu_add(ContextMenu *menu, const char *icon, const char *label, int action_id,
              bool destructive, bool divider_after) {
    if (menu->count >= MENU_MAX_ITEMS) return;
    MenuItem *it = &menu->items[menu->count++];
    it->icon = icon;
    it->label = label;
    it->action_id = action_id;
    it->destructive = destructive;
    it->divider_after = divider_after;
}

int menu_handle_event(ContextMenu *menu, SDL_Event *event, int screen_w, int screen_h) {
    if (!menu->visible) return -1;

    int tx = -1, ty = -1;
    bool is_down = false;
    bool is_up = false;

    if (event->type == SDL_MOUSEBUTTONDOWN) {
        tx = event->button.x; ty = event->button.y; is_down = true;
    } else if (event->type == SDL_FINGERDOWN) {
        tx = (int)(event->tfinger.x * screen_w);
        ty = (int)(event->tfinger.y * screen_h);
        is_down = true;
    } else if (event->type == SDL_MOUSEBUTTONUP) {
        tx = event->button.x; ty = event->button.y; is_up = true;
    } else if (event->type == SDL_FINGERUP) {
        tx = (int)(event->tfinger.x * screen_w);
        ty = (int)(event->tfinger.y * screen_h);
        is_up = true;
    }

    if (tx < 0) return -1;

    int mh = menu->count * MENU_ITEM_H + 8;
    int mx = menu->x, my = menu->y;

    /* Clamp menu position to screen */
    if (mx + MENU_W > screen_w - 8) mx = screen_w - MENU_W - 8;
    if (my + mh > screen_h - 8) my = screen_h - mh - 8;
    if (mx < 8) mx = 8;
    if (my < 8) my = 8;
    menu->x = mx;
    menu->y = my;

    /* Check if touch is inside menu */
    if (tx >= mx && tx <= mx + MENU_W && ty >= my && ty <= my + mh) {
        int item_idx = (ty - my - 4) / MENU_ITEM_H;
        if (item_idx >= 0 && item_idx < menu->count) {
            if (is_down) {
                menu->hovered = item_idx;
            }
            if (is_up) {
                int action = menu->items[item_idx].action_id;
                menu_hide(menu);
                return action;
            }
        }
        return -1; /* Consumed but no action yet */
    }

    /* Touch outside menu — dismiss */
    if (is_down) {
        menu_hide(menu);
    }
    return -1;
}

static void m_fill(SDL_Renderer *r, int x, int y, int w, int h, MColor c) {
    SDL_SetRenderDrawBlendMode(r, SDL_BLENDMODE_BLEND);
    SDL_SetRenderDrawColor(r, c.r, c.g, c.b, c.a);
    SDL_Rect rect = {x, y, w, h};
    SDL_RenderFillRect(r, &rect);
}

static void m_text(SDL_Renderer *ren, TTF_Font *f, const char *text, int x, int y, MColor c) {
    if (!text || !text[0]) return;
    SDL_Color sc = {c.r, c.g, c.b, c.a};
    SDL_Surface *surf = TTF_RenderUTF8_Blended(f, text, sc);
    if (!surf) return;
    SDL_Texture *tex = SDL_CreateTextureFromSurface(ren, surf);
    SDL_Rect dst = {x, y, surf->w, surf->h};
    SDL_RenderCopy(ren, tex, NULL, &dst);
    SDL_FreeSurface(surf);
    SDL_DestroyTexture(tex);
}

void menu_render(ContextMenu *menu, SDL_Renderer *ren, TTF_Font *font, TTF_Font *font_small) {
    if (!menu->visible || menu->count == 0) return;

    int mh = menu->count * MENU_ITEM_H + 8;
    int mx = menu->x, my = menu->y;

    /* Shadow */
    m_fill(ren, mx + 4, my + 4, MENU_W, mh, (MColor){0, 0, 0, 80});

    /* Background */
    m_fill(ren, mx, my, MENU_W, mh, M_BG);

    /* Border */
    SDL_SetRenderDrawBlendMode(ren, SDL_BLENDMODE_BLEND);
    SDL_SetRenderDrawColor(ren, M_BORDER.r, M_BORDER.g, M_BORDER.b, M_BORDER.a);
    SDL_Rect border = {mx, my, MENU_W, mh};
    SDL_RenderDrawRect(ren, &border);

    /* Items */
    for (int i = 0; i < menu->count; i++) {
        MenuItem *it = &menu->items[i];
        int iy = my + 4 + i * MENU_ITEM_H;

        /* Hover highlight */
        if (i == menu->hovered) {
            m_fill(ren, mx + 2, iy, MENU_W - 4, MENU_ITEM_H, M_HOVER);
        }

        /* Icon */
        if (it->icon) {
            m_text(ren, font, it->icon, mx + 14, iy + 12, M_TEXT);
        }

        /* Label */
        MColor label_c = it->destructive ? M_RED : M_TEXT;
        m_text(ren, font, it->label, mx + 44, iy + 12, label_c);

        /* Divider */
        if (it->divider_after) {
            m_fill(ren, mx + 12, iy + MENU_ITEM_H - 1, MENU_W - 24, 1, M_DIVIDER);
        }
    }
}
