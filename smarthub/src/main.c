/*
 * OmniAgent Smart Hub — Native Touch UI
 *
 * Lightweight C application for OrangePi RV2 (RISC-V) with 7" touchscreen.
 * Uses SDL2 for rendering + touch input, libcurl for HTTP API calls.
 *
 * Build: cmake -B build && cmake --build build
 * Run:   ./build/omni-hub [server_url]
 *        ./build/omni-hub 192.168.1.100:8000
 */

#include <SDL2/SDL.h>
#include <SDL2/SDL_ttf.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include <time.h>
#include <pthread.h>
#include <curl/curl.h>
#include "keyboard.h"
#include "login.h"

/* ═══ Configuration ═══ */
#define WINDOW_W 1024
#define WINDOW_H 600
#define SIDEBAR_W 300
#define TOPBAR_H 44
#define INPUT_H 56
#define FPS 30
#define MAX_MESSAGES 100
#define MAX_MSG_LEN 4096
#define MAX_URL_LEN 1024
#define POLL_INTERVAL_MS 5000
#define WEATHER_INTERVAL_MS 300000 /* 5 min */

/* ═══ Colors ═══ */
typedef struct { Uint8 r, g, b, a; } Color;

static const Color COL_BG       = {10, 14, 20, 255};
static const Color COL_SURFACE  = {17, 24, 32, 255};
static const Color COL_CARD     = {22, 29, 39, 255};
static const Color COL_BORDER   = {30, 42, 56, 255};
static const Color COL_ACCENT   = {74, 158, 255, 255};
static const Color COL_TEXT     = {224, 232, 240, 255};
static const Color COL_DIM      = {106, 122, 138, 255};
static const Color COL_GREEN    = {63, 185, 80, 255};
static const Color COL_RED      = {255, 74, 74, 255};
static const Color COL_YELLOW   = {232, 171, 74, 255};
static const Color COL_WHITE    = {255, 255, 255, 255};
static const Color COL_USER_BG  = {74, 158, 255, 255};
static const Color COL_ASST_BG  = {22, 29, 39, 255};
static const Color COL_WEATHER  = {26, 42, 74, 255};

/* ═══ Structs ═══ */
typedef struct {
    char text[MAX_MSG_LEN];
    bool is_user;
} ChatMessage;

typedef struct {
    char location[128];
    char temp[32];
    char condition[64];
    char humidity[32];
    char wind[32];
    char feels_like[32];
    char icon[8]; /* UTF-8 emoji */
    bool valid;
} WeatherData;

typedef struct {
    int tasks_completed;
    int llm_calls;
    int tokens_in;
    int tokens_out;
    char gpu_temp[32];
    char active_model[64];
    bool ollama_online;
    bool bitnet_enabled;
    int gpu_workers;
    char version[32];
    bool connected;
} ServerMetrics;

/* ═══ Globals ═══ */
static SDL_Window *window = NULL;
static SDL_Renderer *renderer = NULL;
static TTF_Font *font_regular = NULL;
static TTF_Font *font_small = NULL;
static TTF_Font *font_large = NULL;
static TTF_Font *font_huge = NULL;

static char server_url[MAX_URL_LEN] = "";
static char detected_city[128] = "";
static char input_text[MAX_MSG_LEN] = "";
static int input_cursor = 0;
static bool input_active = false;
static bool show_connect_dialog = true;
static char connect_url_input[256] = "";
static int connect_cursor = 0;

static ChatMessage messages[MAX_MESSAGES];
static int msg_count = 0;
static int scroll_offset = 0;
static bool is_sending = false;

static WeatherData weather = {0};
static ServerMetrics metrics = {0};

static Uint32 last_poll_time = 0;
static Uint32 last_weather_time = 0;
static bool running = true;
static int screen_w = WINDOW_W;
static int screen_h = WINDOW_H;

/* Touch keyboard + Login */
static Keyboard vkb;
static LoginState login_state;

/* Forward declarations */
static void save_server_url(void);

/* ═══ Curl helper ═══ */
typedef struct {
    char *data;
    size_t size;
} CurlBuffer;

static size_t curl_write_cb(void *contents, size_t size, size_t nmemb, void *userp) {
    size_t total = size * nmemb;
    CurlBuffer *buf = (CurlBuffer *)userp;
    char *ptr = realloc(buf->data, buf->size + total + 1);
    if (!ptr) return 0;
    buf->data = ptr;
    memcpy(&buf->data[buf->size], contents, total);
    buf->size += total;
    buf->data[buf->size] = '\0';
    return total;
}

static char *http_get(const char *url) {
    CURL *curl = curl_easy_init();
    if (!curl) return NULL;
    CurlBuffer buf = {malloc(1), 0};
    buf.data[0] = '\0';
    curl_easy_setopt(curl, CURLOPT_URL, url);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, curl_write_cb);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &buf);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, 5L);
    curl_easy_setopt(curl, CURLOPT_CONNECTTIMEOUT, 3L);
    CURLcode res = curl_easy_perform(curl);
    curl_easy_cleanup(curl);
    if (res != CURLE_OK) { free(buf.data); return NULL; }
    return buf.data;
}

static char *http_post(const char *url, const char *json_body) {
    CURL *curl = curl_easy_init();
    if (!curl) return NULL;
    CurlBuffer buf = {malloc(1), 0};
    buf.data[0] = '\0';
    struct curl_slist *headers = curl_slist_append(NULL, "Content-Type: application/json");
    curl_easy_setopt(curl, CURLOPT_URL, url);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, json_body);
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, curl_write_cb);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &buf);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, 60L);
    curl_easy_setopt(curl, CURLOPT_CONNECTTIMEOUT, 5L);
    CURLcode res = curl_easy_perform(curl);
    curl_slist_free_all(headers);
    curl_easy_cleanup(curl);
    if (res != CURLE_OK) { free(buf.data); return NULL; }
    return buf.data;
}

/* ═══ Minimal JSON helpers (no dependency) ═══ */
static const char *json_find_key(const char *json, const char *key) {
    char search[256];
    snprintf(search, sizeof(search), "\"%s\"", key);
    const char *p = strstr(json, search);
    if (!p) return NULL;
    p += strlen(search);
    while (*p && (*p == ' ' || *p == ':' || *p == '\t')) p++;
    return p;
}

static void json_get_string(const char *json, const char *key, char *out, size_t out_sz) {
    out[0] = '\0';
    const char *p = json_find_key(json, key);
    if (!p || *p != '"') return;
    p++;
    size_t i = 0;
    while (*p && *p != '"' && i < out_sz - 1) {
        if (*p == '\\' && *(p+1)) { p++; } /* skip escape */
        out[i++] = *p++;
    }
    out[i] = '\0';
}

static int json_get_int(const char *json, const char *key) {
    const char *p = json_find_key(json, key);
    if (!p) return 0;
    if (*p == '"') p++; /* handle "123" */
    return atoi(p);
}

static bool json_get_bool(const char *json, const char *key) {
    const char *p = json_find_key(json, key);
    if (!p) return false;
    return strncmp(p, "true", 4) == 0;
}

/* ═══ Drawing helpers ═══ */
static void set_color(Color c) { SDL_SetRenderDrawColor(renderer, c.r, c.g, c.b, c.a); }

static void fill_rect(int x, int y, int w, int h, Color c) {
    set_color(c);
    SDL_Rect r = {x, y, w, h};
    SDL_RenderFillRect(renderer, &r);
}

static void draw_rounded_rect(int x, int y, int w, int h, int radius, Color c) {
    /* Approximate with filled rects (no GL needed) */
    fill_rect(x + radius, y, w - 2*radius, h, c);
    fill_rect(x, y + radius, w, h - 2*radius, c);
    /* Corner circles (simplified) */
    fill_rect(x, y, radius, radius, c);
    fill_rect(x + w - radius, y, radius, radius, c);
    fill_rect(x, y + h - radius, radius, radius, c);
    fill_rect(x + w - radius, y + h - radius, radius, radius, c);
}

static SDL_Texture *render_text(TTF_Font *f, const char *text, Color c, int *w, int *h) {
    if (!text || !text[0]) { if (w) *w = 0; if (h) *h = 0; return NULL; }
    SDL_Color sc = {c.r, c.g, c.b, c.a};
    SDL_Surface *surf = TTF_RenderUTF8_Blended_Wrapped(f, text, sc, 0);
    if (!surf) return NULL;
    if (w) *w = surf->w;
    if (h) *h = surf->h;
    SDL_Texture *tex = SDL_CreateTextureFromSurface(renderer, surf);
    SDL_FreeSurface(surf);
    return tex;
}

static void draw_text(TTF_Font *f, const char *text, int x, int y, Color c) {
    int w, h;
    SDL_Texture *tex = render_text(f, text, c, &w, &h);
    if (!tex) return;
    SDL_Rect dst = {x, y, w, h};
    SDL_RenderCopy(renderer, tex, NULL, &dst);
    SDL_DestroyTexture(tex);
}

__attribute__((unused))
static void draw_text_wrapped(TTF_Font *f, const char *text, int x, int y, int max_w, Color c) {
    if (!text || !text[0]) return;
    SDL_Color sc = {c.r, c.g, c.b, c.a};
    SDL_Surface *surf = TTF_RenderUTF8_Blended_Wrapped(f, text, sc, max_w);
    if (!surf) return;
    SDL_Texture *tex = SDL_CreateTextureFromSurface(renderer, surf);
    SDL_Rect dst = {x, y, surf->w, surf->h};
    SDL_RenderCopy(renderer, tex, NULL, &dst);
    SDL_FreeSurface(surf);
    SDL_DestroyTexture(tex);
}

/* ═══ Weather icon from condition ═══ */
static const char *weather_icon(const char *cond) {
    if (!cond) return "?";
    char lower[64];
    size_t i;
    for (i = 0; i < sizeof(lower)-1 && cond[i]; i++)
        lower[i] = (cond[i] >= 'A' && cond[i] <= 'Z') ? cond[i] + 32 : cond[i];
    lower[i] = '\0';
    if (strstr(lower, "clear") || strstr(lower, "sunny")) return "Sun";
    if (strstr(lower, "partly")) return "P.Cloud";
    if (strstr(lower, "overcast") || strstr(lower, "cloud")) return "Cloud";
    if (strstr(lower, "rain") || strstr(lower, "drizzle")) return "Rain";
    if (strstr(lower, "thunder") || strstr(lower, "storm")) return "Storm";
    if (strstr(lower, "snow") || strstr(lower, "blizzard")) return "Snow";
    if (strstr(lower, "fog") || strstr(lower, "mist")) return "Fog";
    return "---";
}

/* ═══ API calls ═══ */
static void fetch_metrics(void) {
    char url[MAX_URL_LEN + 64];
    snprintf(url, sizeof(url), "%s/api/identify", server_url);
    char *resp = http_get(url);
    if (resp) {
        json_get_string(resp, "version", metrics.version, sizeof(metrics.version));
        metrics.connected = true;
        free(resp);
    } else {
        metrics.connected = false;
        return;
    }

    snprintf(url, sizeof(url), "%s/api/metrics", server_url);
    resp = http_get(url);
    if (resp) {
        metrics.tasks_completed = json_get_int(resp, "tasks_completed");
        metrics.llm_calls = json_get_int(resp, "total_llm_calls");
        metrics.tokens_in = json_get_int(resp, "tokens_in");
        metrics.tokens_out = json_get_int(resp, "tokens_out");
        json_get_string(resp, "gpu", metrics.gpu_temp, sizeof(metrics.gpu_temp));
        free(resp);
    }

    snprintf(url, sizeof(url), "%s/api/status", server_url);
    resp = http_get(url);
    if (resp) {
        metrics.ollama_online = json_get_bool(resp, "ollama");
        metrics.bitnet_enabled = json_get_bool(resp, "bitnet");
        metrics.gpu_workers = json_get_int(resp, "gpu_workers");
        free(resp);
    }
}

static void detect_location(void) {
    if (detected_city[0]) return; /* Already detected */
    char url[MAX_URL_LEN + 64];
    snprintf(url, sizeof(url), "%s/api/location/detect", server_url);
    char *resp = http_get(url);
    if (resp) {
        json_get_string(resp, "city", detected_city, sizeof(detected_city));
        if (detected_city[0]) {
            printf("[Hub] Location detected: %s\n", detected_city);
        }
        free(resp);
    }
    if (!detected_city[0]) {
        printf("[Hub] Could not detect location — weather widget needs manual city\n");
    }
}

static void parse_weather_json(const char *raw_json) {
    const char *cur = strstr(raw_json, "\"current\"");
    if (cur) {
        json_get_string(cur, "location", weather.location, sizeof(weather.location));
        json_get_string(cur, "temperature_f", weather.temp, sizeof(weather.temp));
        json_get_string(cur, "condition", weather.condition, sizeof(weather.condition));
        json_get_string(cur, "humidity", weather.humidity, sizeof(weather.humidity));
        json_get_string(cur, "wind", weather.wind, sizeof(weather.wind));
        json_get_string(cur, "feels_like_f", weather.feels_like, sizeof(weather.feels_like));
        weather.valid = true;
    }
}

static void fetch_weather(void) {
    /* Ensure we have a location */
    if (!detected_city[0]) detect_location();

    /* Build weather request with detected or fallback location */
    const char *city = detected_city[0] ? detected_city : "auto";
    char body[512];
    snprintf(body, sizeof(body),
        "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\","
        "\"params\":{\"name\":\"weather\",\"arguments\":{\"location\":\"%s\"}}}", city);

    char url[MAX_URL_LEN + 64];
    snprintf(url, sizeof(url), "%s/mcp", server_url);
    char *resp = http_post(url, body);
    if (!resp) return;

    /* Find RAW_JSON block */
    const char *raw = strstr(resp, "RAW_JSON:");
    if (raw) {
        parse_weather_json(raw);
    }
    free(resp);
}

static void *send_message_thread(void *arg) {
    char *text = (char *)arg;
    char url[MAX_URL_LEN + 32];
    snprintf(url, sizeof(url), "%s/chat", server_url);

    /* Escape text for JSON */
    char escaped[MAX_MSG_LEN * 2];
    size_t j = 0;
    for (size_t i = 0; text[i] && j < sizeof(escaped) - 2; i++) {
        if (text[i] == '"' || text[i] == '\\') escaped[j++] = '\\';
        if (text[i] == '\n') { escaped[j++] = '\\'; escaped[j++] = 'n'; continue; }
        escaped[j++] = text[i];
    }
    escaped[j] = '\0';

    char body[MAX_MSG_LEN * 2 + 128];
    snprintf(body, sizeof(body),
        "{\"message\":\"%s\",\"session_id\":\"hub\"}", escaped);

    char *resp = http_post(url, body);
    if (resp) {
        char reply[MAX_MSG_LEN];
        json_get_string(resp, "reply", reply, sizeof(reply));
        if (reply[0]) {
            if (msg_count < MAX_MESSAGES) {
                snprintf(messages[msg_count].text, MAX_MSG_LEN, "%s", reply);
                messages[msg_count].is_user = false;
                msg_count++;
            }
            /* If reply contains weather data, update the widget */
            const char *raw = strstr(reply, "RAW_JSON:");
            if (raw) {
                parse_weather_json(raw);
            }
        }
        free(resp);
    } else {
        if (msg_count < MAX_MESSAGES) {
            strcpy(messages[msg_count].text, "Connection error — check server");
            messages[msg_count].is_user = false;
            msg_count++;
        }
    }
    is_sending = false;
    free(text);
    return NULL;
}

static void send_message(void) {
    if (!input_text[0] || is_sending) return;

    /* Add user message */
    if (msg_count < MAX_MESSAGES) {
        snprintf(messages[msg_count].text, MAX_MSG_LEN, "%s", input_text);
        messages[msg_count].is_user = true;
        msg_count++;
    }

    char *text_copy = strdup(input_text);
    input_text[0] = '\0';
    input_cursor = 0;
    is_sending = true;

    pthread_t tid;
    pthread_create(&tid, NULL, send_message_thread, text_copy);
    pthread_detach(tid);
}

/* ═══ Quick Actions ═══ */
typedef struct { const char *icon; const char *label; const char *command; } QuickAction;
static const QuickAction actions[] = {
    {"W", "Weather",  "What is the weather right now?"},
    {"T", "Time",     "What time is it?"},
    {"S", "Status",   "Show system status"},
    {"#", "Tests",    "Run the test suite"},
    {"G", "Git Log",  "Show git log"},
    {"!", "Tasks",    "What tasks are running?"},
};
#define NUM_ACTIONS 6

/* ═══ Drawing ═══ */
static void draw_topbar(void) {
    fill_rect(0, 0, screen_w, TOPBAR_H, COL_SURFACE);
    fill_rect(0, TOPBAR_H - 1, screen_w, 1, COL_BORDER);

    /* Status dot */
    Color dot = metrics.connected ? COL_GREEN : COL_RED;
    fill_rect(12, TOPBAR_H/2 - 4, 8, 8, dot);

    /* Title */
    draw_text(font_regular, "OmniAgent Hub", 28, 12, COL_ACCENT);

    if (metrics.version[0]) {
        char ver[64];
        snprintf(ver, sizeof(ver), "v%s", metrics.version);
        draw_text(font_small, ver, 170, 16, COL_DIM);
    }

    /* Right side: GPU + time */
    if (metrics.gpu_temp[0] && strcmp(metrics.gpu_temp, "--") != 0) {
        char gpu[64];
        snprintf(gpu, sizeof(gpu), "GPU %s", metrics.gpu_temp);
        draw_text(font_small, gpu, screen_w - 200, 16, COL_YELLOW);
    }

    time_t now = time(NULL);
    struct tm *t = localtime(&now);
    char timestr[32];
    strftime(timestr, sizeof(timestr), "%H:%M", t);
    draw_text(font_regular, timestr, screen_w - 70, 12, COL_DIM);
}

static void draw_weather_widget(int x, int y, int w) {
    draw_rounded_rect(x, y, w, 130, 8, COL_WEATHER);
    /* Accent bar */
    fill_rect(x, y, w, 2, COL_ACCENT);

    draw_text(font_small, "WEATHER", x + 12, y + 8, COL_DIM);

    if (weather.valid) {
        draw_text(font_huge, weather.temp, x + 12, y + 28, COL_WHITE);

        const char *icon = weather_icon(weather.condition);
        draw_text(font_large, icon, x + w - 70, y + 28, COL_TEXT);

        draw_text(font_small, weather.condition, x + 12, y + 75, COL_DIM);
        draw_text(font_small, weather.location, x + 12, y + 92, COL_ACCENT);

        fill_rect(x + 8, y + 108, w - 16, 1, COL_BORDER);
        char detail[128];
        snprintf(detail, sizeof(detail), "Humidity: %s   Wind: %s", weather.humidity, weather.wind);
        draw_text(font_small, detail, x + 12, y + 112, COL_DIM);
    } else {
        draw_text(font_regular, "Loading...", x + 12, y + 55, COL_DIM);
    }
}

static void draw_metrics_widget(int x, int y, int w) {
    draw_rounded_rect(x, y, w, 90, 8, COL_CARD);
    fill_rect(x, y, w, 2, COL_GREEN);
    draw_text(font_small, "LIVE METRICS", x + 12, y + 8, COL_DIM);

    int col_w = w / 2;
    char buf[32];

    snprintf(buf, sizeof(buf), "%d", metrics.tasks_completed);
    draw_text(font_large, buf, x + col_w/2 - 10, y + 28, COL_TEXT);
    draw_text(font_small, "Tasks", x + col_w/2 - 14, y + 55, COL_DIM);

    snprintf(buf, sizeof(buf), "%d", metrics.llm_calls);
    draw_text(font_large, buf, x + col_w + col_w/2 - 10, y + 28, COL_TEXT);
    draw_text(font_small, "LLM Calls", x + col_w + col_w/2 - 22, y + 55, COL_DIM);

    char tokens[64];
    snprintf(tokens, sizeof(tokens), "In: %dk  Out: %dk",
        metrics.tokens_in / 1000, metrics.tokens_out / 1000);
    draw_text(font_small, tokens, x + 12, y + 72, COL_DIM);
}

static void draw_actions_widget(int x, int y, int w) {
    draw_rounded_rect(x, y, w, 160, 8, COL_CARD);
    fill_rect(x, y, w, 2, (Color){138, 106, 255, 255});
    draw_text(font_small, "QUICK ACTIONS", x + 12, y + 8, COL_DIM);

    int btn_w = (w - 32) / 2;
    int btn_h = 44;
    for (int i = 0; i < NUM_ACTIONS; i++) {
        int col = i % 2;
        int row = i / 2;
        int bx = x + 8 + col * (btn_w + 8);
        int by = y + 28 + row * (btn_h + 6);
        draw_rounded_rect(bx, by, btn_w, btn_h, 6, COL_SURFACE);
        draw_text(font_small, actions[i].icon, bx + 10, by + 8, COL_ACCENT);
        draw_text(font_small, actions[i].label, bx + 28, by + 8, COL_TEXT);
    }
}

static void draw_status_widget(int x, int y, int w) {
    draw_rounded_rect(x, y, w, 80, 8, COL_CARD);
    fill_rect(x, y, w, 2, COL_YELLOW);
    draw_text(font_small, "SERVER", x + 12, y + 8, COL_DIM);

    Color oc = metrics.ollama_online ? COL_GREEN : COL_RED;
    draw_text(font_small, "Ollama", x + 12, y + 28, COL_DIM);
    draw_text(font_small, metrics.ollama_online ? "Online" : "Offline", x + w - 80, y + 28, oc);

    Color bc = metrics.bitnet_enabled ? COL_GREEN : COL_DIM;
    draw_text(font_small, "BitNet", x + 12, y + 44, COL_DIM);
    draw_text(font_small, metrics.bitnet_enabled ? "On" : "Off", x + w - 80, y + 44, bc);

    char wk[16];
    snprintf(wk, sizeof(wk), "%d", metrics.gpu_workers);
    draw_text(font_small, "Workers", x + 12, y + 60, COL_DIM);
    draw_text(font_small, wk, x + w - 80, y + 60, COL_TEXT);
}

static void draw_sidebar(void) {
    fill_rect(0, TOPBAR_H, SIDEBAR_W, screen_h - TOPBAR_H, COL_SURFACE);
    fill_rect(SIDEBAR_W - 1, TOPBAR_H, 1, screen_h - TOPBAR_H, COL_BORDER);

    int x = 8, y = TOPBAR_H + 8, w = SIDEBAR_W - 16;
    draw_weather_widget(x, y, w);
    y += 138;
    draw_metrics_widget(x, y, w);
    y += 98;
    draw_actions_widget(x, y, w);
    y += 168;
    draw_status_widget(x, y, w);
}

static void draw_chat(void) {
    int cx = SIDEBAR_W;
    int cy = TOPBAR_H;
    int cw = screen_w - SIDEBAR_W;
    int ch = screen_h - TOPBAR_H - INPUT_H;

    fill_rect(cx, cy, cw, ch, COL_BG);

    /* Messages */
    int y = cy + 8 - scroll_offset;
    for (int i = 0; i < msg_count; i++) {
        Color bg = messages[i].is_user ? COL_USER_BG : COL_ASST_BG;
        Color fg = messages[i].is_user ? (Color){0,0,0,255} : COL_TEXT;
        int max_w = cw - 80;

        /* Measure text height */
        int tw, th;
        SDL_Color sc = {fg.r, fg.g, fg.b, fg.a};
        SDL_Surface *surf = TTF_RenderUTF8_Blended_Wrapped(font_small, messages[i].text, sc, max_w - 20);
        if (!surf) continue;
        tw = surf->w;
        th = surf->h;

        int bx = messages[i].is_user ? cx + cw - tw - 36 : cx + 12;
        int by = y;
        int bw = tw + 24;
        int bh = th + 16;

        if (by + bh > cy && by < cy + ch) {
            draw_rounded_rect(bx, by, bw, bh, 10, bg);
            if (!messages[i].is_user) {
                /* Border for assistant */
                set_color(COL_BORDER);
                SDL_Rect br = {bx, by, bw, bh};
                SDL_RenderDrawRect(renderer, &br);
            }
            SDL_Texture *tex = SDL_CreateTextureFromSurface(renderer, surf);
            SDL_Rect dst = {bx + 12, by + 8, tw, th};
            SDL_RenderCopy(renderer, tex, NULL, &dst);
            SDL_DestroyTexture(tex);
        }
        SDL_FreeSurface(surf);
        y += th + 24;
    }

    /* Sending indicator */
    if (is_sending) {
        draw_text(font_small, "Thinking...", cx + 16, y, COL_DIM);
    }
}

static void draw_input_bar(void) {
    int iy = screen_h - INPUT_H;
    fill_rect(SIDEBAR_W, iy, screen_w - SIDEBAR_W, INPUT_H, COL_SURFACE);
    fill_rect(SIDEBAR_W, iy, screen_w - SIDEBAR_W, 1, COL_BORDER);

    /* Input field */
    int fx = SIDEBAR_W + 12;
    int fy = iy + 8;
    int fw = screen_w - SIDEBAR_W - 80;
    int fh = INPUT_H - 16;

    draw_rounded_rect(fx, fy, fw, fh, 16, COL_CARD);
    if (input_active) {
        set_color(COL_ACCENT);
        SDL_Rect br = {fx, fy, fw, fh};
        SDL_RenderDrawRect(renderer, &br);
    }

    if (input_text[0]) {
        draw_text(font_regular, input_text, fx + 14, fy + 8, COL_TEXT);
    } else {
        draw_text(font_regular, "Ask OmniAgent...", fx + 14, fy + 8, COL_DIM);
    }

    /* Send button */
    int bx = screen_w - 56;
    int by = iy + 8;
    Color btn_c = (input_text[0] && !is_sending) ? COL_ACCENT : COL_BORDER;
    draw_rounded_rect(bx, by, 44, 40, 20, btn_c);
    draw_text(font_regular, ">", bx + 16, by + 8, is_sending ? COL_DIM : COL_BG);
}

static void draw_connect_dialog(void) {
    /* Overlay */
    SDL_SetRenderDrawBlendMode(renderer, SDL_BLENDMODE_BLEND);
    set_color((Color){0, 0, 0, 180});
    SDL_Rect full = {0, 0, screen_w, screen_h};
    SDL_RenderFillRect(renderer, &full);

    int dw = 380, dh = 200;
    int dx = (screen_w - dw) / 2, dy = (screen_h - dh) / 2;

    draw_rounded_rect(dx, dy, dw, dh, 12, COL_SURFACE);

    draw_text(font_large, "Connect to OmniAgent", dx + 50, dy + 20, COL_ACCENT);

    /* URL input */
    draw_rounded_rect(dx + 20, dy + 60, dw - 40, 44, 8, COL_CARD);
    if (connect_url_input[0]) {
        draw_text(font_regular, connect_url_input, dx + 32, dy + 72, COL_TEXT);
    } else {
        draw_text(font_regular, "Server IP (e.g. 192.168.1.100:8000)", dx + 32, dy + 72, COL_DIM);
    }

    /* Connect button */
    draw_rounded_rect(dx + 20, dy + 120, dw - 40, 48, 8, COL_ACCENT);
    draw_text(font_regular, "Connect", dx + dw/2 - 30, dy + 132, COL_BG);
}

/* ═══ Touch/Click handling ═══ */
static void handle_touch(int x, int y) {
    if (show_connect_dialog) {
        int dw = 380, dh = 200;
        int dx = (screen_w - dw) / 2, dy = (screen_h - dh) / 2;

        /* Input field */
        if (x >= dx + 20 && x <= dx + dw - 20 && y >= dy + 60 && y <= dy + 104) {
            SDL_StartTextInput();
            input_active = false; /* Use connect input */
            return;
        }
        /* Connect button */
        if (x >= dx + 20 && x <= dx + dw - 20 && y >= dy + 120 && y <= dy + 168) {
            if (connect_url_input[0]) {
                if (strncmp(connect_url_input, "http", 4) != 0) {
                    snprintf(server_url, sizeof(server_url), "http://%s", connect_url_input);
                } else {
                    strncpy(server_url, connect_url_input, sizeof(server_url) - 1);
                }
                fetch_metrics();
                if (metrics.connected) {
                    show_connect_dialog = false;
                    save_server_url();
                    fetch_weather();
                }
            }
            return;
        }
        return;
    }

    /* Sidebar touches */
    if (x < SIDEBAR_W) {
        /* Weather widget tap — refresh now */
        int wy = TOPBAR_H + 8;
        if (y >= wy && y <= wy + 130) {
            last_weather_time = 0; /* triggers fetch on next frame */
            return;
        }

        /* Quick action buttons */
        int ax = 8, ay = TOPBAR_H + 8 + 138 + 98 + 28;
        int btn_w = (SIDEBAR_W - 32) / 2;
        int btn_h = 44;
        for (int i = 0; i < NUM_ACTIONS; i++) {
            int col = i % 2;
            int row = i / 2;
            int bx = ax + 8 + col * (btn_w + 8);
            int by = ay + row * (btn_h + 6);
            if (x >= bx && x <= bx + btn_w && y >= by && y <= by + btn_h) {
                /* Weather action — inject detected city */
                if (i == 0 && detected_city[0]) {
                    snprintf(input_text, sizeof(input_text),
                             "What is the weather in %s right now?", detected_city);
                } else {
                    snprintf(input_text, sizeof(input_text), "%s", actions[i].command);
                }
                input_cursor = (int)strlen(input_text);
                send_message();
                return;
            }
        }
        return;
    }

    /* Input field */
    int kb_h = kb_get_height(&vkb);
    int iy = screen_h - INPUT_H - kb_h;
    if (y >= iy && y < screen_h - kb_h) {
        if (x >= screen_w - 56) {
            /* Send button */
            send_message();
        } else {
            /* Text field — show virtual keyboard */
            input_active = true;
            kb_attach(&vkb, input_text, &input_cursor, sizeof(input_text));
            kb_show(&vkb);
        }
        return;
    }
}

/* ═══ Auto-Discovery ═══ */

static bool try_server(const char *host) {
    char url[MAX_URL_LEN + 64];
    snprintf(url, sizeof(url), "http://%s/api/identify", host);
    char *resp = http_get(url);
    if (resp) {
        bool found = strstr(resp, "OmniAgent") != NULL;
        free(resp);
        return found;
    }
    return false;
}

static bool auto_discover(void) {
    printf("[Hub] Auto-discovering OmniAgent server...\n");

    /* 1. Try saved URL from config file */
    const char *home = getenv("HOME");
    if (home) {
        char cfg_path[512];
        snprintf(cfg_path, sizeof(cfg_path), "%s/.omniagent-hub-url", home);
        FILE *f = fopen(cfg_path, "r");
        if (f) {
            char saved[256] = {0};
            if (fgets(saved, sizeof(saved), f)) {
                /* Strip newline */
                char *nl = strchr(saved, '\n');
                if (nl) *nl = '\0';
                if (saved[0] && try_server(saved)) {
                    snprintf(server_url, sizeof(server_url), "http://%s", saved);
                    printf("[Hub] Connected to saved server: %s\n", saved);
                    fclose(f);
                    return true;
                }
            }
            fclose(f);
        }
    }

    /* 2. Try default: 192.168.254.2:8000 */
    if (try_server("192.168.254.2:8000")) {
        snprintf(server_url, sizeof(server_url), "http://192.168.254.2:8000");
        printf("[Hub] Found server at default: 192.168.254.2:8000\n");
        return true;
    }

    /* 3. Try common LAN addresses */
    const char *common[] = {
        "192.168.1.1:8000", "192.168.1.2:8000", "192.168.1.100:8000",
        "192.168.0.1:8000", "192.168.0.2:8000", "192.168.0.100:8000",
        "10.0.0.1:8000",   "10.0.0.2:8000",
        NULL
    };
    for (int i = 0; common[i]; i++) {
        if (try_server(common[i])) {
            snprintf(server_url, sizeof(server_url), "http://%s", common[i]);
            printf("[Hub] Found server at: %s\n", common[i]);
            return true;
        }
    }

    printf("[Hub] No server found — showing connect dialog\n");
    return false;
}

static void save_server_url(void) {
    /* Save the working URL for next boot */
    const char *home = getenv("HOME");
    if (!home || !server_url[0]) return;
    char cfg_path[512];
    snprintf(cfg_path, sizeof(cfg_path), "%s/.omniagent-hub-url", home);
    FILE *f = fopen(cfg_path, "w");
    if (f) {
        /* Strip http:// prefix for storage */
        const char *host = server_url;
        if (strncmp(host, "http://", 7) == 0) host += 7;
        fprintf(f, "%s\n", host);
        fclose(f);
    }
}

/* ═══ Main ═══ */
int main(int argc, char *argv[]) {
    curl_global_init(CURL_GLOBAL_DEFAULT);

    /* Optional: server URL from command line */
    if (argc > 1) {
        if (strncmp(argv[1], "http", 4) != 0)
            snprintf(server_url, sizeof(server_url), "http://%s", argv[1]);
        else
            snprintf(server_url, sizeof(server_url), "%s", argv[1]);
        show_connect_dialog = false;
    } else {
        /* Auto-discover server on LAN */
        if (auto_discover()) {
            show_connect_dialog = false;
            save_server_url();
            /* Go to login screen */
            login_state.active = true;
            snprintf(login_state.server_display, sizeof(login_state.server_display),
                     "Connected to %s", server_url);
        }
    }

    if (SDL_Init(SDL_INIT_VIDEO | SDL_INIT_EVENTS) < 0) {
        fprintf(stderr, "SDL_Init failed: %s\n", SDL_GetError());
        return 1;
    }
    if (TTF_Init() < 0) {
        fprintf(stderr, "TTF_Init failed: %s\n", TTF_GetError());
        return 1;
    }

    window = SDL_CreateWindow("OmniAgent Hub",
        SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED,
        screen_w, screen_h,
        SDL_WINDOW_SHOWN | SDL_WINDOW_ALLOW_HIGHDPI | SDL_WINDOW_FULLSCREEN_DESKTOP);
    if (!window) {
        /* Fallback to windowed if fullscreen fails */
        window = SDL_CreateWindow("OmniAgent Hub",
            SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED,
            screen_w, screen_h, SDL_WINDOW_SHOWN | SDL_WINDOW_ALLOW_HIGHDPI);
    }
    if (!window) {
        fprintf(stderr, "Window failed: %s\n", SDL_GetError());
        return 1;
    }

    /* Get actual window size (may differ from screen_w/H in fullscreen) */
    SDL_GetWindowSize(window, &screen_w, &screen_h);
    printf("[Hub] Display: %dx%d\n", screen_w, screen_h);

    renderer = SDL_CreateRenderer(window, -1, SDL_RENDERER_ACCELERATED | SDL_RENDERER_PRESENTVSYNC);
    if (!renderer) {
        renderer = SDL_CreateRenderer(window, -1, SDL_RENDERER_SOFTWARE);
    }

    /* Load fonts — try common locations */
    const char *font_paths[] = {
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/usr/share/fonts/noto/NotoSans-Regular.ttf",
        NULL
    };
    const char *font_path = NULL;
    for (int i = 0; font_paths[i]; i++) {
        if (TTF_OpenFont(font_paths[i], 14)) {
            font_path = font_paths[i];
            break;
        }
    }
    if (!font_path) font_path = font_paths[0]; /* fallback */

    font_small   = TTF_OpenFont(font_path, 12);
    font_regular = TTF_OpenFont(font_path, 16);
    font_large   = TTF_OpenFont(font_path, 22);
    font_huge    = TTF_OpenFont(font_path, 36);

    if (!font_regular) {
        fprintf(stderr, "Failed to load font from %s: %s\n", font_path, TTF_GetError());
        fprintf(stderr, "Install: sudo apt install fonts-dejavu-core\n");
        return 1;
    }

    /* Initialize keyboard and login */
    kb_init(&vkb);
    login_init(&login_state);

    /* Initial fetch if URL provided */
    if (server_url[0]) {
        fetch_metrics();
        if (metrics.connected) {
            snprintf(login_state.server_display, sizeof(login_state.server_display),
                     "Connected to %s", server_url);
            fetch_weather();
        }
    }
    /* If not connected, login screen will show but user needs to connect first */
    if (!server_url[0]) {
        login_state.active = false; /* Show connect dialog first */
    }

    SDL_Event event;
    Uint32 frame_start;

    while (running) {
        frame_start = SDL_GetTicks();

        while (SDL_PollEvent(&event)) {
            if (event.type == SDL_QUIT) { running = false; break; }

            /* Escape key: hide keyboard or quit */
            if (event.type == SDL_KEYDOWN && event.key.keysym.sym == SDLK_ESCAPE) {
                if (vkb.visible) { kb_hide(&vkb); }
                else if (input_active) { input_active = false; }
                else { running = false; }
                continue;
            }

            /* Virtual keyboard consumes touch events in its area */
            if (kb_handle_event(&vkb, &event, screen_w, screen_h)) {
                /* Check if keyboard enter was pressed while on login screen */
                if (!vkb.visible && login_state.active && login_state.focused_field == LOGIN_FIELD_PASSWORD) {
                    login_attempt(&login_state, server_url);
                }
                continue;
            }

            /* Login screen consumes all events when active */
            if (login_state.active) {
                if (login_handle_event(&login_state, &vkb, &event, screen_w, screen_h)) {
                    /* Check if login button was tapped (field is NONE after tap) */
                    if (login_state.focused_field == LOGIN_FIELD_NONE
                        && login_state.username[0] && login_state.password[0]
                        && !login_state.authenticating && !login_state.authenticated) {
                        login_attempt(&login_state, server_url);
                    }
                    continue;
                }
            }

            /* Connect dialog */
            if (show_connect_dialog) {
                int tx = -1, ty = -1;
                if (event.type == SDL_MOUSEBUTTONDOWN) { tx = event.button.x; ty = event.button.y; }
                else if (event.type == SDL_FINGERDOWN) { tx = (int)(event.tfinger.x * screen_w); ty = (int)(event.tfinger.y * screen_h); }

                if (tx >= 0) {
                    int dw = 380, dh = 200;
                    int dx = (screen_w - dw) / 2, dy = (screen_h - dh) / 2;
                    /* URL input field — attach keyboard */
                    if (tx >= dx + 20 && tx <= dx + dw - 20 && ty >= dy + 60 && ty <= dy + 104) {
                        kb_attach(&vkb, connect_url_input, &connect_cursor, sizeof(connect_url_input));
                        kb_show(&vkb);
                    }
                    /* Connect button */
                    if (tx >= dx + 20 && tx <= dx + dw - 20 && ty >= dy + 120 && ty <= dy + 168) {
                        kb_hide(&vkb);
                        if (connect_url_input[0]) {
                            if (strncmp(connect_url_input, "http", 4) != 0)
                                snprintf(server_url, sizeof(server_url), "http://%s", connect_url_input);
                            else
                                snprintf(server_url, sizeof(server_url), "%s", connect_url_input);
                            fetch_metrics();
                            if (metrics.connected) {
                                show_connect_dialog = false;
                                save_server_url();
                                snprintf(login_state.server_display, sizeof(login_state.server_display),
                                         "Connected to %s", connect_url_input);
                                login_state.active = true; /* Show login */
                            }
                        }
                    }
                }
                /* Physical keyboard input for connect dialog */
                if (event.type == SDL_TEXTINPUT && !vkb.visible) {
                    size_t len = strlen(connect_url_input);
                    if (len + strlen(event.text.text) < sizeof(connect_url_input) - 1) {
                        strcat(connect_url_input, event.text.text);
                    }
                } else if (event.type == SDL_KEYDOWN && !vkb.visible) {
                    if (event.key.keysym.sym == SDLK_RETURN) {
                        handle_touch(screen_w/2, screen_h/2 + 40);
                    } else if (event.key.keysym.sym == SDLK_BACKSPACE) {
                        size_t len = strlen(connect_url_input);
                        if (len > 0) connect_url_input[len - 1] = '\0';
                    }
                }
                continue;
            }

            /* Main hub event handling */
            switch (event.type) {
            case SDL_MOUSEBUTTONDOWN:
            case SDL_FINGERDOWN: {
                int tx, ty;
                if (event.type == SDL_FINGERDOWN) {
                    tx = (int)(event.tfinger.x * screen_w);
                    ty = (int)(event.tfinger.y * screen_h);
                } else {
                    tx = event.button.x;
                    ty = event.button.y;
                }
                handle_touch(tx, ty);
                break;
            }
            case SDL_TEXTINPUT:
                /* Physical keyboard input (fallback when virtual kb hidden) */
                if (!vkb.visible && input_active) {
                    size_t len = strlen(input_text);
                    if (len + strlen(event.text.text) < sizeof(input_text) - 1) {
                        strcat(input_text, event.text.text);
                        input_cursor = strlen(input_text);
                    }
                }
                break;
            case SDL_KEYDOWN:
                if (!vkb.visible) {
                    if (event.key.keysym.sym == SDLK_RETURN) send_message();
                    else if (event.key.keysym.sym == SDLK_BACKSPACE) {
                        size_t len = strlen(input_text);
                        if (len > 0) input_text[len - 1] = '\0';
                    }
                }
                break;
            case SDL_MOUSEWHEEL:
                scroll_offset -= event.wheel.y * 30;
                if (scroll_offset < 0) scroll_offset = 0;
                break;
            default: break;
            }
        }

        /* Update keyboard (backspace repeat) */
        kb_update(&vkb);

        /* Periodic polling (only when logged in) */
        Uint32 now = SDL_GetTicks();
        if (!show_connect_dialog && !login_state.active && server_url[0]) {
            if (now - last_poll_time > POLL_INTERVAL_MS) {
                last_poll_time = now;
                fetch_metrics();
            }
            /* Fetch weather: immediately on first frame after login, then every 15 min */
            if (last_weather_time == 0 || now - last_weather_time > WEATHER_INTERVAL_MS) {
                last_weather_time = now;
                fetch_weather();
            }
        }

        /* Render */
        set_color(COL_BG);
        SDL_RenderClear(renderer);

        if (show_connect_dialog) {
            draw_connect_dialog();
            kb_render(&vkb, renderer, font_regular, font_small, screen_w, screen_h);
        } else if (login_state.active) {
            login_render(&login_state, renderer, font_regular, font_small, font_large,
                         screen_w, screen_h);
            kb_render(&vkb, renderer, font_regular, font_small, screen_w, screen_h);
        } else {
            draw_topbar();
            draw_sidebar();
            draw_chat();
            draw_input_bar();
            kb_render(&vkb, renderer, font_regular, font_small, screen_w, screen_h);
        }

        SDL_RenderPresent(renderer);

        /* Frame rate limit */
        Uint32 elapsed = SDL_GetTicks() - frame_start;
        if (elapsed < 1000 / FPS) {
            SDL_Delay(1000 / FPS - elapsed);
        }
    }

    /* Cleanup */
    if (font_small) TTF_CloseFont(font_small);
    if (font_regular) TTF_CloseFont(font_regular);
    if (font_large) TTF_CloseFont(font_large);
    if (font_huge) TTF_CloseFont(font_huge);
    SDL_DestroyRenderer(renderer);
    SDL_DestroyWindow(window);
    TTF_Quit();
    curl_global_cleanup();
    SDL_Quit();
    return 0;
}
