/*
 * OmniAgent Smart Hub — Login Screen
 */
#ifndef LOGIN_H
#define LOGIN_H

#include <SDL2/SDL.h>
#include <SDL2/SDL_ttf.h>
#include <stdbool.h>
#include "keyboard.h"

typedef enum {
    LOGIN_FIELD_USERNAME,
    LOGIN_FIELD_PASSWORD,
    LOGIN_FIELD_NONE,
} LoginField;

typedef struct {
    bool active;             /* Is login screen showing */
    char username[128];
    char password[128];
    int user_cursor;
    int pass_cursor;
    LoginField focused_field;
    char error_msg[256];
    char server_display[256]; /* "Connected to 192.168.254.2:8000" */
    bool authenticating;
    bool authenticated;
    char auth_token[256];    /* Session token from server */
    char auth_username[128]; /* Confirmed username */
} LoginState;

/* Initialize login state */
void login_init(LoginState *login);

/* Handle touch events — returns true if consumed */
bool login_handle_event(LoginState *login, Keyboard *kb, SDL_Event *event,
                        int screen_w, int screen_h);

/* Attempt login via HTTP API */
void login_attempt(LoginState *login, const char *server_url);

/* Render login screen */
void login_render(LoginState *login, SDL_Renderer *ren,
                  TTF_Font *font, TTF_Font *font_small, TTF_Font *font_large,
                  int screen_w, int screen_h);

#endif /* LOGIN_H */
