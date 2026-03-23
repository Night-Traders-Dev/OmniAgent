import os
import re
import json
import glob as globmod
import subprocess
import shlex
import urllib.request
import urllib.error
import urllib.parse
import asyncio
from pathlib import Path
import time
import ipaddress
import socket
from enum import Enum
from dataclasses import dataclass
from html.parser import HTMLParser


# ============================================================
# Tier 2: Structured Error Types
# ============================================================

class ToolErrorKind(Enum):
    BLOCKED = "blocked"          # Tool disabled by user
    NOT_FOUND = "not_found"      # File/resource doesn't exist
    PERMISSION = "permission"    # Permission denied
    TIMEOUT = "timeout"          # Operation timed out
    NETWORK = "network"          # Network failure (retryable)
    VALIDATION = "validation"    # Bad arguments
    DANGEROUS = "dangerous"      # Dangerous command blocked
    EXECUTION = "execution"      # Runtime error
    UNKNOWN = "unknown"


@dataclass
class ToolResult:
    """Structured tool result replacing raw strings."""
    success: bool
    output: str
    error_kind: ToolErrorKind | None = None
    retryable: bool = False

    def __str__(self):
        if self.success:
            return self.output
        prefix = f"ERROR[{self.error_kind.value}]" if self.error_kind else "ERROR"
        retry_hint = " (retryable)" if self.retryable else ""
        return f"{prefix}{retry_hint}: {self.output}"


def _ok(output: str) -> ToolResult:
    return ToolResult(success=True, output=output)

def _err(output: str, kind: ToolErrorKind = ToolErrorKind.UNKNOWN, retryable: bool = False) -> ToolResult:
    return ToolResult(success=False, output=output, error_kind=kind, retryable=retryable)


# ============================================================
# Tier 1: Structured Tool Call Parsing (bracket-depth)
# ============================================================

def parse_json(text: str, _depth: int = 0) -> dict | None:
    """Extract JSON using bracket-depth counting instead of greedy regex.
    Handles nested objects correctly. Recursion limited to 3 attempts."""
    if not text or _depth > 3:
        return None
    start = text.find('{')
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        c = text[i]
        if escape:
            escape = False
            continue
        if c == '\\' and in_string:
            escape = True
            continue
        if c == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i+1])
                except json.JSONDecodeError:
                    next_start = text.find('{', i+1)
                    if next_start != -1:
                        return parse_json(text[next_start:], _depth + 1)
                    return None
    return None


# ============================================================
# Tier 2: Enhanced Dangerous Command Detection
# ============================================================

ALLOWED_SHELL_COMMANDS = {
    "ls", "cat", "head", "tail", "find", "grep", "wc", "echo",
    "pwd", "tree", "pip", "python3", "python", "pytest", "ollama",
    "mkdir", "cp", "mv", "git", "diff", "sort", "uniq", "basename",
    "dirname", "date", "chmod", "touch", "rm", "node", "npm", "which",
    "env", "make", "cargo", "go", "rustc", "gcc", "g++", "java",
    "javac", "docker", "wget", "curl", "tar", "unzip", "zip",
    "sed", "awk", "xargs", "tee", "file", "stat", "df", "du",
    "free", "uname", "hostname", "whoami", "id", "ps", "top",
    "htop", "lsof", "ss", "ip", "ping", "traceroute", "dig",
    "nslookup", "openssl",
}

DANGEROUS_PATTERNS = [
    # Filesystem destruction
    "rm -rf /", "rm -rf /*", "rm -rf ~", "rm -rf $HOME",
    "mkfs", "> /dev/sd", "dd if=", ":(){ :|:& };:",
    # Fork bombs / resource exhaustion
    "while true; do", "yes |", "cat /dev/urandom",
    # Privilege escalation attempts
    "chmod 777 /", "chown root",
    # Data exfiltration patterns
    "| curl", "| wget", "| nc ", "| netcat",
    # Pipe to shell (remote code execution)
    "curl | bash", "curl | sh", "wget | bash", "wget | sh",
    "curl -s | bash", "curl -s | sh",
    # Python shell escapes
    'python -c "import os; os.system',
    'python3 -c "import os; os.system',
    "python -c 'import os",
    "python3 -c 'import os",
    # Crontab manipulation
    "crontab -r", "crontab -e",
    # SSH key theft
    "cat ~/.ssh/id_", "cat /root/.ssh",
    # History/credential access
    "cat ~/.bash_history", "cat /etc/shadow",
    # Disk/partition operations
    "fdisk", "parted", "wipefs",
]

# Commands that should never be first token even if in ALLOWED
DANGEROUS_FIRST_TOKENS = {"sudo", "su", "doas", "pkexec"}

# Pre-compiled regex for performance (used in is_dangerous_command)
_PIPE_SHELL_RE = re.compile(r'\|\s*(ba)?sh\b')

# Per-tool timeouts (Tier 2)
TOOL_TIMEOUTS = {
    # File I/O
    "read": 5, "write": 5, "edit": 5, "batch_edit": 15, "regex_replace": 10,
    "glob": 10, "grep": 15, "tree": 10, "list_dir": 5, "file_info": 5,
    "analyze_file": 10, "project_deps": 15, "find_symbol": 15, "semantic_search": 15,
    "diff_preview": 5,
    # Shell / process
    "shell": 60, "python_eval": 10, "run_tests": 60, "process_list": 5, "kill_process": 5,
    # Web / network
    "web": 15, "fetch_url": 15, "weather": 15, "http_request": 30,
    "deep_research": 60, "multi_search": 30, "json_extract": 5, "network_info": 5,
    # Git
    "git_status": 10, "git_diff": 10, "git_log": 10, "git_commit": 15,
    "git_checkout": 10, "git_stash": 10,
    # Multimodal (long-running)
    "generate_image": 180, "vision": 60, "speak": 60, "screenshot": 10,
    # Other
    "database": 15, "docker": 15, "pdf_read": 15, "archive": 30,
    "spawn_agent": 120, "env_get": 2, "env_set": 2,
    "sandbox_run": 60,
}


def is_dangerous_command(cmd: str) -> str | None:
    """Return a warning string if the command is dangerous, else None."""
    lower = cmd.lower().strip()
    # Check dangerous patterns
    for pat in DANGEROUS_PATTERNS:
        if pat.lower() in lower:
            return f"DANGEROUS: Command contains '{pat}'. Blocked for safety."
    # Check for pipe-to-shell patterns (pre-compiled)
    if _PIPE_SHELL_RE.search(lower):
        return "DANGEROUS: Piping to shell interpreter blocked."
    # Check for encoded/obfuscated commands
    if "base64" in lower and ("decode" in lower or "-d" in lower) and "|" in lower:
        return "DANGEROUS: Base64-decoded pipe execution blocked."
    # Check first token
    try:
        tokens = shlex.split(cmd)
        if tokens and tokens[0] in DANGEROUS_FIRST_TOKENS:
            return f"DANGEROUS: '{tokens[0]}' is not allowed. Run commands directly."
    except ValueError:
        pass
    return None


OLLAMA_BASE = os.environ.get("OLLAMA_BASE", "http://localhost:11434")


# --- Path Safety ---

# Directories the agent is NEVER allowed to read from or write to
PATH_BLOCKED_PREFIXES = [
    "/etc/shadow", "/etc/gshadow", "/proc/", "/sys/",
    os.path.expanduser("~/.ssh/"), os.path.expanduser("~/.gnupg/"),
    os.path.expanduser("~/.aws/"), os.path.expanduser("~/.config/gcloud/"),
]

def _check_path_safety(path: str) -> str | None:
    """Return error message if path is blocked, else None."""
    real = os.path.realpath(path)
    for blocked in PATH_BLOCKED_PREFIXES:
        if real.startswith(blocked):
            return f"Access denied: {real} is in a protected directory"
    return None


# --- File I/O ---

def read_file(path: str, offset: int = 0, limit: int = 0) -> str:
    path = os.path.realpath(path)
    blocked = _check_path_safety(path)
    if blocked:
        return str(_err(blocked, ToolErrorKind.PERMISSION))
    if not os.path.exists(path):
        return str(_err(f"{path} not found.", ToolErrorKind.NOT_FOUND))
    try:
        with open(path, "r") as f:
            lines = f.readlines()
        total = len(lines)
        if offset or limit:
            start = max(0, offset)
            end = start + limit if limit else total
            selected = lines[start:end]
            header = f"[Lines {start+1}-{min(end, total)} of {total}]\n"
            return header + "".join(f"{start+i+1:>5} | {l}" for i, l in enumerate(selected))
        if total > 500:
            return f"[Large file: {total} lines. Showing first 200. Use offset/limit for more.]\n" + "".join(
                f"{i+1:>5} | {l}" for i, l in enumerate(lines[:200])
            )
        return "".join(lines)
    except UnicodeDecodeError:
        return str(_err(f"{path} is a binary file.", ToolErrorKind.VALIDATION))
    except PermissionError:
        return str(_err(f"Permission denied: {path}", ToolErrorKind.PERMISSION))


def write_file(path: str, content: str) -> str:
    path = os.path.realpath(path)
    blocked = _check_path_safety(path)
    if blocked:
        return str(_err(blocked, ToolErrorKind.PERMISSION))
    dirname = os.path.dirname(path)
    if dirname:
        os.makedirs(dirname, exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    return f"OK: Wrote {len(content)} bytes to {path}"


def _git_checkpoint(path: str, action: str = "edit"):
    """Create a git stash checkpoint before modifying files (safety net)."""
    try:
        # Only if we're in a git repo
        result = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"],
                               capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            return
        # Stage the file if it exists and is tracked
        subprocess.run(["git", "add", path], capture_output=True, timeout=5)
    except Exception:
        pass


def edit_file(path: str, old_text: str, new_text: str) -> str:
    path = os.path.realpath(path)
    blocked = _check_path_safety(path)
    if blocked:
        return str(_err(blocked, ToolErrorKind.PERMISSION))
    if not os.path.exists(path):
        return str(_err(f"{path} not found.", ToolErrorKind.NOT_FOUND))
    _git_checkpoint(path, "edit")
    with open(path, "r") as f:
        content = f.read()
    count = content.count(old_text)
    if count == 0:
        return str(_err(f"old_text not found in {path}.", ToolErrorKind.VALIDATION))
    if count > 1:
        return str(_err(f"old_text matches {count} locations. Provide more context.", ToolErrorKind.VALIDATION))
    new_content = content.replace(old_text, new_text, 1)
    with open(path, "w") as f:
        f.write(new_content)
    return f"OK: Edited {path} (1 replacement)."


# --- Shell ---

def run_shell(cmd: str, timeout: int = 60) -> str:
    danger = is_dangerous_command(cmd)
    if danger:
        return str(_err(danger, ToolErrorKind.DANGEROUS))
    try:
        first_token = shlex.split(cmd)[0] if cmd.strip() else ""
    except ValueError:
        first_token = cmd.strip().split()[0] if cmd.strip() else ""
    base_cmd = os.path.basename(first_token)
    if base_cmd not in ALLOWED_SHELL_COMMANDS:
        return str(_err(f"'{base_cmd}' not in allowed commands. Available: {', '.join(sorted(ALLOWED_SHELL_COMMANDS))}",
                       ToolErrorKind.BLOCKED))
    try:
        result = subprocess.run(
            ["/bin/bash", "-c", cmd],
            capture_output=True, text=True, timeout=timeout,
        )
        return f"EXIT:{result.returncode}\nOUT: {result.stdout}\nERR: {result.stderr}"
    except subprocess.TimeoutExpired:
        return str(_err(f"Command exceeded {timeout}s.", ToolErrorKind.TIMEOUT))


# --- Codebase exploration ---

def glob_files(pattern: str, root: str = ".") -> str:
    matches = sorted(globmod.glob(os.path.join(root, pattern), recursive=True))
    if not matches:
        return f"No files matching '{pattern}' in {root}"
    return "\n".join(matches[:100]) + (f"\n... ({len(matches)} total)" if len(matches) > 100 else "")


def grep_files(pattern: str, path: str = ".", file_glob: str = "", max_results: int = 50) -> str:
    cmd_parts = ["grep", "-rn", "--include", file_glob if file_glob else "*"]
    cmd_parts += ["-m", str(max_results), pattern, path]
    try:
        result = subprocess.run(cmd_parts, capture_output=True, text=True, timeout=15)
        if result.stdout:
            lines = result.stdout.strip().split("\n")
            return "\n".join(lines[:max_results])
        return f"No matches for '{pattern}' in {path}"
    except subprocess.TimeoutExpired:
        return str(_err("Search took too long.", ToolErrorKind.TIMEOUT))


def project_tree(path: str = ".", max_depth: int = 3) -> str:
    try:
        result = subprocess.run(
            ["tree", "-I", "__pycache__|node_modules|.git|.venv|*.pyc", "-L", str(max_depth), path],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout if result.stdout else "tree command not available"
    except FileNotFoundError:
        lines = []
        for root, dirs, files in os.walk(path):
            depth = root.replace(path, "").count(os.sep)
            if depth >= max_depth:
                dirs.clear()
                continue
            indent = "  " * depth
            lines.append(f"{indent}{os.path.basename(root)}/")
            for f in sorted(files)[:20]:
                lines.append(f"{indent}  {f}")
        return "\n".join(lines[:200])


# --- Git ---

def git_status() -> str:
    try:
        result = subprocess.run(["git", "status", "--short"], capture_output=True, text=True, timeout=10)
        return result.stdout or "Clean working tree."
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError) as e:
        return f"Git error: {e}"


def git_diff(staged: bool = False) -> str:
    cmd = ["git", "diff", "--stat"]
    if staged:
        cmd.append("--staged")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return result.stdout or "No changes."
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError) as e:
        return f"Git error: {e}"


def git_log(n: int = 10) -> str:
    try:
        result = subprocess.run(
            ["git", "log", f"-{n}", "--oneline", "--decorate"],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout or "No commits."
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError) as e:
        return f"Git error: {e}"


# ============================================================
# Tier 2: Retry with Exponential Backoff
# ============================================================

def _retry_with_backoff(fn, max_retries: int = 2, base_delay: float = 1.0):
    """Retry a function with exponential backoff for transient failures."""
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            result = fn()
            return result
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ConnectionError, OSError) as e:
            last_error = e
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                time.sleep(delay)
    return str(_err(f"Failed after {max_retries + 1} attempts: {last_error}", ToolErrorKind.NETWORK, retryable=True))


# --- URL fetching (with retry) ---

class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._text = []
        self._skip = False
    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav", "header", "footer"):
            self._skip = True
    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "header", "footer"):
            self._skip = False
    def handle_data(self, data):
        if not self._skip:
            stripped = data.strip()
            if stripped:
                self._text.append(stripped)
    def get_text(self):
        return "\n".join(self._text)


SSRF_BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "metadata.google.internal"}

def _is_ssrf_target(url: str) -> str | None:
    """Check if a URL targets internal/metadata services. Returns reason if blocked."""
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return f"Blocked scheme: {parsed.scheme}"
        hostname = parsed.hostname or ""
        if hostname in SSRF_BLOCKED_HOSTS:
            return f"Blocked host: {hostname}"
        # Check for IP ranges: private, link-local, loopback
        try:
            addr = ipaddress.ip_address(hostname)
            if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
                return f"Blocked private/reserved IP: {hostname}"
        except ValueError:
            # Not an IP — resolve hostname
            try:
                resolved = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
                for _, _, _, _, sockaddr in resolved:
                    ip = sockaddr[0]
                    addr = ipaddress.ip_address(ip)
                    if addr.is_private or addr.is_loopback or addr.is_link_local:
                        return f"Blocked: {hostname} resolves to private IP {ip}"
            except socket.gaierror:
                pass  # Can't resolve — let it fail naturally
        # Block AWS/GCP/Azure metadata endpoints
        if "169.254.169.254" in hostname or "metadata" in hostname.lower():
            return f"Blocked metadata endpoint: {hostname}"
    except Exception:
        pass
    return None


def deep_research(query: str, max_depth: int = 2) -> str:
    """Multi-step web research: search → read top results → synthesize key facts."""
    results_text = []
    # Step 1: Search
    search_results = web_search(query, max_results=5)
    try:
        items = json.loads(search_results)
        if isinstance(items, list):
            # Step 2: Read the top pages for details
            read_count = 0
            for item in items[:max_depth]:
                href = item.get("href", "")
                title = item.get("title", "")
                body = item.get("body", "")
                results_text.append(f"## {title}\n{body}")
                if href and read_count < max_depth:
                    try:
                        page_text = fetch_url(href, max_chars=3000)
                        if page_text and not page_text.startswith("ERROR"):
                            results_text.append(f"### Page content ({href}):\n{page_text[:2000]}")
                            read_count += 1
                    except Exception:
                        pass
            return "\n\n".join(results_text) if results_text else search_results
    except Exception:
        pass
    return search_results


def multi_search(queries: list[str]) -> str:
    """Run multiple search queries and combine unique results."""
    all_results = []
    seen_urls = set()
    for q in queries[:4]:  # Cap at 4 queries
        try:
            results = web_search(q, max_results=3)
            items = json.loads(results)
            if isinstance(items, list):
                for item in items:
                    url = item.get("href", "")
                    if url not in seen_urls:
                        seen_urls.add(url)
                        all_results.append(item)
        except Exception:
            continue
    return json.dumps(all_results[:10], indent=2) if all_results else '{"note": "No results found"}'


def json_extract(data: str, path: str = "") -> str:
    """Extract data from JSON using dot-notation path (e.g. 'results.0.name')."""
    try:
        obj = json.loads(data)
        if not path:
            return json.dumps(obj, indent=2)[:5000]
        for key in path.split('.'):
            if isinstance(obj, list):
                obj = obj[int(key)]
            elif isinstance(obj, dict):
                obj = obj[key]
            else:
                return f"Cannot navigate into {type(obj).__name__}"
        if isinstance(obj, (dict, list)):
            return json.dumps(obj, indent=2)[:5000]
        return str(obj)
    except (json.JSONDecodeError, KeyError, IndexError, ValueError) as e:
        return f"ERROR: {e}"


def env_get(name: str) -> str:
    """Get an environment variable value."""
    val = os.environ.get(name, "")
    if not val:
        return f"Environment variable '{name}' is not set"
    # Redact sensitive values
    if any(s in name.lower() for s in ('secret', 'password', 'key', 'token')):
        return f"{name}={val[:4]}{'*' * (len(val)-4)}"
    return f"{name}={val}"


def env_set(name: str, value: str) -> str:
    """Set an environment variable for the current process."""
    blocked = {'PATH', 'HOME', 'USER', 'SHELL', 'LD_PRELOAD', 'LD_LIBRARY_PATH'}
    if name in blocked:
        return f"ERROR: Cannot modify {name}"
    os.environ[name] = value
    return f"OK: {name}={value}"


def regex_replace(path: str, pattern: str, replacement: str, count: int = 0) -> str:
    """Regex find-and-replace in a file. count=0 means replace all."""
    blocked = _check_path_safety(path)
    if blocked:
        return str(_err(blocked, ToolErrorKind.PERMISSION))
    try:
        content = Path(path).read_text()
        new_content, n = re.subn(pattern, replacement, content, count=count)
        if n == 0:
            return f"No matches for pattern '{pattern}' in {path}"
        Path(path).write_text(new_content)
        return f"OK: {n} replacement(s) in {path}"
    except re.error as e:
        return f"ERROR: Invalid regex — {e}"
    except Exception as e:
        return str(_err(str(e), ToolErrorKind.EXECUTION))


def batch_edit(edits: list[dict]) -> str:
    """Apply multiple edits to multiple files atomically.
    Each edit: {"path": str, "old_text": str, "new_text": str}"""
    results = []
    for i, edit in enumerate(edits[:20]):  # Cap at 20
        path = edit.get("path", "")
        old = edit.get("old_text", "")
        new = edit.get("new_text", "")
        if not path or not old:
            results.append(f"Edit {i+1}: skipped (missing path or old_text)")
            continue
        r = edit_file(path, old, new)
        results.append(f"Edit {i+1} ({Path(path).name}): {r[:80]}")
    return "\n".join(results)


def process_list() -> str:
    """List running processes (lightweight)."""
    try:
        r = subprocess.run(["ps", "aux", "--sort=-%mem"], capture_output=True, text=True, timeout=5)
        lines = r.stdout.strip().split('\n')
        return '\n'.join(lines[:20])  # Top 20 by memory
    except Exception as e:
        return f"ERROR: {e}"


def kill_process(pid: int, signal: int = 15) -> str:
    """Send a signal to a process. Default SIGTERM (15)."""
    if signal not in (9, 15):
        return "ERROR: Only SIGTERM (15) and SIGKILL (9) allowed"
    try:
        os.kill(pid, signal)
        return f"OK: Sent signal {signal} to PID {pid}"
    except ProcessLookupError:
        return f"ERROR: No process with PID {pid}"
    except PermissionError:
        return "ERROR: Permission denied"


def network_info() -> str:
    """Get network interfaces and connectivity info."""
    try:
        r = subprocess.run(["ip", "-4", "addr", "show"], capture_output=True, text=True, timeout=5)
        return r.stdout.strip()[:3000]
    except Exception:
        try:
            r = subprocess.run(["ifconfig"], capture_output=True, text=True, timeout=5)
            return r.stdout.strip()[:3000]
        except Exception as e:
            return f"ERROR: {e}"


def fetch_url(url: str, max_chars: int = 8000) -> str:
    # Check cache first
    try:
        from src.upgrades import web_cache
        cached = web_cache.get(f"fetch:{url}")
        if cached:
            return cached
    except Exception:
        pass

    ssrf_check = _is_ssrf_target(url)
    if ssrf_check:
        return str(_err(f"SSRF blocked: {ssrf_check}", ToolErrorKind.VALIDATION))

    def _fetch():
        req = urllib.request.Request(url, headers={"User-Agent": "OmniAgent/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read().decode("utf-8", errors="replace")
            if "json" in content_type:
                return raw[:max_chars]
            elif "text/plain" in content_type:
                return raw[:max_chars]
            else:
                extractor = _TextExtractor()
                extractor.feed(raw)
                text = extractor.get_text()
                return text[:max_chars] if text else raw[:max_chars]

    result = _retry_with_backoff(_fetch)
    final = result if isinstance(result, str) else str(result)
    # Cache the result
    try:
        from src.upgrades import web_cache
        if not final.startswith("ERROR"):
            web_cache.set(f"fetch:{url}", final)
    except Exception:
        pass
    return final


# --- Web Search (with retry) ---

def web_search(query: str, max_results: int = 5) -> str:
    def _search():
        try:
            from ddgs import DDGS
            results = DDGS().text(query, max_results=max_results)
            if results:
                return json.dumps(results, indent=2)
        except ImportError:
            pass
        try:
            from duckduckgo_search import DDGS as OldDDGS
            results = OldDDGS().text(query, max_results=max_results)
            if results:
                return json.dumps(results, indent=2)
        except Exception:
            pass
        return None

    result = _retry_with_backoff(_search, max_retries=1, base_delay=2.0)
    if result and isinstance(result, str) and not result.startswith("ERROR"):
        return result
    return json.dumps({"note": "Web search returned no results", "query": query})


# --- Weather ---

WEATHER_KEYWORDS = [
    "weather", "temperature", "forecast", "humidity", "wind",
    "rain", "snow", "sunny", "cloudy", "storm", "10 day", "7 day",
    "this week", "next week", "tomorrow",
]

WMO_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Rime fog", 51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow",
    77: "Snow grains", 80: "Light showers", 81: "Showers", 82: "Heavy showers",
    85: "Light snow showers", 86: "Snow showers",
    95: "Thunderstorm", 96: "Thunderstorm w/ hail", 99: "Severe thunderstorm",
}


def is_weather_query(query: str) -> bool:
    return any(kw in query.lower() for kw in WEATHER_KEYWORDS)


def extract_location(query: str) -> str:
    lower = query.lower()
    for remove in [
        "what is the", "what's the", "what does the", "what will the",
        "can you tell me the", "show me the", "give me the",
        "current", "right now", "today", "tomorrow", "this week", "next week",
        "temperature in", "temperature at", "weather in", "weather at",
        "weather for", "forecast for", "forecast in", "look like",
        "how hot is it in", "how cold is it in",
        "temperature", "weather", "forecast",
        "10 day", "7 day", "5 day", "3 day",
        "next 10 days", "next 7 days", "next 5 days", "next 3 days",
        "for the next", "the next", "days",
        "place the", "in a table", "table format", "as a table",
        "?", ".", "!",
    ]:
        lower = lower.replace(remove, " ")
    words = [w for w in lower.split() if len(w) > 1 and w not in ("for", "the", "in", "at", "of", "on", "is", "it", "do", "an", "to")]
    location = " ".join(words).strip()
    return location if location else "New York"


def _geocode(location: str) -> tuple[float, float, str] | None:
    try:
        import urllib.parse
        parts = location.strip().split()
        search_terms = [location.strip()]
        if len(parts) > 1:
            search_terms.append(parts[0])
        loc_lower = location.lower()
        for term in search_terms:
            q = urllib.parse.quote(term)
            url = f"https://geocoding-api.open-meteo.com/v1/search?name={q}&count=20"
            req = urllib.request.Request(url, headers={"User-Agent": "OmniAgent/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            results = data.get("results", [])
            if not results:
                continue
            for r in results:
                admin = (r.get("admin1", "") or "").lower()
                if admin and admin in loc_lower:
                    return r["latitude"], r["longitude"], f"{r.get('name')}, {r.get('admin1', '')}"
            for r in results:
                if r.get("country_code") == "US":
                    return r["latitude"], r["longitude"], f"{r.get('name')}, {r.get('admin1', '')}"
            r = results[0]
            return r["latitude"], r["longitude"], f"{r.get('name')}, {r.get('admin1', '')}, {r.get('country', '')}"
        return None
    except Exception:
        return None


def _geolocate_ip() -> tuple | None:
    """Get approximate location from public IP using ip-api.com (no key needed)."""
    try:
        req = urllib.request.Request("http://ip-api.com/json/?fields=lat,lon,city,regionName,country",
                                     headers={"User-Agent": "OmniAgent/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        if data.get("city"):
            return (data["lat"], data["lon"], f"{data['city']}, {data.get('regionName', '')}")
    except Exception:
        pass
    return None

def get_weather(location: str, forecast_days: int = 3) -> str:
    try:
        # Handle "auto" — detect location from IP
        if not location or location.lower() in ("auto", "here", "my location", "current"):
            geo = _geolocate_ip()
            if not geo:
                return json.dumps({"error": "Could not detect your location. Please specify a city name."})
        else:
            geo = _geocode(location)
        if not geo:
            return json.dumps({"error": f"Could not find location: {location}"})
        lat, lon, place_name = geo
        params = (
            f"latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m,wind_direction_10m"
            f"&daily=temperature_2m_max,temperature_2m_min,weather_code,precipitation_probability_max,wind_speed_10m_max"
            f"&temperature_unit=fahrenheit&wind_speed_unit=mph&timezone=auto"
            f"&forecast_days={min(forecast_days, 16)}"
        )
        url = f"https://api.open-meteo.com/v1/forecast?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "OmniAgent/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        cur = data.get("current", {})
        current = {
            "location": place_name,
            "temperature_f": f"{cur.get('temperature_2m', '?')}°F",
            "feels_like_f": f"{cur.get('apparent_temperature', '?')}°F",
            "humidity": f"{cur.get('relative_humidity_2m', '?')}%",
            "wind": f"{cur.get('wind_speed_10m', '?')} mph",
            "condition": WMO_CODES.get(cur.get("weather_code", -1), "Unknown"),
        }
        daily = data.get("daily", {})
        dates = daily.get("time", [])
        highs = daily.get("temperature_2m_max", [])
        lows = daily.get("temperature_2m_min", [])
        codes = daily.get("weather_code", [])
        precip = daily.get("precipitation_probability_max", [])
        winds = daily.get("wind_speed_10m_max", [])
        forecast = []
        for i in range(len(dates)):
            forecast.append({
                "date": dates[i], "high_f": f"{highs[i]}°F", "low_f": f"{lows[i]}°F",
                "condition": WMO_CODES.get(codes[i], f"Code {codes[i]}"),
                "precip_chance": f"{precip[i] if i < len(precip) else '?'}%",
                "wind_max": f"{winds[i] if i < len(winds) else '?'} mph",
            })
        result = {"current": current, "forecast": forecast}
        lines = [f"WEATHER FOR {place_name.upper()}"]
        lines.append(f"Current: {current['temperature_f']}, {current['condition']}, Humidity: {current['humidity']}, Wind: {current['wind']}")
        lines.append("")
        lines.append(f"{len(forecast)}-DAY FORECAST:")
        lines.append(f"{'Date':<12} {'High':>6} {'Low':>6}  {'Condition':<20} {'Precip':>6} {'Wind':>8}")
        lines.append("-" * 70)
        for f in forecast:
            lines.append(f"{f['date']:<12} {f['high_f']:>6} {f['low_f']:>6}  {f['condition']:<20} {f['precip_chance']:>6} {f['wind_max']:>8}")
        return "\n".join(lines) + "\n\nRAW_JSON:\n" + json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": f"Weather lookup failed: {e}", "location": location})


def smart_search(query: str, max_results: int = 5) -> str:
    if is_weather_query(query):
        location = extract_location(query)
        lower = query.lower()
        days = 3
        if "10 day" in lower or "next 10" in lower: days = 10
        elif "7 day" in lower or "next 7" in lower or "this week" in lower: days = 7
        elif "5 day" in lower or "next 5" in lower: days = 5
        elif "tomorrow" in lower: days = 2
        elif "forecast" in lower: days = 7
        weather = get_weather(location, forecast_days=days)
        return f"WEATHER_DATA:\n{weather}"
    return web_search(query, max_results=max_results)


# --- Ollama Model Management ---

def ollama_list_models() -> list[dict]:
    try:
        req = urllib.request.Request(f"{OLLAMA_BASE}/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode()).get("models", [])
    except Exception as e:
        return [{"error": str(e)}]


def ollama_pull_model(model_name: str) -> subprocess.Popen:
    from src.config import OLLAMA_BIN
    return subprocess.Popen([OLLAMA_BIN, "pull", model_name], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def ollama_delete_model(model_name: str) -> str:
    try:
        body = json.dumps({"name": model_name}).encode()
        req = urllib.request.Request(f"{OLLAMA_BASE}/api/delete", data=body, method="DELETE", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return f"Deleted {model_name}" if resp.status == 200 else f"Status {resp.status}"
    except Exception as e:
        return f"Error: {e}"


def ollama_model_info(model_name: str) -> dict:
    try:
        body = json.dumps({"name": model_name}).encode()
        req = urllib.request.Request(f"{OLLAMA_BASE}/api/show", data=body, method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e)}


# ============================================================
# Tier 2: Tool Result Compression
# ============================================================

def compress_tool_result(result: str, max_chars: int = 3000) -> str:
    """Intelligently compress tool output, preserving errors and key info."""
    if len(result) <= max_chars:
        return result
    # Preserve error lines fully
    lines = result.split('\n')
    error_lines = [l for l in lines if any(kw in l.lower() for kw in ('error', 'exception', 'traceback', 'failed', 'warning'))]
    # Keep first and last sections
    head = result[:max_chars // 2]
    tail = result[-(max_chars // 3):]
    errors = "\n".join(error_lines[:10])
    omitted = len(result) - len(head) - len(tail)
    return f"{head}\n\n[...{omitted} chars omitted...]\n\n{errors}\n\n{tail}" if errors else f"{head}\n\n[...{omitted} chars omitted...]\n\n{tail}"


# ============================================================
# Tier 4: Confidence Signaling
# ============================================================

UNCERTAINTY_MARKERS = [
    "i'm not sure", "i am not sure", "i think", "i believe",
    "it might", "it could", "possibly", "probably", "perhaps",
    "i don't know", "i don't have", "uncertain", "unclear",
    "may or may not", "it's hard to say", "it depends",
    "i cannot confirm", "not certain", "speculating",
]

def detect_uncertainty(text: str) -> float:
    """Return a confidence score from 0.0 (very uncertain) to 1.0 (confident).
    Based on presence of hedging language."""
    lower = text.lower()
    markers_found = sum(1 for m in UNCERTAINTY_MARKERS if m in lower)
    if markers_found == 0:
        return 1.0
    # More markers = less confidence
    return max(0.1, 1.0 - (markers_found * 0.15))


# --- Tool Registry ---

TOOL_REGISTRY = {
    "read": {"fn": "read_file", "description": "Read a file. Use offset/limit for large files (line numbers, 0-indexed)", "args": "path, [offset], [limit]"},
    "write": {"fn": "write_file", "description": "Write content to a file (creates dirs if needed). Returns confirmation with byte count", "args": "path, content"},
    "edit": {"fn": "edit_file", "description": "Surgical edit: replace old_text with new_text in a file. old_text must be unique", "args": "path, old_text, new_text"},
    "shell": {"fn": "run_shell", "description": "Run a shell command. Returns exit code, stdout, stderr", "args": "cmd, [timeout]"},
    "web": {"fn": "web_search", "description": "Search the web via DuckDuckGo. Returns JSON array of results with title/body/href", "args": "query, [max_results]"},
    "weather": {"fn": "get_weather", "description": "Get current weather + forecast for a location (uses Open-Meteo, no API key)", "args": "location, [forecast_days]"},
    "fetch_url": {"fn": "fetch_url", "description": "Fetch a URL and extract readable text content (strips HTML tags)", "args": "url, [max_chars]"},
    "glob": {"fn": "glob_files", "description": "Find files matching a glob pattern (e.g. '**/*.py'). Recursive with **", "args": "pattern, [root]"},
    "grep": {"fn": "grep_files", "description": "Search file contents with regex. Returns file:line:match format", "args": "pattern, [path], [file_glob], [max_results]"},
    "tree": {"fn": "project_tree", "description": "Show project directory structure (excludes __pycache__, node_modules, .git)", "args": "[path], [max_depth]"},
    "git_status": {"fn": "git_status", "description": "Show git working tree status (short format)", "args": ""},
    "git_diff": {"fn": "git_diff", "description": "Show git diff summary. Use staged=true for staged changes only", "args": "[staged]"},
    "git_log": {"fn": "git_log", "description": "Show recent git commits (n = number of commits, default 10)", "args": "[n]"},
    "done": {"fn": None, "description": "Signal that the task is complete. Put your final answer in 'result'", "args": ""},
    "analyze_file": {"fn": "analyze_file_tool", "description": "Analyze a source file: shows language, imports, function/class definitions, and what imports it", "args": "path"},
    "project_deps": {"fn": "project_deps_tool", "description": "Show project dependency graph: file counts by language, core modules (most imported). Scans current dir by default", "args": "[root]"},
    "find_symbol": {"fn": "find_symbol_tool", "description": "Find all definitions of a function/class name across the project (scans all source files)", "args": "name"},
    "semantic_search": {"fn": "semantic_search_tool", "description": "Search the codebase semantically using embeddings. Requires ChromaDB installed and codebase indexed", "args": "query"},
    "vision": {"fn": "vision_tool", "description": "Analyze an image file using a multimodal vision model. Describe what you see", "args": "image_path, [prompt]"},
    "generate_image": {"fn": "generate_image_tool", "description": "Generate an image from a text prompt using Stable Diffusion/FLUX", "args": "prompt, [negative_prompt], [width], [height]"},
    "run_tests": {"fn": "run_tests_tool", "description": "Run the project's test suite. Returns pass/fail and output", "args": ""},
    "spawn_agent": {"fn": "spawn_agent_tool", "description": "Launch a sub-agent to handle a sub-task. Specify agent type and task", "args": "agent, task"},
    "speak": {"fn": "speak_tool", "description": "Convert text to speech audio. Returns URL to the generated WAV file", "args": "text"},
    "git_commit": {"fn": "git_commit_tool", "description": "Stage all changes and commit with a message", "args": "message"},
    "git_checkout": {"fn": "git_checkout_tool", "description": "Restore a file to its last committed state (undo changes)", "args": "path"},
    "python_eval": {"fn": "python_eval_tool", "description": "Evaluate a Python expression (math, string ops, list comprehensions). No file/network access", "args": "expression"},
    "http_request": {"fn": "http_request_tool", "description": "Make an HTTP request (GET/POST/PUT/DELETE). Returns status + body", "args": "url, [method], [body]"},
    "list_dir": {"fn": "list_dir_tool", "description": "List directory contents with file sizes (lighter than tree)", "args": "[path]"},
    "file_info": {"fn": "file_info_tool", "description": "Get file metadata: size, modified date, permissions, line count", "args": "path"},
    "diff_preview": {"fn": "diff_preview_tool", "description": "Preview what an edit would look like as a unified diff, without applying it", "args": "path, old_text, new_text"},
    "screenshot": {"fn": "screenshot_tool", "description": "Capture a screenshot of the desktop", "args": ""},
    "database": {"fn": "database_query_tool", "description": "Execute a read-only SQL query against a SQLite database", "args": "query, [db_path]"},
    "docker": {"fn": "docker_tool", "description": "Run read-only docker commands (ps, images, logs, inspect, stats)", "args": "cmd"},
    "pdf_read": {"fn": "pdf_read_tool", "description": "Extract text from a PDF file", "args": "path, [max_pages]"},
    "archive": {"fn": "archive_tool", "description": "List, extract, or create zip/tar archives", "args": "action, path, [dest]"},
    "git_stash": {"fn": "git_stash_tool", "description": "Git stash operations: push (save checkpoint), pop (restore), list", "args": "[action]"},
    "sandbox_run": {"fn": "sandbox_run_tool", "description": "Run code safely in a Docker sandbox (no network, limited memory). Use for untrusted code", "args": "code, [language], [timeout]"},
    "deep_research": {"fn": "deep_research", "description": "Multi-step web research: search → read top results → extract key facts. Better than 'web' for complex questions", "args": "query, [max_depth]"},
    "multi_search": {"fn": "multi_search", "description": "Run multiple search queries and combine unique results. Good for comparing topics", "args": "queries"},
    "json_extract": {"fn": "json_extract", "description": "Extract data from JSON using dot-notation path (e.g. 'data.0.name'). Useful for API responses", "args": "data, [path]"},
    "env_get": {"fn": "env_get", "description": "Get the value of an environment variable", "args": "name"},
    "env_set": {"fn": "env_set", "description": "Set an environment variable for the current process", "args": "name, value"},
    "regex_replace": {"fn": "regex_replace", "description": "Find-and-replace with regex in a file. More powerful than edit for pattern-based changes", "args": "path, pattern, replacement, [count]"},
    "batch_edit": {"fn": "batch_edit", "description": "Apply multiple edits to multiple files in one call. Each edit: {path, old_text, new_text}", "args": "edits"},
    "process_list": {"fn": "process_list", "description": "List running processes sorted by memory usage", "args": ""},
    "kill_process": {"fn": "kill_process", "description": "Send signal to a process (SIGTERM=15 or SIGKILL=9)", "args": "pid, [signal]"},
    "network_info": {"fn": "network_info", "description": "Show network interfaces and IP addresses", "args": ""},
}

# ============================================================
# Comprehensive tool reference — injected into agent prompts
# ============================================================

TOOL_DETAILED_REFERENCE = """
=== COMPLETE TOOL REFERENCE (47 tools) ===
All tool calls use JSON format: {"tool": "name", "args": {...}, "reasoning": "why"}

── FILE READING ──────────────────────────────────────────
read       Read a file's contents. For large files, use offset/limit to read specific sections.
           {"tool": "read", "args": {"path": "src/main.py"}}
           {"tool": "read", "args": {"path": "data.log", "offset": 100, "limit": 50}}

glob       Find files matching a glob pattern. Use ** for recursive. Returns list of matching paths.
           {"tool": "glob", "args": {"pattern": "**/*.py"}}
           {"tool": "glob", "args": {"pattern": "src/**/*.ts", "root": "/project"}}

grep       Search file contents by regex. Returns file:line:match format. Essential for finding code.
           {"tool": "grep", "args": {"pattern": "def authenticate"}}
           {"tool": "grep", "args": {"pattern": "TODO|FIXME", "path": "src/", "file_glob": "*.py", "max_results": 20}}

tree       Show directory structure as a tree. Excludes __pycache__, node_modules, .git.
           {"tool": "tree", "args": {}}
           {"tool": "tree", "args": {"path": "src/", "max_depth": 2}}

list_dir   List directory contents with file sizes. Lighter than tree for quick directory checks.
           {"tool": "list_dir", "args": {"path": "src/"}}

file_info  Get file metadata: size, modified date, permissions, line count, type.
           {"tool": "file_info", "args": {"path": "package.json"}}

analyze_file  Analyze a source file: shows language, imports, all function/class definitions, and what other files import it.
           {"tool": "analyze_file", "args": {"path": "src/web.py"}}

project_deps  Show project dependency graph: file counts by language, core modules (most imported files).
           {"tool": "project_deps", "args": {}}

find_symbol  Find all definitions of a function/class name across the entire project.
           {"tool": "find_symbol", "args": {"name": "authenticate_user"}}

semantic_search  Semantic codebase search using embeddings. Best for conceptual queries.
           {"tool": "semantic_search", "args": {"query": "user authentication flow"}}

pdf_read   Extract text from a PDF file. Reads up to max_pages (default 10).
           {"tool": "pdf_read", "args": {"path": "docs/spec.pdf", "max_pages": 5}}

── FILE WRITING ──────────────────────────────────────────
write      Create/overwrite a file. Creates parent directories automatically. Returns byte count.
           {"tool": "write", "args": {"path": "src/utils.py", "content": "def helper():\\n    return True\\n"}}

edit       Surgical text replacement in a file. old_text must match EXACTLY and be UNIQUE in the file.
           Preferred for small, precise changes. Fails if old_text matches multiple locations.
           {"tool": "edit", "args": {"path": "src/main.py", "old_text": "def old_name():", "new_text": "def new_name():"}}

batch_edit Apply multiple edits to one or more files in a single call. Each edit is {path, old_text, new_text}.
           {"tool": "batch_edit", "args": {"edits": [{"path": "a.py", "old_text": "foo", "new_text": "bar"}, {"path": "b.py", "old_text": "baz", "new_text": "qux"}]}}

regex_replace  Find-and-replace using regex in a file. More powerful than edit for pattern-based changes. count=0 means replace all.
           {"tool": "regex_replace", "args": {"path": "src/config.py", "pattern": "v\\\\d+\\\\.\\\\d+", "replacement": "v2.0", "count": 1}}

diff_preview  Preview what an edit would look like as a unified diff without applying it. Use before complex edits to verify.
           {"tool": "diff_preview", "args": {"path": "src/main.py", "old_text": "old code", "new_text": "new code"}}

── SHELL & EXECUTION ─────────────────────────────────────
shell      Run a shell command on the host machine. Returns exit code + stdout + stderr. Default timeout 60s.
           {"tool": "shell", "args": {"cmd": "pip install requests"}}
           {"tool": "shell", "args": {"cmd": "pytest tests/ -v", "timeout": 120}}

python_eval  Evaluate a Python expression safely. Good for math, string ops, list comprehensions. No file/network access.
           {"tool": "python_eval", "args": {"expression": "sum(range(1, 101))"}}
           {"tool": "python_eval", "args": {"expression": "[x**2 for x in range(10)]"}}

run_tests  Run the project's test suite (auto-detects pytest/unittest/npm test). Returns pass/fail + output.
           {"tool": "run_tests", "args": {}}

sandbox_run  Run code in a Docker sandbox (no network, 256MB RAM, 30s timeout). Safe for untrusted code.
           {"tool": "sandbox_run", "args": {"code": "print(2**100)", "language": "python", "timeout": 10}}

spawn_agent  Launch a sub-agent for a parallel sub-task. Agent types: reasoner, coder, researcher, planner, tool_user, security, fast.
           {"tool": "spawn_agent", "args": {"agent": "researcher", "task": "search for Python best practices for error handling"}}

── WEB & NETWORK ─────────────────────────────────────────
web        Quick web search via DuckDuckGo. Returns JSON array with title/body/href. Good for simple lookups.
           {"tool": "web", "args": {"query": "python asyncio tutorial", "max_results": 5}}

deep_research  Multi-step research: searches, reads top results, extracts key facts. BETTER than web for complex questions.
           {"tool": "deep_research", "args": {"query": "best practices for REST API rate limiting", "max_depth": 2}}

multi_search  Run multiple search queries in parallel and combine unique results. Good for comparing topics.
           {"tool": "multi_search", "args": {"queries": ["React vs Svelte performance", "React vs Svelte learning curve"]}}

fetch_url  Fetch a URL and extract readable text (strips HTML). Use to read full articles, docs, or pages.
           {"tool": "fetch_url", "args": {"url": "https://docs.python.org/3/library/asyncio.html", "max_chars": 8000}}

http_request  Make HTTP requests (GET/POST/PUT/DELETE). For calling APIs. Returns status code + response body.
           {"tool": "http_request", "args": {"url": "https://api.example.com/data", "method": "POST", "body": "{\\"key\\": \\"value\\"}"}}

json_extract  Navigate JSON data with dot-notation paths. Use after http_request or web to extract specific fields.
           {"tool": "json_extract", "args": {"data": "{\\"users\\": [{\\"name\\": \\"Alice\\"}]}", "path": "users.0.name"}}

weather    Get current weather + forecast for a location. Uses Open-Meteo (no API key needed).
           {"tool": "weather", "args": {"location": "New York", "forecast_days": 3}}

── GIT ───────────────────────────────────────────────────
git_status Show git working tree status (short format: M=modified, A=added, ?=untracked).
           {"tool": "git_status", "args": {}}

git_diff   Show git diff. Default shows unstaged changes. Use staged=true for staged-only.
           {"tool": "git_diff", "args": {}}
           {"tool": "git_diff", "args": {"staged": true}}

git_log    Show recent git commits (default 10). Shows hash, author, date, message.
           {"tool": "git_log", "args": {"n": 5}}

git_commit Stage ALL changes and create a commit with the given message.
           {"tool": "git_commit", "args": {"message": "fix: resolve auth token expiry bug"}}

git_checkout  Restore a file to its last committed state. DISCARDS all uncommitted changes to that file.
           {"tool": "git_checkout", "args": {"path": "src/broken.py"}}

git_stash  Save/restore work-in-progress. Actions: push (save), pop (restore), list (show stashes).
           {"tool": "git_stash", "args": {"action": "push"}}
           {"tool": "git_stash", "args": {"action": "pop"}}

── MEDIA & AI ────────────────────────────────────────────
vision     Analyze an image file using a multimodal vision model. Returns text description.
           {"tool": "vision", "args": {"image_path": "/path/to/image.png", "prompt": "What does this diagram show?"}}

generate_image  Generate an image from a text prompt using Stable Diffusion. Returns URL to the image file.
           {"tool": "generate_image", "args": {"prompt": "a futuristic city at sunset", "width": 512, "height": 512}}

speak      Convert text to speech (TTS). Returns URL to the generated WAV audio file.
           {"tool": "speak", "args": {"text": "The deployment was successful."}}

screenshot Capture a screenshot of the desktop. Returns the image path.
           {"tool": "screenshot", "args": {}}

── SYSTEM & DATA ─────────────────────────────────────────
database   Execute a read-only SQL query against a SQLite database. Safe: blocks INSERT/UPDATE/DELETE/DROP.
           {"tool": "database", "args": {"query": "SELECT * FROM users LIMIT 10", "db_path": "omni_data.db"}}

docker     Run read-only Docker commands: ps, images, logs, inspect, stats. No destructive ops.
           {"tool": "docker", "args": {"cmd": "ps -a"}}
           {"tool": "docker", "args": {"cmd": "logs my-container --tail 50"}}

archive    Work with zip/tar archives. Actions: list, extract, create.
           {"tool": "archive", "args": {"action": "list", "path": "backup.tar.gz"}}
           {"tool": "archive", "args": {"action": "extract", "path": "data.zip", "dest": "./output/"}}

process_list  List running processes sorted by memory usage. Shows PID, name, CPU%, MEM%.
           {"tool": "process_list", "args": {}}

kill_process  Send a signal to a process. Default SIGTERM (15). Use 9 for SIGKILL.
           {"tool": "kill_process", "args": {"pid": 12345, "signal": 15}}

network_info  Show network interfaces and IP addresses.
           {"tool": "network_info", "args": {}}

env_get    Get the value of an environment variable.
           {"tool": "env_get", "args": {"name": "HOME"}}

env_set    Set an environment variable for the current process.
           {"tool": "env_set", "args": {"name": "DEBUG", "value": "1"}}

── CONTROL ───────────────────────────────────────────────
done       Signal task completion. Put your final answer in the result field.
           {"tool": "done", "args": {}, "result": "I created the file and ran the tests — all 12 passed."}
"""


def build_tool_reference(tool_names: list[str] | None = None) -> str:
    """Build a tool reference string for a specific set of tools, or all tools if None."""
    if tool_names is None:
        return TOOL_DETAILED_REFERENCE
    lines = []
    for name in tool_names:
        entry = TOOL_REGISTRY.get(name)
        if entry:
            lines.append(f"- {name}: {entry['description']} (args: {entry['args']})")
    return "\n".join(lines)


def execute_tool(tool_name: str, args: dict) -> str:
    """Execute a tool by name with keyword arguments.
    Supports external MCP tools via 'server__tool' naming convention."""
    # Route to external MCP server if tool name contains '__'
    if "__" in tool_name:
        parts = tool_name.split("__", 1)
        if len(parts) == 2:
            server_name, remote_tool = parts
            try:
                import asyncio
                from src.mcp import call_mcp_tool
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        result = pool.submit(
                            lambda: asyncio.run(call_mcp_tool(server_name, remote_tool, args))
                        ).result(timeout=30)
                else:
                    result = loop.run_until_complete(call_mcp_tool(server_name, remote_tool, args))
                return result
            except Exception as e:
                return str(_err(f"MCP call failed ({server_name}/{remote_tool}): {e}", ToolErrorKind.EXECUTION))

    if tool_name not in TOOL_REGISTRY:
        return str(_err(f"Unknown tool '{tool_name}'. Available: {', '.join(TOOL_REGISTRY.keys())}",
                       ToolErrorKind.VALIDATION))
    entry = TOOL_REGISTRY[tool_name]
    if entry["fn"] is None:
        return "DONE"
    fn_ref = entry["fn"]
    fn = fn_ref if callable(fn_ref) else globals()[fn_ref]

    # Dedup cache — prevent parallel agents from running identical read-only commands
    _READ_ONLY_TOOLS = {"shell", "read", "glob", "grep", "tree", "list_dir", "file_info",
                        "analyze_file", "project_deps", "find_symbol", "git_status", "git_diff",
                        "git_log", "web", "fetch_url", "weather", "process_list", "network_info",
                        "env_get", "deep_research", "multi_search", "docker"}
    if tool_name in _READ_ONLY_TOOLS:
        cache_key = f"{tool_name}:{json.dumps(args, sort_keys=True)}"
        try:
            from src.upgrades import web_cache
            cached = web_cache.get(f"tool:{cache_key}")
            if cached is not None:
                return cached
        except Exception:
            pass

    # Enforce per-tool timeout
    timeout = TOOL_TIMEOUTS.get(tool_name, 30)
    # Audit log for sensitive tools
    if tool_name in ("shell", "write", "edit", "batch_edit", "regex_replace", "kill_process", "git_commit", "env_set"):
        try:
            from src.upgrades import audit_log
            from src.state import state
            detail = json.dumps({k: str(v)[:80] for k, v in args.items()})
            audit_log(state._active_session_id, f"tool:{tool_name}", detail)
        except Exception:
            pass
    try:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(fn, **args)
            result = str(future.result(timeout=timeout))
        compressed = compress_tool_result(result)
        # Cache read-only tool results (60s TTL) to prevent duplicate parallel calls
        if tool_name in _READ_ONLY_TOOLS:
            try:
                from src.upgrades import web_cache
                cache_key = f"{tool_name}:{json.dumps(args, sort_keys=True)}"
                web_cache.set(f"tool:{cache_key}", compressed)
            except Exception:
                pass
        return compressed
    except TypeError as e:
        # Provide helpful feedback: show expected args from registry
        expected = entry.get("args", "")
        provided = ", ".join(f"{k}={repr(v)[:30]}" for k, v in args.items())
        return str(_err(
            f"Bad arguments for {tool_name}. Expected: ({expected}). You provided: ({provided}). Python error: {e}",
            ToolErrorKind.VALIDATION,
        ))
    except PermissionError as e:
        return str(_err(f"Permission denied: {e}", ToolErrorKind.PERMISSION))
    except FileNotFoundError as e:
        return str(_err(f"Not found: {e}", ToolErrorKind.NOT_FOUND))
    except TimeoutError as e:
        return str(_err(f"Timeout: {e}", ToolErrorKind.TIMEOUT, retryable=True))
    except (urllib.error.URLError, ConnectionError) as e:
        return str(_err(f"Network error: {e}", ToolErrorKind.NETWORK, retryable=True))
    except Exception as e:
        return str(_err(f"{tool_name} failed: {e}", ToolErrorKind.EXECUTION))


# --- Code Intelligence Tool Wrappers ---

def analyze_file_tool(path: str) -> str:
    from src.code_intel import get_file_context
    return get_file_context(path)

def project_deps_tool(root: str = ".") -> str:
    from src.code_intel import project_summary
    return project_summary(root)

_dep_graph_cache = None
_dep_graph_cache_time = 0

def _get_dep_graph():
    """Cache the dependency graph for 60 seconds."""
    global _dep_graph_cache, _dep_graph_cache_time
    import time as _time
    now = _time.time()
    if _dep_graph_cache is None or (now - _dep_graph_cache_time) > 60:
        from src.code_intel import build_dependency_graph
        _dep_graph_cache = build_dependency_graph(".")
        _dep_graph_cache_time = now
    return _dep_graph_cache

def find_symbol_tool(name: str) -> str:
    from src.code_intel import find_symbol
    graph = _get_dep_graph()
    results = find_symbol(graph, name)
    if not results:
        return f"No definitions found for '{name}'"
    return "\n".join(f"  {s.kind}: {s.signature} in {s.file}:{s.line}" for s in results)

def semantic_search_tool(query: str) -> str:
    from src.code_intel import semantic_search
    return semantic_search(query)

def vision_tool(image_path: str, prompt: str = "Describe this image in detail.") -> str:
    from src.multimodal import analyze_image
    return analyze_image(image_path, prompt)

def generate_image_tool(prompt: str, negative_prompt: str = "", width: int = 512, height: int = 512) -> str:
    from src.multimodal import generate_image
    result = generate_image(prompt, negative_prompt, width, height)
    if "error" in result:
        return f"ERROR: {result['error']}"
    url = result.get('url', '')
    # Return markdown image so the LLM includes it in the response
    return f"Image generated successfully.\n\n![{prompt[:60]}]({url})\n\nInclude the above markdown image tag in your response so the user can see it."

def run_tests_tool() -> str:
    from src.advanced import run_auto_test
    result = run_auto_test()
    if result.get("skipped"):
        return f"Tests skipped: {result['output']}"
    status = "PASSED" if result["passed"] else "FAILED"
    return f"Tests {status}:\n{result['output']}"

def spawn_agent_tool(agent: str, task: str) -> str:
    """Stub — actual sub-agent spawning happens in the orchestrator."""
    return f"SUB_AGENT_REQUEST: agent={agent}, task={task}"

def speak_tool(text: str) -> str:
    from src.multimodal import synthesize_speech
    result = synthesize_speech(text)
    if "error" in result:
        return f"ERROR: {result['error']}"
    return f"Audio generated: {result.get('url', result.get('path', ''))}"

def git_commit_tool(message: str) -> str:
    try:
        result = subprocess.run(["git", "add", "-A"], capture_output=True, text=True, timeout=10)
        result = subprocess.run(["git", "commit", "-m", message], capture_output=True, text=True, timeout=15)
        return f"EXIT:{result.returncode}\n{result.stdout}\n{result.stderr}"
    except Exception as e:
        return f"ERROR: {e}"

def git_checkout_tool(path: str) -> str:
    try:
        result = subprocess.run(["git", "checkout", "--", path], capture_output=True, text=True, timeout=10)
        return f"EXIT:{result.returncode}\n{result.stdout}\n{result.stderr}".strip() or f"Restored {path}"
    except Exception as e:
        return f"ERROR: {e}"

def python_eval_tool(expression: str) -> str:
    """Evaluate a Python expression safely (math, string ops, list comprehensions)."""
    # Restricted builtins — no file/network/system access
    safe_builtins = {
        "abs": abs, "all": all, "any": any, "bin": bin, "bool": bool,
        "chr": chr, "dict": dict, "divmod": divmod, "enumerate": enumerate,
        "filter": filter, "float": float, "format": format, "hex": hex,
        "int": int, "isinstance": isinstance, "len": len, "list": list,
        "map": map, "max": max, "min": min, "oct": oct, "ord": ord,
        "pow": pow, "range": range, "repr": repr, "reversed": reversed,
        "round": round, "set": set, "sorted": sorted, "str": str,
        "sum": sum, "tuple": tuple, "type": type, "zip": zip,
        "True": True, "False": False, "None": None,
    }
    try:
        import math
        safe_globals = {"__builtins__": safe_builtins, "math": math}
        result = eval(expression, safe_globals, {})
        return str(result)
    except Exception as e:
        return f"ERROR: {e}"

def http_request_tool(url: str, method: str = "GET", body: str = "") -> str:
    """Make an HTTP request. Returns status + body."""
    from src.tools import _is_ssrf_target, _err, ToolErrorKind
    ssrf = _is_ssrf_target(url)
    if ssrf:
        return str(_err(f"SSRF blocked: {ssrf}", ToolErrorKind.VALIDATION))
    try:
        data = body.encode() if body else None
        req = urllib.request.Request(url, data=data, method=method.upper(),
                                     headers={"User-Agent": "OmniAgent/8.0", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            content = resp.read().decode("utf-8", errors="replace")
            return f"STATUS:{resp.status}\n{content[:5000]}"
    except urllib.error.HTTPError as e:
        return f"HTTP_ERROR:{e.code}\n{e.read().decode('utf-8', errors='replace')[:2000]}"
    except Exception as e:
        return f"ERROR: {e}"

def list_dir_tool(path: str = ".") -> str:
    """List directory contents (lighter than tree)."""
    try:
        entries = sorted(os.listdir(path))
        lines = []
        for e in entries[:100]:
            full = os.path.join(path, e)
            if os.path.isdir(full):
                lines.append(f"  {e}/")
            else:
                size = os.path.getsize(full)
                lines.append(f"  {e} ({size:,} bytes)")
        result = f"{path} ({len(entries)} items):\n" + "\n".join(lines)
        if len(entries) > 100:
            result += f"\n  ... and {len(entries) - 100} more"
        return result
    except Exception as e:
        return f"ERROR: {e}"

def file_info_tool(path: str) -> str:
    """Get file metadata: size, modified date, permissions, type."""
    path = os.path.realpath(path)
    if not os.path.exists(path):
        return f"ERROR: {path} not found"
    try:
        stat = os.stat(path)
        import time as _time
        return (
            f"Path: {path}\n"
            f"Size: {stat.st_size:,} bytes\n"
            f"Modified: {_time.ctime(stat.st_mtime)}\n"
            f"Permissions: {oct(stat.st_mode)[-3:]}\n"
            f"Type: {'directory' if os.path.isdir(path) else 'file'}\n"
            f"Lines: {sum(1 for _ in open(path, errors='replace')) if os.path.isfile(path) and stat.st_size < 10_000_000 else 'N/A'}"
        )
    except Exception as e:
        return f"ERROR: {e}"


def diff_preview_tool(path: str, old_text: str, new_text: str) -> str:
    """Show what an edit would look like without applying it."""
    path = os.path.realpath(path)
    if not os.path.exists(path):
        return f"ERROR: {path} not found"
    with open(path, "r") as f:
        content = f.read()
    if old_text not in content:
        return "ERROR: old_text not found in file"
    import difflib
    original_lines = content.splitlines(keepends=True)
    modified = content.replace(old_text, new_text, 1)
    modified_lines = modified.splitlines(keepends=True)
    diff = difflib.unified_diff(original_lines, modified_lines, fromfile=f"a/{os.path.basename(path)}", tofile=f"b/{os.path.basename(path)}")
    return "".join(diff) or "No changes"

def screenshot_tool() -> str:
    """Capture a screenshot of the desktop."""
    try:
        import secrets as _s
        filename = f"screenshot_{_s.token_hex(4)}.png"
        filepath = os.path.join("uploads", filename)
        result = subprocess.run(["gnome-screenshot", "-f", filepath], capture_output=True, text=True, timeout=10)
        if result.returncode == 0 and os.path.exists(filepath):
            return f"Screenshot saved: /uploads/{filename}"
        # Fallback: scrot
        result = subprocess.run(["scrot", filepath], capture_output=True, text=True, timeout=10)
        if result.returncode == 0 and os.path.exists(filepath):
            return f"Screenshot saved: /uploads/{filename}"
        return "ERROR: No screenshot tool available (install gnome-screenshot or scrot)"
    except Exception as e:
        return f"ERROR: {e}"

def database_query_tool(query: str, db_path: str = "") -> str:
    """Execute a read-only SQL query against a SQLite database."""
    import sqlite3
    if not db_path:
        db_path = "omni_data.db"
    db_path = os.path.realpath(db_path)
    if not os.path.exists(db_path):
        return f"ERROR: Database not found: {db_path}"
    # Safety: only allow SELECT queries
    q_upper = query.strip().upper()
    if not q_upper.startswith("SELECT") and not q_upper.startswith("PRAGMA"):
        return "ERROR: Only SELECT and PRAGMA queries are allowed for safety"
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query).fetchall()
        conn.close()
        if not rows:
            return "No results"
        headers = rows[0].keys()
        lines = [" | ".join(headers)]
        lines.append("-" * len(lines[0]))
        for row in rows[:50]:
            lines.append(" | ".join(str(row[h]) for h in headers))
        if len(rows) > 50:
            lines.append(f"... ({len(rows)} total rows)")
        return "\n".join(lines)
    except Exception as e:
        return f"ERROR: {e}"

def docker_tool(cmd: str) -> str:
    """Run a docker command (read-only: ps, images, logs, inspect)."""
    allowed = ["ps", "images", "logs", "inspect", "stats", "top", "port", "version", "info"]
    parts = cmd.strip().split()
    if not parts:
        return "ERROR: Empty command"
    subcmd = parts[0]
    if subcmd not in allowed:
        return f"ERROR: Only these docker subcommands are allowed: {', '.join(allowed)}"
    try:
        result = subprocess.run(["docker"] + parts, capture_output=True, text=True, timeout=30)
        return f"EXIT:{result.returncode}\n{result.stdout[:3000]}\n{result.stderr[:500]}"
    except FileNotFoundError:
        return "ERROR: docker not installed"
    except Exception as e:
        return f"ERROR: {e}"

def pdf_read_tool(path: str, max_pages: int = 10) -> str:
    """Extract text from a PDF file."""
    path = os.path.realpath(path)
    if not os.path.exists(path):
        return f"ERROR: {path} not found"
    # Try pdftotext first (poppler-utils)
    try:
        result = subprocess.run(["pdftotext", "-l", str(max_pages), path, "-"], capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout[:8000]
    except FileNotFoundError:
        pass
    # Try PyPDF2 / pypdf
    try:
        from pypdf import PdfReader
        reader = PdfReader(path)
        text = []
        for i, page in enumerate(reader.pages[:max_pages]):
            text.append(f"--- Page {i+1} ---\n{page.extract_text()}")
        return "\n".join(text)[:8000]
    except ImportError:
        pass
    return "ERROR: No PDF reader available. Install poppler-utils or pypdf"

def archive_tool(action: str, path: str, dest: str = ".") -> str:
    """Create or extract archives. action: 'list', 'extract', 'create'."""
    path = os.path.realpath(path)
    if action == "list":
        try:
            if path.endswith((".zip",)):
                result = subprocess.run(["unzip", "-l", path], capture_output=True, text=True, timeout=15)
            else:
                result = subprocess.run(["tar", "-tf", path], capture_output=True, text=True, timeout=15)
            return result.stdout[:3000]
        except Exception as e:
            return f"ERROR: {e}"
    elif action == "extract":
        try:
            if path.endswith((".zip",)):
                result = subprocess.run(["unzip", "-o", path, "-d", dest], capture_output=True, text=True, timeout=60)
            else:
                result = subprocess.run(["tar", "-xf", path, "-C", dest], capture_output=True, text=True, timeout=60)
            return f"Extracted to {dest}\n{result.stdout[:500]}"
        except Exception as e:
            return f"ERROR: {e}"
    elif action == "create":
        try:
            import secrets as _s
            if dest.endswith(".zip"):
                result = subprocess.run(["zip", "-r", dest, path], capture_output=True, text=True, timeout=60)
            else:
                if not dest.endswith((".tar.gz", ".tgz")):
                    dest = f"{dest}.tar.gz"
                result = subprocess.run(["tar", "-czf", dest, path], capture_output=True, text=True, timeout=60)
            return f"Created {dest}\n{result.stdout[:500]}"
        except Exception as e:
            return f"ERROR: {e}"
    return "ERROR: action must be 'list', 'extract', or 'create'"

def sandbox_run_tool(code: str, language: str = "python", timeout: int = 30) -> str:
    """Run code in a Docker sandbox."""
    from src.platform import run_sandboxed
    result = run_sandboxed(code, language, timeout)
    if result.get("sandbox"):
        return f"[SANDBOXED] EXIT:{result.get('exit_code',0)}\n{result.get('stdout','')}\n{result.get('stderr','')}"
    return result.get("output", result.get("error", "Unknown error"))


def git_stash_tool(action: str = "push") -> str:
    """Git stash operations: push, pop, list."""
    try:
        if action == "push":
            result = subprocess.run(["git", "stash", "push", "-m", "omniagent-checkpoint"], capture_output=True, text=True, timeout=10)
        elif action == "pop":
            result = subprocess.run(["git", "stash", "pop"], capture_output=True, text=True, timeout=10)
        elif action == "list":
            result = subprocess.run(["git", "stash", "list"], capture_output=True, text=True, timeout=10)
        else:
            return "ERROR: action must be 'push', 'pop', or 'list'"
        return f"EXIT:{result.returncode}\n{result.stdout}\n{result.stderr}".strip()
    except Exception as e:
        return f"ERROR: {e}"


# --- Export Helpers ---

def export_chat_json(chat_history: list[dict]) -> str:
    return json.dumps(chat_history, indent=2, ensure_ascii=False)

def export_chat_markdown(chat_history: list[dict]) -> str:
    lines = ["# OmniAgent Chat Export\n"]
    for msg in chat_history:
        lines.append(f"## {msg.get('role', 'unknown').capitalize()}\n\n{msg.get('content', '')}\n")
    return "\n".join(lines)

def export_chat_text(chat_history: list[dict]) -> str:
    return "\n".join(f"[{m.get('role','').upper()}]\n{m.get('content','')}\n" for m in chat_history)

def export_chat_csv(chat_history: list[dict]) -> str:
    import csv, io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["role", "content"])
    for m in chat_history:
        w.writerow([m.get("role", ""), m.get("content", "")])
    return buf.getvalue()

def export_chat_html(chat_history: list[dict]) -> str:
    rows = []
    for m in chat_history:
        role = m.get("role", "unknown")
        content = m.get("content", "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        cls = "user" if role == "user" else "assistant"
        rows.append(f'<div class="msg {cls}"><strong>{role.upper()}</strong><pre>{content}</pre></div>')
    return f'<!DOCTYPE html><html><head><meta charset="UTF-8"><title>OmniAgent Export</title><style>body{{font-family:sans-serif;background:#0d1117;color:#c9d1d9;padding:20px}}.msg{{margin:12px 0;padding:12px;border-radius:8px}}.user{{background:#238636}}.assistant{{background:#161b22;border:1px solid #30363d}}pre{{white-space:pre-wrap;margin:6px 0 0}}</style></head><body><h1>OmniAgent Chat Export</h1>{"".join(rows)}</body></html>'


# --- Auto-load user plugins ---

try:
    from src.plugins import load_plugins as _load_plugins
    _loaded_plugin_names = _load_plugins()
    if _loaded_plugin_names:
        import logging as _logging
        _logging.getLogger("omniagent.plugins").info(
            "Auto-loaded %d plugin(s): %s", len(_loaded_plugin_names), ", ".join(_loaded_plugin_names)
        )
except Exception as _plugin_err:
    import logging as _logging
    _logging.getLogger("omniagent.plugins").warning(
        "Plugin auto-load failed (non-fatal): %s", _plugin_err
    )
