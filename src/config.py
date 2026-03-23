import os
from openai import OpenAI

os.environ["OLLAMA_MAX_LOADED_MODELS"] = "1"

# Ollama context window — 32K tokens for code-aware models
OLLAMA_NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "32768"))

# Primary client — Ollama for large models
CLIENT = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")

# BitNet client — lightweight 1.58-bit model for fast parallel tasks
# Runs on CPU via bitnet.cpp llama-server on port 8081
BITNET_CLIENT = OpenAI(base_url="http://localhost:8081/v1", api_key="bitnet")
BITNET_MODEL = "bitnet-2b"
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

# dolphin3:8b is uncensored — used as the general/orchestrator model so it
# never refuses to route or synthesize any task. Individual specialist models
# (coding, reasoning) have their own guardrails.
EXPERTS = {
    "general": "dolphin3:8b",
    "reasoning": "deepseek-r1:8b",
    "coding": "qwen2.5-coder:7b",
    "security": "dolphin3:8b",
    "fast": "bitnet-2b",
}

SYSTEM_PROMPT = """
You are an Autonomous Sub-Agent under the OMNI-SUPERVISOR.
1. Always check 'plan.md' before acting.
2. Use 'read' to see files and 'write' to modify them.
3. If a task is finished, set your status to 'SUCCESS' so the Supervisor can archive the plan.
"""

OLLAMA_BIN = "/usr/local/bin/ollama"
