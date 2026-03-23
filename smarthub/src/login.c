/*
 * OmniAgent Smart Hub — Login Screen
 *
 * Full-screen login with username + password fields.
 * Authenticates via POST /api/auth/login on the OmniAgent server.
 * Uses the on-screen touch keyboard for input.
 */
#include "login.h"
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include <curl/curl.h>

/* Colors */
typedef struct { Uint8 r, g, b, a; } LColor;

static const LColor L_BG       = {10, 14, 20, 255};
static const LColor L_CARD     = {17, 24, 32, 255};
static const LColor L_BORDER   = {30, 42, 56, 255};
static const LColor L_ACCENT   = {74, 158, 255, 255};
static const LColor L_TEXT     = {224, 232, 240, 255};
static const LColor L_DIM      = {106, 122, 138, 255};
static const LColor L_RED      = {255, 74, 74, 255};
static const LColor L_FIELD_BG = {22, 29, 39, 255};
static const LColor L_FIELD_FOCUS = {74, 158, 255, 40};

/* HTTP helper (same as main.c) */
typedef struct { char *data; size_t size; } LCurlBuf;

static size_t l_write_cb(void *p, size_t s, size_t n, void *u) {
    size_t total = s * n;
    LCurlBuf *b = (LCurlBuf *)u;
    char *ptr = realloc(b->data, b->size + total + 1);
    if (!ptr) return 0;
    b->data = ptr;
    memcpy(&b->data[b->size], p, total);
    b->size += total;
    b->data[b->size] = '\0';
    return total;
}

static char *l_http_post(const char *url, const char *body) {
    CURL *curl = curl_easy_init();
    if (!curl) return NULL;
    LCurlBuf buf = {malloc(1), 0};
    buf.data[0] = '\0';
    struct curl_slist *hdrs = curl_slist_append(NULL, "Content-Type: application/json");
    curl_easy_setopt(curl, CURLOPT_URL, url);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, body);
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, hdrs);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, l_write_cb);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &buf);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, 10L);
    CURLcode res = curl_easy_perform(curl);
    curl_slist_free_all(hdrs);
    curl_easy_cleanup(curl);
    if (res != CURLE_OK) { free(buf.data); return NULL; }
    return buf.data;
}

/* Minimal JSON helpers */
static void l_json_str(const char *json, const char *key, char *out, size_t sz) {
    out[0] = '\0';
    char search[128];
    snprintf(search, sizeof(search), "\"%s\"", key);
    const char *p = strstr(json, search);
    if (!p) return;
    p += strlen(search);
    while (*p && (*p == ' ' || *p == ':' || *p == '\t')) p++;
    if (*p != '"') return;
    p++;
    size_t i = 0;
    while (*p && *p != '"' && i < sz - 1) {
        if (*p == '\\' && *(p+1)) p++;
        out[i++] = *p++;
    }
    out[i] = '\0';
}

/* ═══ API ═══ */

void login_init(LoginState *login) {
    memset(login, 0, sizeof(LoginState));
    login->active = true;
    login->focused_field = LOGIN_FIELD_USERNAME;
}

void login_attempt(LoginState *login, const char *server_url) {
    if (!login->username[0]) {
        snprintf(login->error_msg, sizeof(login->error_msg), "Username is required");
        return;
    }
    if (!login->password[0]) {
        snprintf(login->error_msg, sizeof(login->error_msg), "Password is required");
        return;
    }

    login->authenticating = true;
    login->error_msg[0] = '\0';

    /* Build login JSON — escape strings */
    char user_esc[256] = {0}, pass_esc[256] = {0};
    size_t j;
    j = 0;
    for (size_t i = 0; login->username[i] && j < sizeof(user_esc) - 2; i++) {
        if (login->username[i] == '"' || login->username[i] == '\\') user_esc[j++] = '\\';
        user_esc[j++] = login->username[i];
    }
    j = 0;
    for (size_t i = 0; login->password[i] && j < sizeof(pass_esc) - 2; i++) {
        if (login->password[i] == '"' || login->password[i] == '\\') pass_esc[j++] = '\\';
        pass_esc[j++] = login->password[i];
    }

    char body[1024];
    snprintf(body, sizeof(body), "{\"username\":\"%s\",\"password\":\"%s\"}", user_esc, pass_esc);

    char url[1024];
    snprintf(url, sizeof(url), "%s/api/auth/login", server_url);

    char *resp = l_http_post(url, body);
    login->authenticating = false;

    if (!resp) {
        snprintf(login->error_msg, sizeof(login->error_msg), "Connection failed — server unreachable");
        return;
    }

    /* Check for error */
    char err[256] = {0};
    l_json_str(resp, "error", err, sizeof(err));
    if (err[0]) {
        snprintf(login->error_msg, sizeof(login->error_msg), "%s", err);
        free(resp);
        return;
    }

    /* Extract session token */
    char sid[256] = {0};
    l_json_str(resp, "session_id", sid, sizeof(sid));
    if (sid[0]) {
        snprintf(login->auth_token, sizeof(login->auth_token), "%s", sid);
        snprintf(login->auth_username, sizeof(login->auth_username), "%s", login->username);
        login->authenticated = true;
        login->active = false;
    } else {
        snprintf(login->error_msg, sizeof(login->error_msg), "Unexpected response from server");
    }
    free(resp);
}

/* ═══ Touch handling ═══ */

/* Layout constants */
#define FORM_W 400
#define FORM_H 360
#define FIELD_H 48
#define BTN_H 50
#define FIELD_GAP 16

bool login_handle_event(LoginState *login, Keyboard *kb, SDL_Event *event,
                        int screen_w, int screen_h) {
    if (!login->active) return false;

    int tx = -1, ty = -1;
    bool is_press = false;

    if (event->type == SDL_MOUSEBUTTONDOWN) {
        tx = event->button.x; ty = event->button.y; is_press = true;
    } else if (event->type == SDL_FINGERDOWN) {
        tx = (int)(event->tfinger.x * screen_w);
        ty = (int)(event->tfinger.y * screen_h);
        is_press = true;
    }

    if (!is_press) return login->active;

    /* Form position (centered, but shifted up when keyboard is visible) */
    int kb_h = kb_get_height(kb);
    int avail_h = screen_h - kb_h;
    int fx = (screen_w - FORM_W) / 2;
    int fy = (avail_h - FORM_H) / 2;
    if (fy < 20) fy = 20;

    /* Username field */
    int uf_y = fy + 80;
    if (tx >= fx && tx <= fx + FORM_W && ty >= uf_y && ty <= uf_y + FIELD_H) {
        login->focused_field = LOGIN_FIELD_USERNAME;
        kb_attach(kb, login->username, &login->user_cursor, sizeof(login->username));
        kb_show(kb);
        return true;
    }

    /* Password field */
    int pf_y = uf_y + FIELD_H + FIELD_GAP + 20;
    if (tx >= fx && tx <= fx + FORM_W && ty >= pf_y && ty <= pf_y + FIELD_H) {
        login->focused_field = LOGIN_FIELD_PASSWORD;
        kb_attach(kb, login->password, &login->pass_cursor, sizeof(login->password));
        kb_show(kb);
        return true;
    }

    /* Login button */
    int btn_y = pf_y + FIELD_H + FIELD_GAP + 8;
    if (tx >= fx && tx <= fx + FORM_W && ty >= btn_y && ty <= btn_y + BTN_H) {
        kb_hide(kb);
        /* login_attempt is called from main loop after this returns */
        return true;
    }

    /* Tapping outside fields — unfocus */
    if (ty < screen_h - kb_h) {
        login->focused_field = LOGIN_FIELD_NONE;
        kb_hide(kb);
    }

    return true; /* Consume all events on login screen */
}

/* ═══ Rendering ═══ */

static void l_fill(SDL_Renderer *r, int x, int y, int w, int h, LColor c) {
    SDL_SetRenderDrawColor(r, c.r, c.g, c.b, c.a);
    SDL_Rect rect = {x, y, w, h};
    SDL_RenderFillRect(r, &rect);
}

static void l_text(SDL_Renderer *ren, TTF_Font *f, const char *text, int x, int y, LColor c) {
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

static void l_text_centered(SDL_Renderer *ren, TTF_Font *f, const char *text, int cx, int cy, LColor c) {
    if (!text || !text[0]) return;
    SDL_Color sc = {c.r, c.g, c.b, c.a};
    SDL_Surface *surf = TTF_RenderUTF8_Blended(f, text, sc);
    if (!surf) return;
    SDL_Texture *tex = SDL_CreateTextureFromSurface(ren, surf);
    SDL_Rect dst = {cx - surf->w/2, cy - surf->h/2, surf->w, surf->h};
    SDL_RenderCopy(ren, tex, NULL, &dst);
    SDL_FreeSurface(surf);
    SDL_DestroyTexture(tex);
}

void login_render(LoginState *login, SDL_Renderer *ren,
                  TTF_Font *font, TTF_Font *font_small, TTF_Font *font_large,
                  int screen_w, int screen_h) {
    if (!login->active) return;

    /* Full-screen background */
    l_fill(ren, 0, 0, screen_w, screen_h, L_BG);

    /* Keyboard-aware centering */
    /* (keyboard renders itself — we just shift the form up) */
    int avail_h = screen_h; /* keyboard overlaps, form just shifts */
    int fx = (screen_w - FORM_W) / 2;
    int fy = (avail_h - FORM_H) / 2 - 40; /* Shift up for keyboard */
    if (fy < 10) fy = 10;

    /* Card background */
    l_fill(ren, fx - 20, fy - 20, FORM_W + 40, FORM_H + 40, L_CARD);
    /* Card border */
    SDL_SetRenderDrawColor(ren, L_BORDER.r, L_BORDER.g, L_BORDER.b, L_BORDER.a);
    SDL_Rect card = {fx - 20, fy - 20, FORM_W + 40, FORM_H + 40};
    SDL_RenderDrawRect(ren, &card);
    /* Accent top bar */
    l_fill(ren, fx - 20, fy - 20, FORM_W + 40, 3, L_ACCENT);

    /* Title */
    l_text_centered(ren, font_large, "OmniAgent", screen_w / 2, fy + 10, L_ACCENT);

    /* Server info */
    if (login->server_display[0]) {
        l_text_centered(ren, font_small, login->server_display, screen_w / 2, fy + 45, L_DIM);
    }

    /* Username label + field */
    int uf_y = fy + 70;
    l_text(ren, font_small, "Username", fx, uf_y, L_DIM);
    uf_y += 18;

    LColor uf_bg = (login->focused_field == LOGIN_FIELD_USERNAME) ? L_FIELD_FOCUS : L_FIELD_BG;
    l_fill(ren, fx, uf_y, FORM_W, FIELD_H, uf_bg);
    /* Border */
    LColor uf_border = (login->focused_field == LOGIN_FIELD_USERNAME) ? L_ACCENT : L_BORDER;
    SDL_SetRenderDrawColor(ren, uf_border.r, uf_border.g, uf_border.b, uf_border.a);
    SDL_Rect uf_rect = {fx, uf_y, FORM_W, FIELD_H};
    SDL_RenderDrawRect(ren, &uf_rect);
    /* Text or placeholder */
    if (login->username[0]) {
        l_text(ren, font, login->username, fx + 14, uf_y + 12, L_TEXT);
    } else {
        l_text(ren, font, "Enter username", fx + 14, uf_y + 12, L_DIM);
    }
    /* Cursor blink */
    if (login->focused_field == LOGIN_FIELD_USERNAME && (SDL_GetTicks() / 500) % 2 == 0) {
        int tw = 0;
        if (login->username[0]) {
            TTF_SizeUTF8(font, login->username, &tw, NULL);
        }
        l_fill(ren, fx + 14 + tw, uf_y + 10, 2, FIELD_H - 20, L_ACCENT);
    }

    /* Password label + field */
    int pf_y = uf_y + FIELD_H + FIELD_GAP;
    l_text(ren, font_small, "Password", fx, pf_y, L_DIM);
    pf_y += 18;

    LColor pf_bg = (login->focused_field == LOGIN_FIELD_PASSWORD) ? L_FIELD_FOCUS : L_FIELD_BG;
    l_fill(ren, fx, pf_y, FORM_W, FIELD_H, pf_bg);
    LColor pf_border = (login->focused_field == LOGIN_FIELD_PASSWORD) ? L_ACCENT : L_BORDER;
    SDL_SetRenderDrawColor(ren, pf_border.r, pf_border.g, pf_border.b, pf_border.a);
    SDL_Rect pf_rect = {fx, pf_y, FORM_W, FIELD_H};
    SDL_RenderDrawRect(ren, &pf_rect);
    /* Password dots */
    if (login->password[0]) {
        char dots[128];
        size_t len = strlen(login->password);
        if (len > sizeof(dots) - 1) len = sizeof(dots) - 1;
        memset(dots, '*', len);
        dots[len] = '\0';
        l_text(ren, font, dots, fx + 14, pf_y + 12, L_TEXT);
    } else {
        l_text(ren, font, "Enter password", fx + 14, pf_y + 12, L_DIM);
    }
    /* Cursor blink */
    if (login->focused_field == LOGIN_FIELD_PASSWORD && (SDL_GetTicks() / 500) % 2 == 0) {
        int tw = 0;
        if (login->password[0]) {
            size_t len = strlen(login->password);
            char dots[128];
            if (len > sizeof(dots) - 1) len = sizeof(dots) - 1;
            memset(dots, '*', len);
            dots[len] = '\0';
            TTF_SizeUTF8(font, dots, &tw, NULL);
        }
        l_fill(ren, fx + 14 + tw, pf_y + 10, 2, FIELD_H - 20, L_ACCENT);
    }

    /* Error message */
    if (login->error_msg[0]) {
        l_text_centered(ren, font_small, login->error_msg, screen_w / 2, pf_y + FIELD_H + 10, L_RED);
    }

    /* Login button */
    int btn_y = pf_y + FIELD_H + FIELD_GAP + 8;
    if (login->error_msg[0]) btn_y += 16;
    LColor btn_bg = login->authenticating ? L_DIM : L_ACCENT;
    l_fill(ren, fx, btn_y, FORM_W, BTN_H, btn_bg);
    const char *btn_text = login->authenticating ? "Signing in..." : "Sign In";
    l_text_centered(ren, font, btn_text, screen_w / 2, btn_y + BTN_H / 2,
                    (LColor){0, 0, 0, 255});
}
