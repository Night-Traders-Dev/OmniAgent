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
#include <math.h>
#include <pthread.h>
#include <curl/curl.h>
#include <SDL2/SDL_image.h>
#include "keyboard.h"
#include "login.h"
#include "background.h"
#include "menu.h"

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
#define TAB_BAR_H 36

/* ═══ Colors (warm, homey palette with transparency for animated bg) ═══ */
typedef struct { Uint8 r, g, b, a; } Color;

static const Color COL_BG       = {8, 10, 18, 255};
static const Color COL_SURFACE  = {14, 18, 28, 200};   /* Semi-transparent — bg shows through */
static const Color COL_CARD     = {18, 24, 36, 180};
static const Color COL_BORDER   = {40, 50, 70, 120};
static const Color COL_ACCENT   = {100, 160, 240, 255};
static const Color COL_TEXT     = {230, 235, 245, 255};
static const Color COL_DIM      = {120, 135, 155, 255};
static const Color COL_GREEN    = {80, 200, 120, 255};
static const Color COL_RED      = {240, 90, 90, 255};
static const Color COL_YELLOW   = {240, 190, 100, 255};
static const Color COL_WHITE    = {255, 255, 255, 255};
static const Color COL_USER_BG  = {90, 130, 200, 220};  /* Softer blue, semi-transparent */
static const Color COL_ASST_BG  = {20, 26, 40, 190};    /* Glass-like */
static const Color COL_WEATHER  = {20, 35, 65, 200};

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
    int session_messages;
    int commands_run;
    int context_pct;
    char gpu_temp[32];
    char active_model[64];
    char status[64];
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
static char sessionId[64] = "hub";
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
static bool weather_refresh_pending = true;
static bool news_refresh_pending = true;
static bool markets_refresh_pending = true;

/* Touch keyboard + Login + Animated background + Context menu */
static Keyboard vkb;
static LoginState login_state;
static AnimatedBG anim_bg;
static ContextMenu ctx_menu;

/* Session management */
#define MAX_SESSIONS 50
typedef struct {
    char id[64];
    char title[128];
    int message_count;
} SessionEntry;
static SessionEntry sessions[MAX_SESSIONS];
static int session_count = 0;
static bool show_session_drawer = false;

/* Smart reply chips */
#define MAX_CHIPS 4
static char smart_chips[MAX_CHIPS][128];
static int chip_count = 0;

/* Sidebar tabs: Home / News / Markets / Settings */
typedef enum { TAB_HOME, TAB_NEWS, TAB_MARKETS, TAB_SETTINGS } SidebarTab;
static SidebarTab sidebar_tab = TAB_HOME;

/* News articles */
#define MAX_NEWS 8
typedef struct {
    char title[256];
    char source[64];
    char body[256];
    char url[512];
    char thumbnail_url[512];
    SDL_Texture *thumb_tex;   /* Cached texture (loaded async) */
    bool thumb_loading;
    bool thumb_failed;
} NewsArticle;
static NewsArticle news_articles[MAX_NEWS];
static int news_count = 0;
static char news_category[32] = "top";
static Uint32 last_news_time = 0;
#define NEWS_INTERVAL_MS 300000  /* 5 min */

/* Market data */
static char market_summary[1024] = "";
static Uint32 last_market_time = 0;
#define MARKET_INTERVAL_MS 300000  /* 5 min */

/* Thinking/Reasoning log */
#define MAX_THINKING 20
static char thinking_log[MAX_THINKING][256];
static int thinking_count = 0;
static bool show_thinking = false;

/* Long-press tracking */
static Uint32 touch_down_time = 0;
static int touch_down_x = 0, touch_down_y = 0;
static bool long_press_fired = false;

/* Context menu action IDs */
enum {
    ACT_COPY = 1, ACT_RESEND, ACT_RESEND_MODEL, ACT_BRANCH, ACT_PIN,
    ACT_SHARE, ACT_RATE_UP, ACT_RATE_DOWN, ACT_DELETE_MSG,
    ACT_SESSION_SWITCH, ACT_SESSION_RENAME, ACT_SESSION_DELETE, ACT_SESSION_EXPORT,
    ACT_WIDGET_REFRESH, ACT_NEW_CHAT,
};

/* Forward declarations */
static void save_server_url(void);
static void send_message(void);

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

/* ═══ Image download → SDL_Texture ═══ */
/* Downloads image bytes and creates a texture. Must be called from main thread for texture creation. */
static SDL_Texture *download_image_texture(const char *url) {
    if (!url || !url[0] || !renderer) return NULL;
    CURL *curl = curl_easy_init();
    if (!curl) return NULL;
    CurlBuffer buf = {malloc(1), 0};
    buf.data[0] = '\0';
    curl_easy_setopt(curl, CURLOPT_URL, url);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, curl_write_cb);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &buf);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, 8L);
    curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L);
    CURLcode res = curl_easy_perform(curl);
    curl_easy_cleanup(curl);
    if (res != CURLE_OK || buf.size < 100) { free(buf.data); return NULL; }

    SDL_RWops *rw = SDL_RWFromMem(buf.data, (int)buf.size);
    if (!rw) { free(buf.data); return NULL; }
    SDL_Surface *surf = IMG_Load_RW(rw, 1); /* frees RWops */
    free(buf.data);
    if (!surf) return NULL;
    SDL_Texture *tex = SDL_CreateTextureFromSurface(renderer, surf);
    SDL_FreeSurface(surf);
    return tex;
}

/* Thumbnail loader — called from main loop to lazily load thumbnails */
static void load_pending_thumbnails(void) {
    for (int i = 0; i < news_count; i++) {
        NewsArticle *a = &news_articles[i];
        if (a->thumb_tex || a->thumb_failed || a->thumb_loading || !a->thumbnail_url[0]) continue;
        /* Load one per frame to avoid blocking */
        a->thumb_loading = true;
        a->thumb_tex = download_image_texture(a->thumbnail_url);
        a->thumb_loading = false;
        if (!a->thumb_tex) a->thumb_failed = true;
        return; /* One per frame */
    }
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
    SDL_SetRenderDrawBlendMode(renderer, c.a < 255 ? SDL_BLENDMODE_BLEND : SDL_BLENDMODE_NONE);
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
        metrics.session_messages = json_get_int(resp, "session_messages");
        metrics.commands_run = json_get_int(resp, "commands_run");
        metrics.context_pct = json_get_int(resp, "context_usage_pct");
        metrics.gpu_workers = json_get_int(resp, "gpu_workers");
        json_get_string(resp, "gpu", metrics.gpu_temp, sizeof(metrics.gpu_temp));
        json_get_string(resp, "active_model", metrics.active_model, sizeof(metrics.active_model));
        json_get_string(resp, "status", metrics.status, sizeof(metrics.status));
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

    /* Fetch reasoning/thinking log (only when a task is active) */
    if (metrics.status[0] && strcmp(metrics.status, "Idle") != 0 && strcmp(metrics.status, "Finished") != 0) {
        snprintf(url, sizeof(url), "%s/api/reasoning/history?session_id=%s", server_url, sessionId);
        resp = http_get(url);
        if (resp) {
            /* Parse entries array — look for quoted strings after "entries" */
            thinking_count = 0;
            const char *p = strstr(resp, "\"entries\"");
            if (p) {
                p = strchr(p, '[');
                if (p) {
                    p++;
                    while (thinking_count < MAX_THINKING) {
                        const char *q = strchr(p, '"');
                        if (!q) break;
                        q++;
                        const char *end = strchr(q, '"');
                        if (!end) break;
                        size_t len = (size_t)(end - q);
                        if (len >= sizeof(thinking_log[0])) len = sizeof(thinking_log[0]) - 1;
                        memcpy(thinking_log[thinking_count], q, len);
                        thinking_log[thinking_count][len] = '\0';
                        thinking_count++;
                        p = end + 1;
                    }
                }
            }
            show_thinking = (thinking_count > 0);
            free(resp);
        }
    } else if (strcmp(metrics.status, "Finished") == 0) {
        /* Keep showing last thinking log briefly, then clear */
        show_thinking = (thinking_count > 0);
    } else {
        show_thinking = false;
    }
}

/* Threaded data fetchers — these do web searches which take 5-15s */
static volatile bool news_fetching = false;
static volatile bool markets_fetching = false;
static volatile bool weather_fetching = false;

typedef struct {
    char category[32];
} NewsFetchArgs;

static void *news_thread_fn(void *arg) {
    NewsFetchArgs *args = (NewsFetchArgs *)arg;
    char requested_category[32] = "top";
    if (args) {
        snprintf(requested_category, sizeof(requested_category), "%s", args->category);
        free(args);
    }
    char url[MAX_URL_LEN + 128];
    snprintf(url, sizeof(url), "%s/api/hub/news?category=%s", server_url, requested_category);
    char *resp = http_get(url);
    if (resp) {
        if (strcmp(requested_category, news_category) != 0) {
            free(resp);
            news_fetching = false;
            return NULL;
        }
        /* Free old thumbnails */
        for (int i = 0; i < news_count; i++) {
            if (news_articles[i].thumb_tex) {
                /* Can't destroy textures from non-main thread — mark for cleanup */
                news_articles[i].thumb_tex = NULL;
            }
        }
        news_count = 0;
        const char *p = resp;
        while (news_count < MAX_NEWS) {
            const char *title_key = strstr(p, "\"title\"");
            if (!title_key) break;
            memset(&news_articles[news_count], 0, sizeof(NewsArticle));
            json_get_string(title_key - 1, "title", news_articles[news_count].title, sizeof(news_articles[0].title));
            json_get_string(title_key - 1, "source", news_articles[news_count].source, sizeof(news_articles[0].source));
            json_get_string(title_key - 1, "body", news_articles[news_count].body, sizeof(news_articles[0].body));
            json_get_string(title_key - 1, "url", news_articles[news_count].url, sizeof(news_articles[0].url));
            json_get_string(title_key - 1, "thumbnail", news_articles[news_count].thumbnail_url, sizeof(news_articles[0].thumbnail_url));
            if (news_articles[news_count].title[0]) news_count++;
            p = title_key + 7;
        }
        free(resp);
    }
    news_fetching = false;
    return NULL;
}

static bool fetch_news(void) {
    if (news_fetching) return false;
    news_fetching = true;
    NewsFetchArgs *args = malloc(sizeof(NewsFetchArgs));
    if (!args) {
        news_fetching = false;
        return false;
    }
    snprintf(args->category, sizeof(args->category), "%s", news_category);
    pthread_t tid;
    if (pthread_create(&tid, NULL, news_thread_fn, args) != 0) {
        free(args);
        news_fetching = false;
        return false;
    }
    pthread_detach(tid);
    return true;
}

static void *markets_thread_fn(void *arg) {
    (void)arg;
    char url[MAX_URL_LEN + 64];
    snprintf(url, sizeof(url), "%s/api/hub/markets", server_url);
    char *resp = http_get(url);
    if (resp) {
        json_get_string(resp, "summary", market_summary, sizeof(market_summary));
        free(resp);
    }
    markets_fetching = false;
    return NULL;
}

static bool fetch_markets(void) {
    if (markets_fetching) return false;
    markets_fetching = true;
    pthread_t tid;
    if (pthread_create(&tid, NULL, markets_thread_fn, NULL) != 0) {
        markets_fetching = false;
        return false;
    }
    pthread_detach(tid);
    return true;
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

/* Unescape JSON string in-place: \n→newline, \"→quote, \\→backslash, \uXXXX→char */
static void json_unescape(char *s) {
    char *r = s, *w = s;
    while (*r) {
        if (*r == '\\' && *(r+1)) {
            r++;
            switch (*r) {
                case 'n': *w++ = '\n'; r++; break;
                case 't': *w++ = '\t'; r++; break;
                case '"': *w++ = '"';  r++; break;
                case '\\': *w++ = '\\'; r++; break;
                case 'u': {
                    /* \uXXXX — decode to UTF-8 (simplified: just skip for now) */
                    unsigned int cp = 0;
                    if (r[1] && r[2] && r[3] && r[4]) {
                        sscanf(r+1, "%4x", &cp);
                        r += 5;
                        if (cp < 0x80) { *w++ = (char)cp; }
                        else if (cp < 0x800) { *w++ = (char)(0xC0 | (cp >> 6)); *w++ = (char)(0x80 | (cp & 0x3F)); }
                        else { *w++ = (char)(0xE0 | (cp >> 12)); *w++ = (char)(0x80 | ((cp >> 6) & 0x3F)); *w++ = (char)(0x80 | (cp & 0x3F)); }
                    } else { *w++ = '?'; r++; }
                    break;
                }
                default: *w++ = *r++; break;
            }
        } else {
            *w++ = *r++;
        }
    }
    *w = '\0';
}

static void *weather_thread_fn(void *arg) {
    (void)arg;
    if (!detected_city[0]) detect_location();

    const char *city = detected_city[0] ? detected_city : "auto";
    char body[512];
    snprintf(body, sizeof(body),
        "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\","
        "\"params\":{\"name\":\"weather\",\"arguments\":{\"location\":\"%s\"}}}", city);

    char url[MAX_URL_LEN + 64];
    snprintf(url, sizeof(url), "%s/mcp", server_url);
    char *resp = http_post(url, body);
    if (resp) {
        /* The response is a JSON-RPC wrapper with escaped text inside.
           Unescape twice — outer JSON escaping + inner RAW_JSON escaping. */
        json_unescape(resp);
        json_unescape(resp);
        const char *raw = strstr(resp, "RAW_JSON:");
        if (raw) parse_weather_json(raw);
        free(resp);
    }
    weather_fetching = false;
    return NULL;
}

static bool fetch_weather(void) {
    if (weather_fetching) return false;
    weather_fetching = true;
    pthread_t tid;
    if (pthread_create(&tid, NULL, weather_thread_fn, NULL) != 0) {
        weather_fetching = false;
        return false;
    }
    pthread_detach(tid);
    return true;
}

static void queue_hub_refresh(bool weather_now, bool news_now, bool markets_now) {
    if (weather_now) weather_refresh_pending = true;
    if (news_now) news_refresh_pending = true;
    if (markets_now) markets_refresh_pending = true;
}

/* ═══ Session Management ═══ */

static void fetch_sessions(void) {
    char url[MAX_URL_LEN + 64];
    snprintf(url, sizeof(url), "%s/api/auth/sessions?session_id=%s", server_url, sessionId);
    char *resp = http_get(url);
    if (!resp) return;
    /* Parse JSON array — minimal parse for [{id, title, message_count},...] */
    session_count = 0;
    const char *p = resp;
    while (session_count < MAX_SESSIONS) {
        const char *id_start = strstr(p, "\"id\"");
        if (!id_start) break;
        json_get_string(id_start - 1, "id", sessions[session_count].id, sizeof(sessions[0].id));
        json_get_string(id_start - 1, "title", sessions[session_count].title, sizeof(sessions[0].title));
        sessions[session_count].message_count = json_get_int(id_start - 1, "message_count");
        if (!sessions[session_count].title[0])
            snprintf(sessions[session_count].title, sizeof(sessions[0].title), "Session %d", session_count + 1);
        session_count++;
        p = id_start + 4;
    }
    free(resp);
}

static void new_chat(void) {
    char url[MAX_URL_LEN + 64];
    snprintf(url, sizeof(url), "%s/api/auth/sessions/new", server_url);
    char body[256];
    snprintf(body, sizeof(body), "{\"session_id\":\"%s\"}", sessionId);
    char *resp = http_post(url, body);
    if (resp) {
        char new_sid[64];
        json_get_string(resp, "session_id", new_sid, sizeof(new_sid));
        if (new_sid[0]) {
            snprintf(sessionId, sizeof(sessionId), "%s", new_sid);
            msg_count = 0;
            scroll_offset = 0;
            chip_count = 0;
        }
        free(resp);
    }
    fetch_sessions();
}

static void switch_session(const char *sid) {
    snprintf(sessionId, sizeof(sessionId), "%s", sid);
    /* Load messages for this session */
    char url[MAX_URL_LEN + 128];
    snprintf(url, sizeof(url), "%s/api/auth/sessions/load", server_url);
    char body[256];
    snprintf(body, sizeof(body), "{\"session_id\":\"%s\",\"target_session_id\":\"%s\"}", sessionId, sid);
    char *resp = http_post(url, body);
    msg_count = 0;
    scroll_offset = 0;
    chip_count = 0;
    if (resp) {
        /* Parse messages from response */
        const char *p = resp;
        while (msg_count < MAX_MESSAGES) {
            const char *role = strstr(p, "\"role\"");
            if (!role) break;
            char r[16], c[MAX_MSG_LEN];
            json_get_string(role - 1, "role", r, sizeof(r));
            json_get_string(role - 1, "content", c, sizeof(c));
            if (c[0]) {
                snprintf(messages[msg_count].text, MAX_MSG_LEN, "%s", c);
                messages[msg_count].is_user = (strcmp(r, "user") == 0);
                msg_count++;
            }
            p = role + 6;
        }
        free(resp);
    }
}

static void delete_session(const char *sid) {
    char url[MAX_URL_LEN + 64];
    snprintf(url, sizeof(url), "%s/api/auth/sessions/delete", server_url);
    char body[256];
    snprintf(body, sizeof(body), "{\"session_id\":\"%s\",\"target_session_id\":\"%s\"}", sessionId, sid);
    char *resp = http_post(url, body);
    if (resp) free(resp);
    fetch_sessions();
}

/* ═══ Smart Reply Chips ═══ */

static void generate_chips(const char *reply) {
    chip_count = 0;
    const char *lower = reply; /* Simple check — not actual lowercase but works for ASCII */
    if (strstr(lower, "error") || strstr(lower, "Error") || strstr(lower, "fail")) {
        snprintf(smart_chips[0], 128, "Show full error");
        snprintf(smart_chips[1], 128, "How do I fix this?");
        snprintf(smart_chips[2], 128, "Try a different approach");
        chip_count = 3;
    } else if (strstr(lower, "```") || strstr(lower, "function") || strstr(lower, "class ")) {
        snprintf(smart_chips[0], 128, "Explain this code");
        snprintf(smart_chips[1], 128, "Write tests for this");
        snprintf(smart_chips[2], 128, "Optimize it");
        chip_count = 3;
    } else if (strstr(lower, "°F") || strstr(lower, "°C") || strstr(lower, "weather")) {
        snprintf(smart_chips[0], 128, "Tomorrow's forecast?");
        snprintf(smart_chips[1], 128, "Hourly breakdown");
        snprintf(smart_chips[2], 128, "Thanks!");
        chip_count = 3;
    } else {
        snprintf(smart_chips[0], 128, "Tell me more");
        snprintf(smart_chips[1], 128, "What else can you do?");
        snprintf(smart_chips[2], 128, "Thanks!");
        chip_count = 3;
    }
}

/* ═══ Clipboard (SDL2) ═══ */

static void copy_to_clipboard(const char *text) {
    SDL_SetClipboardText(text);
}

/* ═══ Context Menu Builders ═══ */

static void show_user_msg_menu(int msg_idx, int x, int y) {
    menu_hide(&ctx_menu);
    ctx_menu.context_type = 1;
    ctx_menu.context_index = msg_idx;
    snprintf(ctx_menu.context_text, sizeof(ctx_menu.context_text), "%s", messages[msg_idx].text);
    menu_add(&ctx_menu, "C", "Copy", ACT_COPY, false, false);
    menu_add(&ctx_menu, "R", "Resend", ACT_RESEND, false, false);
    menu_add(&ctx_menu, "M", "Resend with model...", ACT_RESEND_MODEL, false, true);
    menu_add(&ctx_menu, "B", "Branch", ACT_BRANCH, false, false);
    menu_show(&ctx_menu, x, y);
}

static void show_asst_msg_menu(int msg_idx, int x, int y) {
    menu_hide(&ctx_menu);
    ctx_menu.context_type = 2;
    ctx_menu.context_index = msg_idx;
    snprintf(ctx_menu.context_text, sizeof(ctx_menu.context_text), "%s", messages[msg_idx].text);
    menu_add(&ctx_menu, "C", "Copy", ACT_COPY, false, false);
    menu_add(&ctx_menu, "S", "Share", ACT_SHARE, false, true);
    menu_add(&ctx_menu, "P", "Pin Message", ACT_PIN, false, false);
    menu_add(&ctx_menu, "+", "Rate: Good", ACT_RATE_UP, false, false);
    menu_add(&ctx_menu, "-", "Rate: Bad", ACT_RATE_DOWN, false, true);
    menu_add(&ctx_menu, "X", "Delete", ACT_DELETE_MSG, true, false);
    menu_show(&ctx_menu, x, y);
}

static void show_session_menu(int sess_idx, int x, int y) {
    menu_hide(&ctx_menu);
    ctx_menu.context_type = 3;
    ctx_menu.context_index = sess_idx;
    menu_add(&ctx_menu, "O", "Open", ACT_SESSION_SWITCH, false, true);
    menu_add(&ctx_menu, "E", "Export", ACT_SESSION_EXPORT, false, false);
    menu_add(&ctx_menu, "X", "Delete", ACT_SESSION_DELETE, true, false);
    menu_show(&ctx_menu, x, y);
}

static void handle_menu_action(int action) {
    switch (action) {
    case ACT_COPY:
        copy_to_clipboard(ctx_menu.context_text);
        break;
    case ACT_RESEND:
        snprintf(input_text, sizeof(input_text), "%s", ctx_menu.context_text);
        input_cursor = (int)strlen(input_text);
        send_message();
        break;
    case ACT_NEW_CHAT:
        new_chat();
        break;
    case ACT_SESSION_SWITCH:
        if (ctx_menu.context_index >= 0 && ctx_menu.context_index < session_count) {
            switch_session(sessions[ctx_menu.context_index].id);
            show_session_drawer = false;
        }
        break;
    case ACT_SESSION_DELETE:
        if (ctx_menu.context_index >= 0 && ctx_menu.context_index < session_count) {
            delete_session(sessions[ctx_menu.context_index].id);
        }
        break;
    case ACT_PIN: {
        char url[MAX_URL_LEN + 64];
        snprintf(url, sizeof(url), "%s/api/chat/pin", server_url);
        char body[256];
        snprintf(body, sizeof(body), "{\"session_id\":\"%s\",\"message_index\":%d,\"content\":\"\"}",
                 sessionId, ctx_menu.context_index);
        char *resp = http_post(url, body);
        if (resp) free(resp);
        break;
    }
    case ACT_RATE_UP:
    case ACT_RATE_DOWN: {
        char url[MAX_URL_LEN + 64];
        snprintf(url, sizeof(url), "%s/api/chat/rate", server_url);
        char body[256];
        snprintf(body, sizeof(body), "{\"session_id\":\"%s\",\"message_index\":%d,\"rating\":\"%s\"}",
                 sessionId, ctx_menu.context_index,
                 action == ACT_RATE_UP ? "thumbs_up" : "thumbs_down");
        char *resp = http_post(url, body);
        if (resp) free(resp);
        break;
    }
    default:
        break;
    }
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
            /* If reply looks like weather data, refresh the widget */
            if (strstr(reply, "°F") || strstr(reply, "°C") ||
                strstr(reply, "temperature") || strstr(reply, "weather") ||
                strstr(reply, "forecast") || strstr(reply, "humidity")) {
                weather_refresh_pending = true;
            }
            /* Generate smart reply chips based on response content */
            generate_chips(reply);
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

    /* Session button (left of GPU) */
    draw_rounded_rect(screen_w - 280, 8, 28, 28, 6, COL_CARD);
    draw_text(font_small, "=", screen_w - 272, 12, COL_TEXT); /* Hamburger-ish */

    /* New Chat button */
    draw_rounded_rect(screen_w - 246, 8, 28, 28, 6, COL_ACCENT);
    draw_text(font_small, "+", screen_w - 239, 12, (Color){10, 15, 25, 255});

    time_t now = time(NULL);
    struct tm *t = localtime(&now);
    char timestr[32];
    strftime(timestr, sizeof(timestr), "%H:%M", t);
    draw_text(font_regular, timestr, screen_w - 70, 12, COL_DIM);
}

/* ═══ Smart Reply Chips ═══ */
static void draw_smart_chips(void) {
    if (chip_count == 0 || is_sending) return;
    int kb_h = kb_get_height(&vkb);
    int cy = screen_h - INPUT_H - kb_h - 38;
    int cx = SIDEBAR_W + 16;

    for (int i = 0; i < chip_count && i < MAX_CHIPS; i++) {
        int tw = 0;
        TTF_SizeUTF8(font_small, smart_chips[i], &tw, NULL);
        int cw = tw + 24;
        draw_rounded_rect(cx, cy, cw, 30, 15, (Color){50, 70, 120, 160});
        draw_text(font_small, smart_chips[i], cx + 12, cy + 7, COL_ACCENT);
        cx += cw + 8;
    }
}

/* ═══ Session Drawer ═══ */
#define DRAWER_W 280
static void draw_session_drawer(void) {
    if (!show_session_drawer) return;
    /* Overlay */
    SDL_SetRenderDrawBlendMode(renderer, SDL_BLENDMODE_BLEND);
    fill_rect(0, 0, screen_w, screen_h, (Color){0, 0, 0, 120});

    /* Drawer panel from left */
    fill_rect(0, 0, DRAWER_W, screen_h, COL_SURFACE);
    fill_rect(DRAWER_W - 1, 0, 1, screen_h, COL_BORDER);

    /* Header */
    draw_text(font_large, "Sessions", 16, 14, COL_ACCENT);
    draw_rounded_rect(DRAWER_W - 48, 10, 32, 28, 6, COL_ACCENT);
    draw_text(font_small, "+", DRAWER_W - 38, 14, (Color){10, 15, 25, 255});

    fill_rect(0, 48, DRAWER_W, 1, COL_BORDER);

    /* Session list */
    int y = 56;
    for (int i = 0; i < session_count && y < screen_h - 20; i++) {
        bool active = (strcmp(sessions[i].id, sessionId) == 0);
        Color bg = active ? (Color){50, 65, 90, 200} : (Color){0, 0, 0, 0};
        if (active) fill_rect(0, y, DRAWER_W - 1, 48, bg);

        draw_text(font_regular, sessions[i].title, 16, y + 6, active ? COL_WHITE : COL_TEXT);
        char info[64];
        snprintf(info, sizeof(info), "%d msgs", sessions[i].message_count);
        draw_text(font_small, info, 16, y + 28, COL_DIM);

        fill_rect(16, y + 47, DRAWER_W - 32, 1, COL_BORDER);
        y += 48;
    }
}

/* Procedural sky gradient based on weather condition + time of day */
typedef struct { Uint8 r, g, b; } RGB3;

static void get_sky_colors(const char *cond, RGB3 *top, RGB3 *mid, RGB3 *bot) {
    /* Time of day determines base sky */
    time_t now = time(NULL);
    struct tm *t = localtime(&now);
    int hour = t->tm_hour;
    bool night = (hour < 6 || hour >= 20);
    bool golden = (hour >= 6 && hour < 8) || (hour >= 17 && hour < 20);

    char lower[64] = {0};
    if (cond) { for (int i = 0; i < 63 && cond[i]; i++) lower[i] = (cond[i]>='A'&&cond[i]<='Z') ? cond[i]+32 : cond[i]; }

    if (night) {
        /* Night sky — deep blue/indigo */
        *top = (RGB3){8, 12, 30};
        *mid = (RGB3){12, 18, 45};
        *bot = (RGB3){18, 25, 55};
        if (strstr(lower, "cloud") || strstr(lower, "overcast")) {
            *top = (RGB3){15, 18, 28}; *mid = (RGB3){20, 24, 35}; *bot = (RGB3){25, 30, 40};
        }
    } else if (strstr(lower, "rain") || strstr(lower, "drizzle") || strstr(lower, "shower")) {
        /* Rainy — steel gray with blue tint */
        *top = (RGB3){40, 50, 65}; *mid = (RGB3){55, 65, 80}; *bot = (RGB3){70, 80, 95};
    } else if (strstr(lower, "thunder") || strstr(lower, "storm")) {
        /* Stormy — dark dramatic purple-gray */
        *top = (RGB3){25, 22, 35}; *mid = (RGB3){40, 35, 55}; *bot = (RGB3){55, 50, 70};
    } else if (strstr(lower, "snow") || strstr(lower, "blizzard") || strstr(lower, "flurr")) {
        /* Snowy — bright pale gray-blue */
        *top = (RGB3){140, 155, 175}; *mid = (RGB3){160, 175, 195}; *bot = (RGB3){180, 195, 210};
    } else if (strstr(lower, "fog") || strstr(lower, "mist") || strstr(lower, "haze")) {
        /* Foggy — muted gray */
        *top = (RGB3){80, 85, 95}; *mid = (RGB3){100, 105, 115}; *bot = (RGB3){120, 125, 130};
    } else if (strstr(lower, "overcast") || strstr(lower, "cloud")) {
        /* Cloudy — medium gray with slight blue */
        *top = (RGB3){55, 65, 80}; *mid = (RGB3){75, 85, 100}; *bot = (RGB3){90, 100, 115};
    } else if (golden) {
        /* Golden hour — warm sunset/sunrise */
        *top = (RGB3){50, 80, 140}; *mid = (RGB3){140, 100, 70}; *bot = (RGB3){200, 130, 60};
    } else {
        /* Clear/sunny day — vivid blue gradient */
        *top = (RGB3){30, 80, 180}; *mid = (RGB3){60, 120, 210}; *bot = (RGB3){100, 170, 240};
        if (strstr(lower, "partly")) {
            *top = (RGB3){45, 85, 160}; *mid = (RGB3){80, 115, 180}; *bot = (RGB3){110, 150, 200};
        }
    }
}

static void draw_weather_widget(int x, int y, int w) {
    int h = 130;

    /* Draw procedural sky background */
    RGB3 sky_top, sky_mid, sky_bot;
    get_sky_colors(weather.valid ? weather.condition : NULL, &sky_top, &sky_mid, &sky_bot);

    SDL_SetRenderDrawBlendMode(renderer, SDL_BLENDMODE_BLEND);
    for (int row = 0; row < h; row++) {
        float t = (float)row / (float)h;
        Uint8 r, g, b;
        if (t < 0.5f) {
            float s = t * 2.0f;
            r = (Uint8)(sky_top.r + (sky_mid.r - sky_top.r) * s);
            g = (Uint8)(sky_top.g + (sky_mid.g - sky_top.g) * s);
            b = (Uint8)(sky_top.b + (sky_mid.b - sky_top.b) * s);
        } else {
            float s = (t - 0.5f) * 2.0f;
            r = (Uint8)(sky_mid.r + (sky_bot.r - sky_mid.r) * s);
            g = (Uint8)(sky_mid.g + (sky_bot.g - sky_mid.g) * s);
            b = (Uint8)(sky_mid.b + (sky_bot.b - sky_mid.b) * s);
        }
        SDL_SetRenderDrawColor(renderer, r, g, b, 230);
        SDL_Rect strip = {x, y + row, w, 1};
        SDL_RenderFillRect(renderer, &strip);
    }

    /* Round off corners with dark pixels (approximate rounding) */
    int radius = 8;
    for (int ry = 0; ry < radius; ry++) {
        int rx = radius - (int)sqrtf((float)(radius * radius - (radius - ry) * (radius - ry)));
        fill_rect(x, y + ry, rx, 1, COL_BG);
        fill_rect(x + w - rx, y + ry, rx, 1, COL_BG);
        fill_rect(x, y + h - 1 - ry, rx, 1, COL_BG);
        fill_rect(x + w - rx, y + h - 1 - ry, rx, 1, COL_BG);
    }

    /* Semi-transparent overlay for text readability */
    fill_rect(x, y + h - 30, w, 30, (Color){0, 0, 0, 100});

    /* Content */
    if (weather.valid) {
        /* Temperature — large, white with shadow */
        draw_text(font_huge, weather.temp, x + 13, y + 19, (Color){0, 0, 0, 80}); /* Shadow */
        draw_text(font_huge, weather.temp, x + 12, y + 18, COL_WHITE);

        const char *icon = weather_icon(weather.condition);
        draw_text(font_large, icon, x + w - 70, y + 20, COL_WHITE);

        draw_text(font_small, weather.condition, x + 12, y + 68, (Color){240, 245, 255, 220});
        draw_text(font_small, weather.location, x + 12, y + 84, (Color){180, 210, 255, 255});

        char detail[128];
        snprintf(detail, sizeof(detail), "Humidity: %s   Wind: %s   Feels: %s",
                 weather.humidity, weather.wind, weather.feels_like);
        draw_text(font_small, detail, x + 8, y + 112, (Color){200, 215, 235, 200});
    } else {
        const char *msg = weather_fetching ? "Loading weather..." : "Tap to refresh";
        draw_text(font_regular, msg, x + 12, y + 50, (Color){200, 210, 230, 180});
    }
}

#define METRICS_H 200

static void draw_metric_row(int x, int y, int w, const char *label, const char *value, Color val_color) {
    draw_text(font_small, label, x, y, COL_DIM);
    /* Right-align value */
    int vw = 0;
    TTF_SizeUTF8(font_small, value, &vw, NULL);
    draw_text(font_small, value, x + w - vw, y, val_color);
}

static void draw_metrics_widget(int x, int y, int w) {
    draw_rounded_rect(x, y, w, METRICS_H, 8, COL_CARD);
    fill_rect(x, y, w, 2, COL_GREEN);
    draw_text(font_small, "LIVE METRICS", x + 12, y + 8, COL_DIM);

    int mx = x + 12;
    int mw = w - 24;
    int row = y + 26;
    int rh = 18; /* row height */
    char buf[64];

    snprintf(buf, sizeof(buf), "%d", metrics.tasks_completed);
    draw_metric_row(mx, row, mw, "Tasks Completed", buf, COL_TEXT);
    row += rh;

    snprintf(buf, sizeof(buf), "%d", metrics.llm_calls);
    draw_metric_row(mx, row, mw, "LLM Calls", buf, COL_TEXT);
    row += rh;

    snprintf(buf, sizeof(buf), "%d", metrics.session_messages);
    draw_metric_row(mx, row, mw, "Session Messages", buf, COL_TEXT);
    row += rh;

    snprintf(buf, sizeof(buf), "%d", metrics.commands_run);
    draw_metric_row(mx, row, mw, "Commands Run", buf, COL_TEXT);
    row += rh;

    snprintf(buf, sizeof(buf), "%d", metrics.tokens_in);
    draw_metric_row(mx, row, mw, "Tokens In", buf, COL_ACCENT);
    row += rh;

    snprintf(buf, sizeof(buf), "%d", metrics.tokens_out);
    draw_metric_row(mx, row, mw, "Tokens Out", buf, COL_ACCENT);
    row += rh;

    /* GPU temp */
    const char *gpu = (metrics.gpu_temp[0] && strcmp(metrics.gpu_temp, "--") != 0)
                      ? metrics.gpu_temp : "N/A";
    Color gpu_c = COL_TEXT;
    if (strstr(gpu, "N/A") == NULL) gpu_c = COL_YELLOW;
    draw_metric_row(mx, row, mw, "GPU", gpu, gpu_c);
    row += rh;

    /* GPU Workers */
    snprintf(buf, sizeof(buf), "%d", metrics.gpu_workers);
    draw_metric_row(mx, row, mw, "GPU Workers", buf, COL_TEXT);
    row += rh;

    /* Context usage bar */
    draw_text(font_small, "Context", mx, row, COL_DIM);
    int bar_x = mx + 60;
    int bar_w = mw - 80;
    int bar_h = 10;
    fill_rect(bar_x, row + 2, bar_w, bar_h, COL_BORDER);
    int fill_w = (int)(bar_w * metrics.context_pct / 100.0f);
    Color bar_c = metrics.context_pct > 80 ? COL_RED : (metrics.context_pct > 50 ? COL_YELLOW : COL_GREEN);
    fill_rect(bar_x, row + 2, fill_w, bar_h, bar_c);
    snprintf(buf, sizeof(buf), "%d%%", metrics.context_pct);
    draw_text(font_small, buf, bar_x + bar_w + 4, row, COL_DIM);
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
    draw_rounded_rect(x, y, w, 110, 8, COL_CARD);
    fill_rect(x, y, w, 2, COL_YELLOW);
    draw_text(font_small, "SERVER", x + 12, y + 8, COL_DIM);

    int mx = x + 12, mw = w - 24, row = y + 26, rh = 16;

    draw_metric_row(mx, row, mw, "Ollama",
        metrics.ollama_online ? "Online" : "Offline",
        metrics.ollama_online ? COL_GREEN : COL_RED);
    row += rh;

    draw_metric_row(mx, row, mw, "BitNet",
        metrics.bitnet_enabled ? "Enabled" : "Off",
        metrics.bitnet_enabled ? COL_GREEN : COL_DIM);
    row += rh;

    /* Active model */
    const char *model = metrics.active_model[0] ? metrics.active_model : "--";
    draw_metric_row(mx, row, mw, "Model", model, COL_ACCENT);
    row += rh;

    /* Current status */
    const char *st = metrics.status[0] ? metrics.status : "Idle";
    Color st_c = COL_DIM;
    if (strcmp(st, "Idle") != 0 && strcmp(st, "Finished") != 0) st_c = COL_GREEN;
    draw_metric_row(mx, row, mw, "Status", st, st_c);
    row += rh;

    /* Version */
    const char *ver = metrics.version[0] ? metrics.version : "--";
    draw_metric_row(mx, row, mw, "Version", ver, COL_DIM);
}

/* Clipped text — renders text but clips to max pixel width */
static void draw_text_clipped(TTF_Font *f, const char *text, int x, int y, int max_w, Color c) {
    if (!text || !text[0] || max_w <= 0) return;
    /* Measure full text */
    int tw = 0;
    TTF_SizeUTF8(f, text, &tw, NULL);
    if (tw <= max_w) {
        draw_text(f, text, x, y, c);
        return;
    }
    /* Truncate: binary search for how many chars fit */
    char buf[512];
    int len = (int)strlen(text);
    if (len > (int)sizeof(buf) - 4) len = (int)sizeof(buf) - 4;
    int lo = 1, hi = len;
    while (lo < hi) {
        int mid = (lo + hi + 1) / 2;
        snprintf(buf, sizeof(buf), "%.*s...", mid, text);
        TTF_SizeUTF8(f, buf, &tw, NULL);
        if (tw <= max_w) lo = mid; else hi = mid - 1;
    }
    snprintf(buf, sizeof(buf), "%.*s...", lo, text);
    draw_text(f, buf, x, y, c);
}

static void draw_news_panel(int x, int y, int w) {
    /* Set clip rect to prevent bleeding */
    SDL_Rect clip = {0, TOPBAR_H + TAB_BAR_H, SIDEBAR_W, screen_h - TOPBAR_H - TAB_BAR_H};
    SDL_RenderSetClipRect(renderer, &clip);

    int max_text_w = w - 16;

    /* Category tabs */
    const char *cats[] = {"Top", "Local", "National", "Global", NULL};
    const char *cat_ids[] = {"top", "local", "national", "global"};
    int cx = x;
    for (int i = 0; cats[i]; i++) {
        bool active = (strcmp(news_category, cat_ids[i]) == 0);
        Color bg = active ? COL_ACCENT : COL_CARD;
        Color fg = active ? (Color){10,15,25,255} : COL_DIM;
        int tw = 0; TTF_SizeUTF8(font_small, cats[i], &tw, NULL);
        int chip_w = tw + 14;
        draw_rounded_rect(cx, y, chip_w, 22, 8, bg);
        draw_text(font_small, cats[i], cx + 7, y + 4, fg);
        cx += chip_w + 4;
    }
    y += 28;

    /* Articles */
    int thumb_sz = 36;
    for (int i = 0; i < news_count && y < screen_h - 20; i++) {
        draw_rounded_rect(x, y, w, 52, 6, COL_CARD);
        int text_x = x + 8;
        int text_w = max_text_w;

        /* Thumbnail (favicon) */
        if (news_articles[i].thumb_tex) {
            SDL_Rect dst = {x + w - thumb_sz - 6, y + 8, thumb_sz, thumb_sz};
            SDL_RenderCopy(renderer, news_articles[i].thumb_tex, NULL, &dst);
            text_w -= thumb_sz + 8;
        }

        /* Source badge */
        if (news_articles[i].source[0]) {
            draw_text_clipped(font_small, news_articles[i].source, text_x, y + 4, text_w, COL_ACCENT);
        }
        /* Title */
        draw_text_clipped(font_small, news_articles[i].title, text_x, y + 18, text_w, COL_TEXT);
        /* Snippet */
        draw_text_clipped(font_small, news_articles[i].body, text_x, y + 34, text_w, COL_DIM);
        y += 58;
    }
    if (news_count == 0) {
        const char *msg = news_fetching ? "Loading news..." : "No articles";
        draw_text(font_regular, msg, x + 8, y, COL_DIM);
    }
    SDL_RenderSetClipRect(renderer, NULL);
}

static void draw_markets_panel(int x, int y, int w) {
    SDL_Rect clip = {0, TOPBAR_H + TAB_BAR_H, SIDEBAR_W, screen_h - TOPBAR_H - TAB_BAR_H};
    SDL_RenderSetClipRect(renderer, &clip);

    int max_text_w = w - 24;
    draw_rounded_rect(x, y, w, 100, 8, COL_CARD);
    fill_rect(x, y, w, 2, COL_GREEN);
    draw_text(font_small, "MARKETS", x + 12, y + 8, COL_DIM);

    if (market_summary[0]) {
        /* Split summary by semicolons and display each */
        char buf[1024];
        snprintf(buf, sizeof(buf), "%s", market_summary);
        int ly = y + 28;
        char *saveptr = NULL;
        char *line = strtok_r(buf, ";", &saveptr);
        while (line && ly < y + 92) {
            while (*line == ' ') line++;
            draw_text_clipped(font_small, line, x + 12, ly, max_text_w, COL_TEXT);
            ly += 16;
            line = strtok_r(NULL, ";", &saveptr);
        }
    } else {
        const char *msg = markets_fetching ? "Loading markets..." : "No data";
        draw_text(font_regular, msg, x + 12, y + 35, COL_DIM);
    }
    SDL_RenderSetClipRect(renderer, NULL);
}

static void draw_settings_panel(int x, int y, int w) {
    draw_text(font_large, "Settings", x + 8, y, COL_ACCENT);
    y += 32;

    int rh = 20;
    draw_metric_row(x + 8, y, w - 16, "Server", server_url, COL_TEXT); y += rh;
    draw_metric_row(x + 8, y, w - 16, "Session", sessionId, COL_TEXT); y += rh;
    draw_metric_row(x + 8, y, w - 16, "User", login_state.auth_username[0] ? login_state.auth_username : "guest", COL_TEXT); y += rh;
    draw_metric_row(x + 8, y, w - 16, "Version", metrics.version[0] ? metrics.version : "--", COL_TEXT); y += rh;
    y += 8;
    draw_metric_row(x + 8, y, w - 16, "Ollama", metrics.ollama_online ? "Online" : "Offline",
                    metrics.ollama_online ? COL_GREEN : COL_RED); y += rh;
    draw_metric_row(x + 8, y, w - 16, "BitNet", metrics.bitnet_enabled ? "Enabled" : "Off",
                    metrics.bitnet_enabled ? COL_GREEN : COL_DIM); y += rh;
    draw_metric_row(x + 8, y, w - 16, "Model", metrics.active_model[0] ? metrics.active_model : "--", COL_ACCENT); y += rh;
    draw_metric_row(x + 8, y, w - 16, "GPU Workers", metrics.gpu_workers > 0 ? "Connected" : "0",
                    metrics.gpu_workers > 0 ? COL_GREEN : COL_DIM); y += rh;
    draw_metric_row(x + 8, y, w - 16, "Location", detected_city[0] ? detected_city : "Unknown", COL_TEXT); y += rh;
    y += 8;

    char tok_in[32], tok_out[32];
    snprintf(tok_in, sizeof(tok_in), "%d", metrics.tokens_in);
    snprintf(tok_out, sizeof(tok_out), "%d", metrics.tokens_out);
    draw_metric_row(x + 8, y, w - 16, "Tokens In", tok_in, COL_ACCENT); y += rh;
    draw_metric_row(x + 8, y, w - 16, "Tokens Out", tok_out, COL_ACCENT); y += rh;
    char tasks[16]; snprintf(tasks, sizeof(tasks), "%d", metrics.tasks_completed);
    draw_metric_row(x + 8, y, w - 16, "Tasks Done", tasks, COL_TEXT); y += rh;
    char llm[16]; snprintf(llm, sizeof(llm), "%d", metrics.llm_calls);
    draw_metric_row(x + 8, y, w - 16, "LLM Calls", llm, COL_TEXT); y += rh;
}

static void draw_sidebar(void) {
    fill_rect(0, TOPBAR_H, SIDEBAR_W, screen_h - TOPBAR_H, COL_SURFACE);
    fill_rect(SIDEBAR_W - 1, TOPBAR_H, 1, screen_h - TOPBAR_H, COL_BORDER);

    /* Tab bar at top of sidebar */
    int tab_y = TOPBAR_H;
    const char *tabs[] = {"Home", "News", "Mkt", "Set"};
    SidebarTab tab_ids[] = {TAB_HOME, TAB_NEWS, TAB_MARKETS, TAB_SETTINGS};
    int tab_w = SIDEBAR_W / 4;
    for (int i = 0; i < 4; i++) {
        bool active = (sidebar_tab == tab_ids[i]);
        Color bg = active ? (Color){40, 55, 80, 220} : (Color){0,0,0,0};
        fill_rect(i * tab_w, tab_y, tab_w, TAB_BAR_H, bg);
        Color fg = active ? COL_ACCENT : COL_DIM;
        /* Center text */
        int tw = 0; TTF_SizeUTF8(font_small, tabs[i], &tw, NULL);
        draw_text(font_small, tabs[i], i * tab_w + (tab_w - tw) / 2, tab_y + 10, fg);
        if (active) fill_rect(i * tab_w, tab_y + TAB_BAR_H - 2, tab_w, 2, COL_ACCENT);
    }
    fill_rect(0, tab_y + TAB_BAR_H, SIDEBAR_W, 1, COL_BORDER);

    int x = 8, y = TOPBAR_H + TAB_BAR_H + 8, w = SIDEBAR_W - 16;

    switch (sidebar_tab) {
    case TAB_HOME:
        draw_weather_widget(x, y, w);
        y += 138;
        draw_metrics_widget(x, y, w);
        y += METRICS_H + 8;
        draw_actions_widget(x, y, w);
        y += 168;
        if (y + 110 < screen_h) draw_status_widget(x, y, w);
        break;
    case TAB_NEWS:
        draw_news_panel(x, y, w);
        break;
    case TAB_MARKETS:
        draw_markets_panel(x, y, w);
        break;
    case TAB_SETTINGS:
        draw_settings_panel(x, y, w);
        break;
    }
}

/* Chat bubble colors — vivid, warm, fit the animated bg */
static const Color COL_USER_BUBBLE  = {70, 120, 200, 230};  /* Rich blue glass */
static const Color COL_USER_GLOW    = {90, 140, 220, 40};   /* Soft glow behind user bubble */
static const Color COL_ASST_BUBBLE  = {25, 32, 50, 210};    /* Deep frosted glass */
static const Color COL_ASST_GLOW    = {60, 80, 140, 30};    /* Subtle purple glow */
static const Color COL_ASST_ACCENT  = {100, 140, 220, 60};  /* Left accent bar */

static void draw_chat(void) {
    int cx = SIDEBAR_W;
    int cy = TOPBAR_H;
    int cw = screen_w - SIDEBAR_W;
    int ch = screen_h - TOPBAR_H - INPUT_H;
    int kb_h = kb_get_height(&vkb);
    if (kb_h > 0) ch -= kb_h;

    /* Chat area — very subtle overlay so bg shows through */
    fill_rect(cx, cy, cw, ch, (Color){6, 8, 16, 60});

    /* Clip region (don't draw outside chat area) */
    SDL_Rect clip = {cx, cy, cw, ch};
    SDL_RenderSetClipRect(renderer, &clip);

    /* Messages — bigger font, more padding, more color */
    int y = cy + 16 - scroll_offset;
    int padding = 16;
    int bubble_radius = 14;

    for (int i = 0; i < msg_count; i++) {
        bool is_user = messages[i].is_user;
        Color bubble_bg = is_user ? COL_USER_BUBBLE : COL_ASST_BUBBLE;
        Color glow = is_user ? COL_USER_GLOW : COL_ASST_GLOW;
        Color fg = is_user ? (Color){240, 245, 255, 255} : COL_TEXT;
        int max_w = cw - 100;

        /* Render text with the regular font (bigger than before) */
        SDL_Color sc = {fg.r, fg.g, fg.b, fg.a};
        SDL_Surface *surf = TTF_RenderUTF8_Blended_Wrapped(font_regular, messages[i].text, sc, max_w - padding * 2);
        if (!surf) continue;
        int tw = surf->w;
        int th = surf->h;

        int bw = tw + padding * 2 + 4;
        int bh = th + padding * 2;
        int bx = is_user ? cx + cw - bw - 20 : cx + 20;
        int by = y;

        /* Glow behind bubble (soft shadow/ambient light) */
        SDL_SetRenderDrawBlendMode(renderer, SDL_BLENDMODE_BLEND);
        draw_rounded_rect(bx - 3, by - 3, bw + 6, bh + 6, bubble_radius + 3, glow);

        /* Bubble background */
        draw_rounded_rect(bx, by, bw, bh, bubble_radius, bubble_bg);

        /* Assistant accent bar on left edge */
        if (!is_user) {
            fill_rect(bx, by + 6, 3, bh - 12, COL_ASST_ACCENT);
        }

        /* Text */
        SDL_Texture *tex = SDL_CreateTextureFromSurface(renderer, surf);
        SDL_Rect dst = {bx + padding + (is_user ? 0 : 4), by + padding, tw, th};
        SDL_SetRenderDrawBlendMode(renderer, SDL_BLENDMODE_BLEND);
        SDL_RenderCopy(renderer, tex, NULL, &dst);
        SDL_DestroyTexture(tex);
        SDL_FreeSurface(surf);

        y += bh + 14;
    }

    /* Thinking/Reasoning dialogue panel */
    if (is_sending || show_thinking) {
        int panel_x = cx + 16;
        int panel_w = cw - 32;
        int panel_max_h = 160;

        /* Background panel */
        draw_rounded_rect(panel_x, y, panel_w, panel_max_h, 12,
                          (Color){15, 20, 35, 210});
        /* Accent bar */
        fill_rect(panel_x, y, panel_w, 2, (Color){100, 140, 220, 180});

        /* Header with pulsing dot */
        float pulse = 0.5f + 0.5f * sinf((float)SDL_GetTicks() * 0.005f);
        Uint8 dot_alpha = (Uint8)(120 + pulse * 135);
        fill_rect(panel_x + 12, y + 12, 8, 8, (Color){100, 200, 140, dot_alpha});
        draw_text(font_small, "Thinking...", panel_x + 28, y + 10, COL_ACCENT);

        /* Status line */
        if (metrics.status[0] && strcmp(metrics.status, "Idle") != 0) {
            draw_text(font_small, metrics.status, panel_x + 110, y + 10, COL_DIM);
        }
        if (metrics.active_model[0]) {
            char model_str[128];
            snprintf(model_str, sizeof(model_str), "Model: %s", metrics.active_model);
            int mw_text = 0;
            TTF_SizeUTF8(font_small, model_str, &mw_text, NULL);
            draw_text(font_small, model_str, panel_x + panel_w - mw_text - 12, y + 10, COL_DIM);
        }

        /* Thinking log entries — show last N that fit */
        int log_y = y + 30;
        int log_h = panel_max_h - 38;
        int line_h = 16;
        int max_lines = log_h / line_h;
        int start = thinking_count > max_lines ? thinking_count - max_lines : 0;

        for (int i = start; i < thinking_count; i++) {
            /* Color-code entries */
            Color entry_c = COL_DIM;
            const char *entry = thinking_log[i];
            if (strstr(entry, "BitNet")) entry_c = (Color){100, 160, 255, 255};  /* Blue */
            else if (strstr(entry, "NPU")) entry_c = (Color){180, 130, 255, 255}; /* Purple */
            else if (strstr(entry, "error") || strstr(entry, "Error")) entry_c = COL_RED;
            else if (strstr(entry, "review") || strstr(entry, "Review")) entry_c = (Color){240, 180, 80, 255}; /* Orange */
            else if (strstr(entry, "SUCCESS") || strstr(entry, "complete")) entry_c = COL_GREEN;
            else if (strstr(entry, "tool:")) entry_c = (Color){140, 180, 220, 255}; /* Light blue */

            /* Truncate long entries */
            char display[128];
            snprintf(display, sizeof(display), "%.120s", entry);
            draw_text(font_small, display, panel_x + 12, log_y, entry_c);
            log_y += line_h;
        }

        /* If no log entries yet, show waiting animation */
        if (thinking_count == 0 && is_sending) {
            int dots = ((SDL_GetTicks() / 400) % 4);
            char wait[16] = "Waiting";
            for (int d = 0; d < dots; d++) strcat(wait, ".");
            draw_text(font_small, wait, panel_x + 12, log_y, COL_DIM);
        }

        y += panel_max_h + 8;
    }

    SDL_RenderSetClipRect(renderer, NULL); /* Remove clip */
}

static void draw_input_bar(void) {
    int kb_h = kb_get_height(&vkb);
    int iy = screen_h - INPUT_H - kb_h;
    /* Frosted glass bar */
    fill_rect(SIDEBAR_W, iy, screen_w - SIDEBAR_W, INPUT_H, (Color){12, 16, 26, 200});
    fill_rect(SIDEBAR_W, iy, screen_w - SIDEBAR_W, 1, (Color){60, 80, 120, 40});

    /* Input field — larger, glassy */
    int fx = SIDEBAR_W + 16;
    int fy = iy + 8;
    int fw = screen_w - SIDEBAR_W - 88;
    int fh = INPUT_H - 16;

    /* Glow when active */
    if (input_active) {
        draw_rounded_rect(fx - 2, fy - 2, fw + 4, fh + 4, 22, (Color){80, 130, 220, 30});
    }
    draw_rounded_rect(fx, fy, fw, fh, 20, (Color){20, 28, 44, 220});

    if (input_text[0]) {
        draw_text(font_regular, input_text, fx + 18, fy + 10, COL_TEXT);
    } else {
        draw_text(font_regular, "Ask OmniAgent...", fx + 18, fy + 10, (Color){80, 100, 130, 180});
    }

    /* Cursor blink when active */
    if (input_active && (SDL_GetTicks() / 500) % 2 == 0) {
        int tw = 0;
        if (input_text[0]) TTF_SizeUTF8(font_regular, input_text, &tw, NULL);
        fill_rect(fx + 18 + tw, fy + 8, 2, fh - 16, COL_ACCENT);
    }

    /* Send button — circular, glowing when ready */
    int bx = screen_w - 60;
    int by = iy + 8;
    bool ready = input_text[0] && !is_sending;
    if (ready) {
        draw_rounded_rect(bx - 2, by - 2, 52, 44, 24, (Color){80, 140, 230, 40});
    }
    Color btn_c = ready ? COL_ACCENT : (Color){30, 40, 60, 180};
    draw_rounded_rect(bx, by, 48, 40, 20, btn_c);
    Color arrow_c = ready ? (Color){10, 15, 25, 255} : COL_DIM;
    draw_text(font_large, ">", bx + 14, by + 6, arrow_c);
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
                    queue_hub_refresh(true, true, true);
                }
            }
            return;
        }
        return;
    }

    /* Topbar buttons */
    if (y < TOPBAR_H) {
        /* Session drawer button */
        if (x >= screen_w - 280 && x <= screen_w - 252) {
            show_session_drawer = !show_session_drawer;
            if (show_session_drawer) fetch_sessions();
            return;
        }
        /* New chat button */
        if (x >= screen_w - 246 && x <= screen_w - 218) {
            new_chat();
            return;
        }
        return;
    }

    /* Smart reply chip taps */
    if (chip_count > 0 && !is_sending) {
        int kb_h = kb_get_height(&vkb);
        int cy = screen_h - INPUT_H - kb_h - 38;
        int cx = SIDEBAR_W + 16;
        for (int i = 0; i < chip_count && i < MAX_CHIPS; i++) {
            int tw = 0;
            TTF_SizeUTF8(font_small, smart_chips[i], &tw, NULL);
            int cw = tw + 24;
            if (x >= cx && x <= cx + cw && y >= cy && y <= cy + 30) {
                snprintf(input_text, sizeof(input_text), "%s", smart_chips[i]);
                input_cursor = (int)strlen(input_text);
                chip_count = 0;
                send_message();
                return;
            }
            cx += cw + 8;
        }
    }

    /* Long-press on chat bubbles → context menu */
    if (x > SIDEBAR_W && y > TOPBAR_H && y < screen_h - INPUT_H) {
        Uint32 held = SDL_GetTicks() - touch_down_time;
        if (held > LONG_PRESS_MS && touch_down_time > 0 && !long_press_fired) {
            /* Find which message bubble was long-pressed */
            int by_scan = TOPBAR_H + 16 - scroll_offset;
            for (int i = 0; i < msg_count; i++) {
                /* Rough height estimate per message */
                int est_h = 60 + (int)(strlen(messages[i].text) / 60) * 18;
                if (y >= by_scan && y < by_scan + est_h) {
                    if (messages[i].is_user) {
                        show_user_msg_menu(i, x, y);
                    } else {
                        show_asst_msg_menu(i, x, y);
                    }
                    long_press_fired = true;
                    return;
                }
                by_scan += est_h + 14;
            }
        }
    }

    /* Sidebar touches */
    if (x < SIDEBAR_W) {
        /* Tab bar */
        if (y >= TOPBAR_H && y < TOPBAR_H + TAB_BAR_H) {
            int tab_w = SIDEBAR_W / 4;
            int tab_idx = x / tab_w;
            SidebarTab tabs[] = {TAB_HOME, TAB_NEWS, TAB_MARKETS, TAB_SETTINGS};
            if (tab_idx >= 0 && tab_idx < 4) {
                sidebar_tab = tabs[tab_idx];
                /* Trigger data fetch for the tab */
                if (sidebar_tab == TAB_NEWS && news_count == 0) news_refresh_pending = true;
                if (sidebar_tab == TAB_MARKETS && !market_summary[0]) markets_refresh_pending = true;
            }
            return;
        }

        /* News tab — category taps */
        if (sidebar_tab == TAB_NEWS && y >= TOPBAR_H + TAB_BAR_H + 8 && y < TOPBAR_H + TAB_BAR_H + 32) {
            const char *cat_ids[] = {"top", "local", "national", "global"};
            int cx_check = 8;
            const char *cats[] = {"Top", "Local", "National", "Global"};
            for (int i = 0; i < 4; i++) {
                int tw = 0; TTF_SizeUTF8(font_small, cats[i], &tw, NULL);
                if (x >= cx_check && x <= cx_check + tw + 16) {
                    snprintf(news_category, sizeof(news_category), "%s", cat_ids[i]);
                    news_refresh_pending = true;
                    return;
                }
                cx_check += tw + 22;
            }
            return;
        }

        if (sidebar_tab != TAB_HOME) return; /* Only Home tab has widgets below */

        /* Weather widget tap — refresh now */
        int wy = TOPBAR_H + TAB_BAR_H + 8;
        if (y >= wy && y <= wy + 130) {
            weather_refresh_pending = true;
            return;
        }

        /* Quick action buttons */
        int ax = 8, ay = TOPBAR_H + TAB_BAR_H + 8 + 138 + METRICS_H + 8 + 28;
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
    if (IMG_Init(IMG_INIT_PNG | IMG_INIT_JPG) == 0) {
        fprintf(stderr, "IMG_Init warning: %s\n", IMG_GetError());
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

    /* Load fonts — prefer bundled Nunito (rounded, modern), fallback to system */
    /* Resolve path relative to executable */
    char font_dir[512];
    {
        /* Try relative to binary location */
        const char *base = SDL_GetBasePath();
        if (base) {
            snprintf(font_dir, sizeof(font_dir), "%s../fonts/Nunito.ttf", base);
            SDL_free((void*)base);
        } else {
            font_dir[0] = '\0';
        }
    }

    const char *font_paths[] = {
        font_dir,  /* bundled Nunito (relative to binary) */
        "fonts/Nunito.ttf",  /* CWD-relative */
        "../fonts/Nunito.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  /* bold fallback */
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        NULL
    };
    const char *font_path = NULL;
    for (int i = 0; font_paths[i] && font_paths[i][0]; i++) {
        TTF_Font *test = TTF_OpenFont(font_paths[i], 14);
        if (test) {
            TTF_CloseFont(test);
            font_path = font_paths[i];
            printf("[Hub] Font: %s\n", font_path);
            break;
        }
    }
    if (!font_path) font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf";

    font_small   = TTF_OpenFont(font_path, 13);
    font_regular = TTF_OpenFont(font_path, 17);
    font_large   = TTF_OpenFont(font_path, 24);
    font_huge    = TTF_OpenFont(font_path, 40);

    if (!font_regular) {
        fprintf(stderr, "Failed to load font from %s: %s\n", font_path, TTF_GetError());
        fprintf(stderr, "Install: sudo apt install fonts-dejavu-core\n");
        fprintf(stderr, "Or place Nunito.ttf in smarthub/fonts/\n");
        return 1;
    }

    /* Initialize subsystems */
    kb_init(&vkb);
    login_init(&login_state);
    bg_init(&anim_bg);

    /* Initial fetch if URL provided */
    if (server_url[0]) {
        fetch_metrics();
        if (metrics.connected) {
            snprintf(login_state.server_display, sizeof(login_state.server_display),
                     "Connected to %s", server_url);
            queue_hub_refresh(true, true, true);
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

            /* Escape key: dismiss menus/drawers/keyboard, or quit */
            if (event.type == SDL_KEYDOWN && event.key.keysym.sym == SDLK_ESCAPE) {
                if (ctx_menu.visible) { menu_hide(&ctx_menu); }
                else if (show_session_drawer) { show_session_drawer = false; }
                else if (vkb.visible) { kb_hide(&vkb); }
                else if (input_active) { input_active = false; }
                else { running = false; }
                continue;
            }

            /* Context menu consumes events when visible */
            if (ctx_menu.visible) {
                int action = menu_handle_event(&ctx_menu, &event, screen_w, screen_h);
                if (action >= 0) handle_menu_action(action);
                continue;
            }

            /* Track long-press for context menus */
            if (event.type == SDL_MOUSEBUTTONDOWN || event.type == SDL_FINGERDOWN) {
                if (event.type == SDL_FINGERDOWN) {
                    touch_down_x = (int)(event.tfinger.x * screen_w);
                    touch_down_y = (int)(event.tfinger.y * screen_h);
                } else {
                    touch_down_x = event.button.x;
                    touch_down_y = event.button.y;
                }
                touch_down_time = SDL_GetTicks();
                long_press_fired = false;
            }
            if (event.type == SDL_MOUSEBUTTONUP || event.type == SDL_FINGERUP) {
                touch_down_time = 0;
            }

            /* Session drawer touches */
            if (show_session_drawer) {
                int tx = -1, ty = -1;
                if (event.type == SDL_MOUSEBUTTONDOWN) { tx = event.button.x; ty = event.button.y; }
                else if (event.type == SDL_FINGERDOWN) { tx = (int)(event.tfinger.x * screen_w); ty = (int)(event.tfinger.y * screen_h); }
                if (tx >= 0) {
                    if (tx > DRAWER_W) {
                        show_session_drawer = false;
                    } else {
                        /* New chat button in drawer */
                        if (tx >= DRAWER_W - 48 && tx <= DRAWER_W - 16 && ty >= 10 && ty <= 38) {
                            new_chat();
                            show_session_drawer = false;
                        }
                        /* Session item tap/long-press */
                        int sy = 56;
                        for (int i = 0; i < session_count; i++) {
                            if (ty >= sy && ty < sy + 48) {
                                Uint32 held = SDL_GetTicks() - touch_down_time;
                                if (held > LONG_PRESS_MS && !long_press_fired) {
                                    show_session_menu(i, tx, ty);
                                    long_press_fired = true;
                                } else {
                                    switch_session(sessions[i].id);
                                    show_session_drawer = false;
                                }
                                break;
                            }
                            sy += 48;
                        }
                    }
                }
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
            /* Fetch on startup and then every 5 minutes without blocking the UI. */
            if ((weather_refresh_pending || last_weather_time == 0 || now - last_weather_time > WEATHER_INTERVAL_MS)
                && fetch_weather()) {
                last_weather_time = now;
                weather_refresh_pending = false;
            }
            if ((news_refresh_pending || last_news_time == 0 || now - last_news_time > NEWS_INTERVAL_MS)
                && fetch_news()) {
                last_news_time = now;
                news_refresh_pending = false;
            }
            if ((markets_refresh_pending || last_market_time == 0 || now - last_market_time > MARKET_INTERVAL_MS)
                && fetch_markets()) {
                last_market_time = now;
                markets_refresh_pending = false;
            }
        }

        /* Load pending thumbnails (one per frame, non-blocking feel) */
        if (sidebar_tab == TAB_NEWS && !news_fetching) {
            load_pending_thumbnails();
        }

        /* Update animated background */
        float dt = 1.0f / FPS;
        bg_update(&anim_bg, dt);

        /* Render */
        SDL_SetRenderDrawColor(renderer, 0, 0, 0, 255);
        SDL_RenderClear(renderer);

        /* Animated background — always drawn first, all screens get it */
        SDL_SetRenderDrawBlendMode(renderer, SDL_BLENDMODE_BLEND);
        bg_render(&anim_bg, renderer, screen_w, screen_h);

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
            draw_smart_chips();
            draw_input_bar();
            kb_render(&vkb, renderer, font_regular, font_small, screen_w, screen_h);
            draw_session_drawer();
            menu_render(&ctx_menu, renderer, font_regular, font_small);
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
    /* Free thumbnail textures */
    for (int i = 0; i < MAX_NEWS; i++) {
        if (news_articles[i].thumb_tex) SDL_DestroyTexture(news_articles[i].thumb_tex);
    }
    TTF_Quit();
    IMG_Quit();
    curl_global_cleanup();
    SDL_Quit();
    return 0;
}
