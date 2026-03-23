"""
Experimental features — A/B testing, fine-tuning pipeline, metrics dashboard,
plugin marketplace, conversation fork tree.
"""
import os
import json
import time
import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger("experiments")


# ============================================================
# 1. Model A/B Testing
# ============================================================

async def compare_models(prompt: str, model_a: str, model_b: str, context: str = "") -> dict:
    """Run the same prompt through two models and return both responses."""
    from src.config import CLIENT
    loop = asyncio.get_event_loop()

    messages = [{"role": "user", "content": prompt}]
    if context:
        messages.insert(0, {"role": "system", "content": context})

    async def run_model(model: str) -> dict:
        start = time.time()
        try:
            response = await loop.run_in_executor(
                None,
                lambda: CLIENT.chat.completions.create(model=model, messages=messages),
            )
            elapsed = time.time() - start
            reply = response.choices[0].message.content
            tokens = getattr(response.usage, 'completion_tokens', 0) if response.usage else 0
            return {
                "model": model,
                "reply": reply,
                "tokens": tokens,
                "latency": round(elapsed, 1),
                "speed": round(tokens / elapsed, 1) if elapsed > 0 else 0,
            }
        except Exception as e:
            return {"model": model, "reply": "", "error": str(e), "latency": round(time.time() - start, 1)}

    result_a, result_b = await asyncio.gather(run_model(model_a), run_model(model_b))
    return {"model_a": result_a, "model_b": result_b}


# ============================================================
# 2. Fine-Tuning Pipeline (scaffold)
# ============================================================

FINETUNE_DIR = Path(__file__).resolve().parent.parent / "finetune_data"
FINETUNE_DIR.mkdir(exist_ok=True)

def collect_training_sample(user_message: str, good_response: str, bad_response: str = "",
                           correction: str = ""):
    """Collect a training sample from user feedback for future fine-tuning."""
    sample = {
        "timestamp": datetime.now().isoformat(),
        "prompt": user_message,
        "chosen": good_response[:2000],
    }
    if bad_response:
        sample["rejected"] = bad_response[:2000]
    if correction:
        sample["correction"] = correction[:1000]

    # Append to JSONL file
    output_file = FINETUNE_DIR / "training_samples.jsonl"
    with open(output_file, "a") as f:
        f.write(json.dumps(sample) + "\n")
    return True


def get_training_stats() -> dict:
    """Get stats about collected training data."""
    output_file = FINETUNE_DIR / "training_samples.jsonl"
    if not output_file.exists():
        return {"samples": 0, "size_kb": 0}
    lines = output_file.read_text().strip().split("\n")
    size = output_file.stat().st_size
    return {
        "samples": len(lines),
        "size_kb": round(size / 1024, 1),
        "path": str(output_file),
    }


def export_training_data(format: str = "alpaca") -> str:
    """Export collected samples in a format suitable for fine-tuning.
    Formats: alpaca (instruction/input/output), sharegpt (conversations)."""
    output_file = FINETUNE_DIR / "training_samples.jsonl"
    if not output_file.exists():
        return json.dumps({"error": "No training data collected"})

    samples = []
    for line in output_file.read_text().strip().split("\n"):
        try:
            samples.append(json.loads(line))
        except Exception:
            continue

    if format == "alpaca":
        exported = []
        for s in samples:
            entry = {
                "instruction": s["prompt"],
                "input": "",
                "output": s["chosen"],
            }
            exported.append(entry)
        export_path = FINETUNE_DIR / "alpaca_export.json"
        export_path.write_text(json.dumps(exported, indent=2))
        return json.dumps({"ok": True, "path": str(export_path), "samples": len(exported)})

    elif format == "sharegpt":
        exported = []
        for s in samples:
            entry = {
                "conversations": [
                    {"from": "human", "value": s["prompt"]},
                    {"from": "gpt", "value": s["chosen"]},
                ]
            }
            exported.append(entry)
        export_path = FINETUNE_DIR / "sharegpt_export.json"
        export_path.write_text(json.dumps(exported, indent=2))
        return json.dumps({"ok": True, "path": str(export_path), "samples": len(exported)})

    return json.dumps({"error": f"Unknown format: {format}"})


# ============================================================
# 3. Metrics Dashboard Data
# ============================================================

_metrics_history: list[dict] = []
_MAX_HISTORY = 1440  # 24 hours at 1/min

def record_metrics_snapshot():
    """Record a point-in-time metrics snapshot for the dashboard."""
    try:
        from src.state import state
        snapshot = {
            "timestamp": datetime.now().isoformat(),
            "gpu": state.gpu_telemetry,
            "tasks": state.tasks_completed,
            "llm_calls": state.total_llm_calls,
            "sessions": len(state._sessions),
        }
        # Parse GPU temp if available
        try:
            gpu_str = state.gpu_telemetry
            if "°C" in gpu_str:
                temp = int(gpu_str.split("°C")[0].strip().split()[-1])
                snapshot["gpu_temp"] = temp
            if "MB" in gpu_str:
                vram = int(gpu_str.split("MB")[0].strip().split()[-1])
                snapshot["vram_mb"] = vram
        except Exception:
            pass

        _metrics_history.append(snapshot)
        if len(_metrics_history) > _MAX_HISTORY:
            _metrics_history.pop(0)
    except Exception:
        pass


def get_metrics_history(hours: int = 1) -> list[dict]:
    """Get metrics history for the dashboard."""
    cutoff = datetime.now() - timedelta(hours=hours)
    return [m for m in _metrics_history if m.get("timestamp", "") >= cutoff.isoformat()]


# ============================================================
# 4. Plugin Marketplace (scaffold)
# ============================================================

PLUGIN_REGISTRY_URL = os.environ.get("PLUGIN_REGISTRY_URL",
    "https://raw.githubusercontent.com/omniagent/plugins/main/registry.json")

def fetch_plugin_registry() -> list[dict]:
    """Fetch available plugins from the registry."""
    try:
        import urllib.request
        req = urllib.request.Request(PLUGIN_REGISTRY_URL, headers={"User-Agent": "OmniAgent/8.2"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode()).get("plugins", [])
    except Exception:
        return []


def install_plugin(plugin_url: str, name: str) -> str:
    """Download and install a plugin from a URL."""
    plugin_dir = Path(os.path.expanduser("~/.omniagent/tools"))
    plugin_dir.mkdir(parents=True, exist_ok=True)
    try:
        import urllib.request
        dest = plugin_dir / f"{name}.py"
        urllib.request.urlretrieve(plugin_url, str(dest))
        return f"Installed {name} to {dest}"
    except Exception as e:
        return f"Failed: {e}"


# ============================================================
# 5. Conversation Fork Tree
# ============================================================

def get_conversation_tree(session_id: str) -> dict:
    """Build a tree structure of conversation branches."""
    from src.persistence import get_db, decrypt
    conn = get_db()
    rows = conn.execute(
        "SELECT id, role, content, created_at FROM chat_messages WHERE session_id = ? ORDER BY id",
        (session_id,),
    ).fetchall()
    conn.close()

    # Build linear tree (branches would need a parent_id column — future enhancement)
    nodes = []
    for i, row in enumerate(rows):
        try:
            content = decrypt(row[2])[:100]
        except Exception:
            content = "[encrypted]"
        nodes.append({
            "id": row[0],
            "index": i,
            "role": row[1],
            "preview": content,
            "created_at": row[3],
        })

    return {"session_id": session_id, "nodes": nodes, "total": len(nodes)}
