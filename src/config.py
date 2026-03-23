import os
from pathlib import Path
from openai import OpenAI

# Single source of truth — read from VERSION file at project root
_version_file = Path(__file__).resolve().parent.parent / "VERSION"
VERSION = _version_file.read_text().strip() if _version_file.exists() else "0.0.0"

os.environ["OLLAMA_MAX_LOADED_MODELS"] = "1"

# Ollama context window — 32K tokens for code-aware models
OLLAMA_NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "32768"))
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY", "ollama")

# Primary client — Ollama for large models
CLIENT = OpenAI(base_url=OLLAMA_BASE_URL, api_key=OLLAMA_API_KEY)

# Optional remote MiniMax provider. This stays opt-in and only becomes active
# when an API key is configured or when a MiniMax model is selected explicitly.
MINIMAX_BASE_URL = os.environ.get("MINIMAX_BASE_URL", "https://api.minimax.io/v1")
MINIMAX_API_KEY = os.environ.get("MINIMAX_API_KEY", "")
MINIMAX_MODEL = os.environ.get("MINIMAX_MODEL", "MiniMax-M2.7")
MINIMAX_FALLBACK_ROLES = {
    role.strip().lower()
    for role in os.environ.get("MINIMAX_FALLBACK_ROLES", "").split(",")
    if role.strip()
}
MINIMAX_CLIENT = OpenAI(base_url=MINIMAX_BASE_URL, api_key=MINIMAX_API_KEY) if MINIMAX_API_KEY else None

# BitNet client — lightweight 1.58-bit model for fast parallel tasks
# Runs on CPU via bitnet.cpp llama-server on port 8081
BITNET_CLIENT = OpenAI(base_url="http://localhost:8081/v1", api_key="bitnet")
BITNET_MODEL = os.environ.get("BITNET_MODEL", "bitnet-2b")
BITNET_ENABLED = False  # Auto-detected below

# Auto-detect running BitNet server on import
try:
    import urllib.request as _ur
    _port = int(os.environ.get("BITNET_PORT", "8081"))
    with _ur.urlopen(f"http://localhost:{_port}/v1/models", timeout=1) as _resp:
        if _resp.status == 200:
            BITNET_ENABLED = True
except Exception:
    pass

SESSION_FILE = "omni_session.json"
PLAN_FILE = "plan.md"
MEMORY_FILE = "memory.md"

# qwen3:8b is the default general/orchestrator model for routing, planning,
# and synthesis. Individual specialist models (coding, reasoning) keep their
# own assignments and fallback chains.
EXPERTS = {
    "general": os.environ.get("GENERAL_MODEL", "qwen3:8b"),
    "reasoning": os.environ.get("REASONING_MODEL", "deepseek-r1:8b"),
    "coding": os.environ.get("CODING_MODEL", "qwen2.5-coder:7b"),
    "security": os.environ.get("SECURITY_MODEL", "dolphin3:8b"),
    "fast": BITNET_MODEL,
}

SYSTEM_PROMPT = """
You are an Autonomous Sub-Agent under the OMNI-SUPERVISOR.
1. Always check 'plan.md' before acting.
2. Use 'read' to see files and 'write' to modify them.
3. If a task is finished, set your status to 'SUCCESS' so the Supervisor can archive the plan.
"""

OLLAMA_BIN = "/usr/local/bin/ollama"


def is_minimax_model(model: str | None) -> bool:
    """True when a model name should be routed to the MiniMax OpenAI-compatible API."""
    return bool(model and model.strip().lower().startswith("minimax-"))


def get_client_for_model(model: str):
    """Resolve the OpenAI-compatible client for a given model name."""
    if is_minimax_model(model) and MINIMAX_CLIENT is not None:
        return MINIMAX_CLIENT
    return CLIENT


def get_model_for_role(model_key: str, override: str | None = None) -> str:
    """Resolve the configured model for a specialist role."""
    if override and override != "auto":
        return override
    return EXPERTS.get(model_key, EXPERTS["general"])


def get_minimax_fallback_model(model_key: str | None, current_model: str = "") -> str | None:
    """Return the configured MiniMax fallback model for a role, if enabled."""
    if MINIMAX_CLIENT is None or not model_key or is_minimax_model(current_model):
        return None
    normalized = model_key.strip().lower()
    if "all" not in MINIMAX_FALLBACK_ROLES and normalized not in MINIMAX_FALLBACK_ROLES:
        return None
    return MINIMAX_MODEL


def create_chat_completion(*, model: str, messages: list[dict], model_key: str | None = None, **kwargs):
    """Run a chat completion against the correct provider with optional MiniMax fallback."""
    client = get_client_for_model(model)
    try:
        return client.chat.completions.create(model=model, messages=messages, **kwargs), model
    except Exception:
        fallback_model = get_minimax_fallback_model(model_key, current_model=model)
        if not fallback_model:
            raise
        fallback_client = get_client_for_model(fallback_model)
        if fallback_client is client and fallback_model == model:
            raise
        return fallback_client.chat.completions.create(
            model=fallback_model,
            messages=messages,
            **kwargs,
        ), fallback_model
