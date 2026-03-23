"""
External service integrations: GitHub, Google Drive, Google Keep.
Uses personal access tokens / API keys for authentication.
"""
import json
import urllib.request
import urllib.error
import urllib.parse
from dataclasses import dataclass, field


def _get_tokens():
    """Get integration tokens from the active session — NOT a global object.
    This ensures User A's tokens are never used for User B's requests."""
    from src.state import state
    session = state.session
    return session.github_token, session.google_token


def get_integration_status() -> dict:
    gh, gd = _get_tokens()
    return {
        "github": {"connected": bool(gh), "has_token": bool(gh)},
        "google_drive": {"connected": bool(gd), "has_token": bool(gd)},
        "google_keep": {"connected": bool(gd), "has_token": bool(gd)},
    }


# Legacy compatibility — will be removed once all callsites use session tokens
@dataclass
class IntegrationTokens:
    @property
    def github_token(self):
        from src.state import state
        return state.session.github_token
    @github_token.setter
    def github_token(self, val):
        from src.state import state
        state.session.github_token = val
    @property
    def google_token(self):
        from src.state import state
        return state.session.google_token
    @google_token.setter
    def google_token(self, val):
        from src.state import state
        state.session.google_token = val
    def to_dict(self):
        return get_integration_status()

tokens = IntegrationTokens()


# =========================================================
# GitHub Integration
# Uses Personal Access Token (PAT) — no OAuth app needed
# =========================================================

def _github_request(endpoint: str, method: str = "GET", data: dict | None = None) -> dict | list:
    if not tokens.github_token:
        raise ValueError("GitHub token not configured. Set it in Settings.")
    url = f"https://api.github.com{endpoint}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method=method, headers={
        "Authorization": f"Bearer {tokens.github_token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "OmniAgent/8.0",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        # Sanitize — don't expose headers/tokens in error messages
        raise ValueError(f"GitHub API error {e.code} on {endpoint}") from None
    except urllib.error.URLError as e:
        raise ValueError(f"Network error reaching GitHub: {e.reason}") from None


def github_user() -> dict:
    return _github_request("/user")


def github_repos(per_page: int = 20) -> list:
    return _github_request(f"/user/repos?per_page={per_page}&sort=updated")


def github_repo_contents(owner: str, repo: str, path: str = "") -> list:
    return _github_request(f"/repos/{owner}/{repo}/contents/{path}")


def github_read_file(owner: str, repo: str, path: str) -> str:
    import base64
    data = _github_request(f"/repos/{owner}/{repo}/contents/{path}")
    if isinstance(data, dict) and data.get("encoding") == "base64":
        return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
    return str(data)


def github_create_file(owner: str, repo: str, path: str, content: str, message: str, branch: str = "main") -> dict:
    import base64
    return _github_request(f"/repos/{owner}/{repo}/contents/{path}", method="PUT", data={
        "message": message,
        "content": base64.b64encode(content.encode()).decode(),
        "branch": branch,
    })


def github_create_gist(description: str, files: dict[str, str], public: bool = False) -> dict:
    return _github_request("/gists", method="POST", data={
        "description": description,
        "public": public,
        "files": {name: {"content": content} for name, content in files.items()},
    })


def github_list_gists(per_page: int = 10) -> list:
    return _github_request(f"/gists?per_page={per_page}")


def github_search_code(query: str, per_page: int = 10) -> dict:
    q = urllib.parse.quote(query)
    return _github_request(f"/search/code?q={q}&per_page={per_page}")


def github_create_issue(owner: str, repo: str, title: str, body: str) -> dict:
    return _github_request(f"/repos/{owner}/{repo}/issues", method="POST", data={
        "title": title,
        "body": body,
    })


# =========================================================
# Google Drive Integration
# Uses OAuth2 access token (user gets it from Google OAuth Playground
# or from a proper OAuth flow)
# =========================================================

def _google_request(url: str, method: str = "GET", data: dict | None = None, raw_body: bytes | None = None, extra_headers: dict | None = None) -> dict | list:
    body = raw_body or (json.dumps(data).encode() if data else None)
    headers = {
        "Authorization": f"Bearer {tokens.google_token}",
        "User-Agent": "OmniAgent/8.0",
    }
    if data and not raw_body:
        headers["Content-Type"] = "application/json"
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


def gdrive_list_files(query: str = "", page_size: int = 20) -> dict:
    params = f"pageSize={page_size}&fields=files(id,name,mimeType,modifiedTime,size)"
    if query:
        params += f"&q={urllib.parse.quote(query)}"
    return _google_request(f"https://www.googleapis.com/drive/v3/files?{params}")


def gdrive_read_file(file_id: str) -> str:
    """Download file content as text."""
    url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {tokens.google_token}",
        "User-Agent": "OmniAgent/8.0",
    })
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="replace")


def gdrive_upload_file(name: str, content: str, mime_type: str = "text/plain", folder_id: str | None = None) -> dict:
    """Upload a text file to Google Drive."""
    metadata = {"name": name, "mimeType": mime_type}
    if folder_id:
        metadata["parents"] = [folder_id]

    # Simple upload for text files
    boundary = "omniagent_boundary"
    body = (
        f"--{boundary}\r\n"
        f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{json.dumps(metadata)}\r\n"
        f"--{boundary}\r\n"
        f"Content-Type: {mime_type}\r\n\r\n"
        f"{content}\r\n"
        f"--{boundary}--"
    ).encode()

    url = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id,name,webViewLink"
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {tokens.google_token}",
        "Content-Type": f"multipart/related; boundary={boundary}",
        "User-Agent": "OmniAgent/8.0",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def gdrive_create_folder(name: str) -> dict:
    return _google_request("https://www.googleapis.com/drive/v3/files?fields=id,name", method="POST", data={
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
    })


# =========================================================
# Google Keep Integration
# Keep has no public API. We use Google Tasks API as a structured
# note-taking alternative, plus support for exporting to Keep-compatible format.
# =========================================================

def gtasks_list_tasklists() -> dict:
    return _google_request("https://tasks.googleapis.com/tasks/v1/users/@me/lists")


def gtasks_list_tasks(tasklist_id: str = "@default") -> dict:
    return _google_request(f"https://tasks.googleapis.com/tasks/v1/lists/{tasklist_id}/tasks")


def gtasks_create_task(title: str, notes: str = "", tasklist_id: str = "@default") -> dict:
    data = {"title": title}
    if notes:
        data["notes"] = notes
    return _google_request(
        f"https://tasks.googleapis.com/tasks/v1/lists/{tasklist_id}/tasks",
        method="POST", data=data,
    )


def gtasks_create_tasklist(title: str) -> dict:
    return _google_request(
        "https://tasks.googleapis.com/tasks/v1/users/@me/lists",
        method="POST", data={"title": title},
    )


# =========================================================
# Convenience: Save chat/content to any service
# =========================================================

def save_to_github_gist(title: str, content: str, filename: str = "omni_export.md") -> dict | str:
    if not tokens.github_token:
        return "GitHub not connected. Add your Personal Access Token in Settings."
    try:
        result = github_create_gist(title, {filename: content})
        return result.get("html_url", str(result))
    except Exception as e:
        return f"GitHub error: {e}"


def save_to_drive(title: str, content: str) -> dict | str:
    if not tokens.google_token:
        return "Google Drive not connected. Add your OAuth token in Settings."
    try:
        result = gdrive_upload_file(title, content)
        return result.get("webViewLink", str(result))
    except Exception as e:
        return f"Drive error: {e}"


def save_to_tasks(title: str, notes: str = "") -> dict | str:
    if not tokens.google_token:
        return "Google not connected. Add your OAuth token in Settings."
    try:
        result = gtasks_create_task(title, notes)
        return result
    except Exception as e:
        return f"Tasks error: {e}"
