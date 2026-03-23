/*
 * OmniAgent Smart Hub — Context Menu + Popup System
 * Touch-friendly long-press menus for bubbles, widgets, sessions.
 */
#ifndef MENU_H
#define MENU_H

#include <SDL2/SDL.h>
#include <SDL2/SDL_ttf.h>
#include <stdbool.h>

#define MENU_MAX_ITEMS 12
#define MENU_ITEM_H 44
#define MENU_W 220
#define MENU_RADIUS 12
#define LONG_PRESS_MS 400

typedef struct {
    const char *icon;        /* Emoji or single char */
    const char *label;
    int action_id;           /* App-defined action code */
    bool destructive;        /* Red text for delete/dangerous actions */
    bool divider_after;      /* Draw separator after this item */
} MenuItem;

typedef struct {
    bool visible;
    int x, y;                /* Screen position */
    MenuItem items[MENU_MAX_ITEMS];
    int count;
    int hovered;             /* Which item is being touched */
    /* Context — what was long-pressed */
    int context_type;        /* 0=none, 1=user_msg, 2=asst_msg, 3=session, 4=widget */
    int context_index;       /* Message index, session index, widget id */
    char context_text[4096]; /* Message text for copy/share */
} ContextMenu;

/* Clear and hide the menu */
void menu_hide(ContextMenu *menu);

/* Show menu at position with items */
void menu_show(ContextMenu *menu, int x, int y);

/* Add an item (call before menu_show or between hide/show) */
void menu_add(ContextMenu *menu, const char *icon, const char *label, int action_id,
              bool destructive, bool divider_after);

/* Handle touch event — returns action_id if an item was tapped, -1 otherwise */
int menu_handle_event(ContextMenu *menu, SDL_Event *event, int screen_w, int screen_h);

/* Render the context menu */
void menu_render(ContextMenu *menu, SDL_Renderer *ren, TTF_Font *font, TTF_Font *font_small);

#endif
