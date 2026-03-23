"""
OAuth2 integration for GitHub, Google (Drive, Gmail, Keep/Tasks).

One-time setup:
  1. GitHub: https://github.com/settings/developers → New OAuth App
     - Callback URL: http://localhost:8000/api/oauth/callback/github
     - Set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET env vars

  2. Google: https://console.cloud.google.com/apis/credentials → Create OAuth Client
     - Type: Web application
     - Redirect URI: http://localhost:8000/api/oauth/callback/google
     - Enable APIs: Drive, Gmail, Tasks
     - Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET env vars

Tokens are encrypted and stored per-user in the database.
"""
import os
import json
import urllib.request
import urllib.parse
import urllib.error
import logging

log = logging.getLogger("oauth")

# ── OAuth Configuration ──────────────────────────────────────
# Set these via environment variables or .env file

GITHUB_CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET", "")

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")


def _load_from_db():
    """Load OAuth credentials from DB if not set via env vars."""
    global GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
    try:
        from src.persistence import get_global_state, decrypt
        if not GITHUB_CLIENT_ID:
            GITHUB_CLIENT_ID = decrypt(get_global_state("oauth_github_client_id", ""))
        if not GITHUB_CLIENT_SECRET:
            GITHUB_CLIENT_SECRET = decrypt(get_global_state("oauth_github_client_secret", ""))
        if not GOOGLE_CLIENT_ID:
            GOOGLE_CLIENT_ID = decrypt(get_global_state("oauth_google_client_id", ""))
        if not GOOGLE_CLIENT_SECRET:
            GOOGLE_CLIENT_SECRET = decrypt(get_global_state("oauth_google_client_secret", ""))
    except Exception:
        pass

# Auto-load on import
_load_from_db()


def save_oauth_config(service: str, client_id: str, client_secret: str):
    """Save OAuth credentials to DB (encrypted) and update in-memory config."""
    global GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
    from src.persistence import save_global_state, encrypt
    if service == "github":
        GITHUB_CLIENT_ID = client_id
        GITHUB_CLIENT_SECRET = client_secret
        save_global_state("oauth_github_client_id", encrypt(client_id))
        save_global_state("oauth_github_client_secret", encrypt(client_secret))
    elif service == "google":
        GOOGLE_CLIENT_ID = client_id
        GOOGLE_CLIENT_SECRET = client_secret
        save_global_state("oauth_google_client_id", encrypt(client_id))
        save_global_state("oauth_google_client_secret", encrypt(client_secret))


def get_oauth_status() -> dict:
    """Get OAuth configuration status for UI display."""
    return {
        "github_configured": bool(GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET),
        "google_configured": bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET),
    }

# Scopes
GITHUB_SCOPES = "repo,gist,read:user"
GOOGLE_SCOPES = " ".join([
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/tasks",
    "https://www.googleapis.com/auth/userinfo.email",
])


def is_configured(service: str) -> bool:
    if service == "github":
        return bool(GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET)
    elif service == "google":
        return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)
    return False


def get_authorize_url(service: str, redirect_uri: str, state: str = "") -> str | None:
    """Generate the OAuth authorization URL for a service."""
    if service == "github" and is_configured("github"):
        params = urllib.parse.urlencode({
            "client_id": GITHUB_CLIENT_ID,
            "scope": GITHUB_SCOPES,
            "redirect_uri": redirect_uri,
            "state": state,
        })
        return f"https://github.com/login/oauth/authorize?{params}"

    elif service == "google" and is_configured("google"):
        params = urllib.parse.urlencode({
            "client_id": GOOGLE_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": GOOGLE_SCOPES,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        })
        return f"https://accounts.google.com/o/oauth2/v2/auth?{params}"

    return None


def exchange_code(service: str, code: str, redirect_uri: str) -> dict:
    """Exchange an authorization code for an access token."""
    try:
        if service == "github":
            data = urllib.parse.urlencode({
                "client_id": GITHUB_CLIENT_ID,
                "client_secret": GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": redirect_uri,
            }).encode()
            req = urllib.request.Request(
                "https://github.com/login/oauth/access_token",
                data=data,
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read().decode())
            if "access_token" in result:
                return {"ok": True, "access_token": result["access_token"], "scope": result.get("scope", "")}
            return {"error": result.get("error_description", result.get("error", "Token exchange failed"))}

        elif service == "google":
            data = urllib.parse.urlencode({
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            }).encode()
            req = urllib.request.Request(
                "https://oauth2.googleapis.com/token",
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read().decode())
            if "access_token" in result:
                return {
                    "ok": True,
                    "access_token": result["access_token"],
                    "refresh_token": result.get("refresh_token", ""),
                    "expires_in": result.get("expires_in", 3600),
                }
            return {"error": result.get("error_description", result.get("error", "Token exchange failed"))}

        return {"error": f"Unknown service: {service}"}

    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        log.error(f"OAuth token exchange failed for {service}: {e.code} {body}")
        return {"error": f"HTTP {e.code}: {body[:200]}"}
    except Exception as e:
        log.error(f"OAuth token exchange error for {service}: {e}")
        return {"error": str(e)}


def refresh_google_token(refresh_token: str) -> dict:
    """Refresh an expired Google access token."""
    if not is_configured("google") or not refresh_token:
        return {"error": "Not configured or no refresh token"}
    try:
        data = urllib.parse.urlencode({
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }).encode()
        req = urllib.request.Request(
            "https://oauth2.googleapis.com/token",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode())
        if "access_token" in result:
            return {"ok": True, "access_token": result["access_token"], "expires_in": result.get("expires_in", 3600)}
        return {"error": result.get("error", "Refresh failed")}
    except Exception as e:
        return {"error": str(e)}


# HTML page returned after OAuth callback — closes the popup/tab
CALLBACK_SUCCESS_HTML = """<!DOCTYPE html>
<html><head><title>OmniAgent - Connected</title>
<style>
body{background:#0d1117;color:#e6edf3;font-family:system-ui;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
.card{text-align:center;padding:40px;border:1px solid #30363d;border-radius:12px;background:#161b22}
h2{color:#58a6ff;margin:0 0 10px} p{color:#8b949e;margin:0 0 20px}
.ok{font-size:48px;margin-bottom:10px}
</style></head>
<body><div class="card">
<div class="ok">&#x2705;</div>
<h2>{service} Connected</h2>
<p>You can close this window now.</p>
<script>
try {{ window.opener && window.opener.postMessage({{type:'oauth_complete',service:'{service_lower}'}}, '*'); }} catch(e){{}}
setTimeout(function(){{ window.close(); }}, 2000);
</script>
</div></body></html>"""

CALLBACK_ERROR_HTML = """<!DOCTYPE html>
<html><head><title>OmniAgent - Error</title>
<style>
body{background:#0d1117;color:#e6edf3;font-family:system-ui;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
.card{text-align:center;padding:40px;border:1px solid #30363d;border-radius:12px;background:#161b22}
h2{color:#f85149;margin:0 0 10px} p{color:#8b949e;margin:0 0 20px}
.err{font-size:48px;margin-bottom:10px}
</style></head>
<body><div class="card">
<div class="err">&#x274C;</div>
<h2>Connection Failed</h2>
<p>{error}</p>
<script>setTimeout(function(){{ window.close(); }}, 5000);</script>
</div></body></html>"""
