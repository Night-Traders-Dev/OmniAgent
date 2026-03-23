"""
OmniAgent v8.0 - Entry Point
Starts all services: FastAPI server, GPU monitor, BitNet (if available),
Cloudflare tunnel (optional), and rolling log with metrics.
"""
import subprocess
import signal
import sys
import os
import time
import threading
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from datetime import datetime
import uvicorn
from src.web import app


# ============================================================
# Rolling Log Setup
# ============================================================

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

# Main application log — 5MB per file, 5 backups = 25MB max
log_formatter = logging.Formatter(
    "[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
file_handler = RotatingFileHandler(
    LOG_DIR / "omniagent.log",
    maxBytes=5 * 1024 * 1024,  # 5MB
    backupCount=5,
    encoding="utf-8",
)
file_handler.setFormatter(log_formatter)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(logging.Formatter(
    "%(asctime)s %(levelname)s: %(message)s", datefmt="%H:%M:%S",
))

logger = logging.getLogger("omniagent")
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)
logger.addHandler(console_handler)

# Also capture uvicorn access logs into the rolling log
uvicorn_logger = logging.getLogger("uvicorn.access")
uvicorn_logger.addHandler(file_handler)


BITNET_PROCESS = None
TUNNEL_PROCESS = None
CTRL_C_COUNT = 0
TUNNEL_URL = None  # Set when tunnel connects

# ============================================================
# Pairing Code + ntfy.sh for Remote Discovery
# ============================================================
# The server generates a short pairing code on startup.
# When the tunnel URL is obtained, it pushes the URL to ntfy.sh
# using the pairing code as the topic. The Android app enters the
# same code and fetches the URL from ntfy.sh. No LAN needed.

import hashlib

def _generate_pairing_code() -> str:
    """Generate a deterministic pairing code from machine identity.
    Same machine + user always gets the same code, so it's memorable."""
    import platform
    identity = f"{platform.node()}-{os.environ.get('USER', 'omni')}"
    h = hashlib.sha256(identity.encode()).hexdigest()[:6]
    return h

# Allow override via env var
PAIRING_CODE = os.environ.get("OMNI_PAIRING_CODE", _generate_pairing_code())
NTFY_TOPIC = f"omniagent-{PAIRING_CODE}"
NTFY_URL = "https://ntfy.sh"


def publish_tunnel_url(url: str):
    """Publish the tunnel URL to ntfy.sh so remote clients can find us."""
    global TUNNEL_URL
    TUNNEL_URL = url
    try:
        import urllib.request
        data = url.encode()
        req = urllib.request.Request(
            f"{NTFY_URL}/{NTFY_TOPIC}",
            data=data,
            method="POST",
            headers={
                "Title": "OmniAgent Server",
                "Tags": "robot",
                "Priority": "3",
            },
        )
        urllib.request.urlopen(req, timeout=10)
        logger.info(f"[Pairing] Published tunnel URL to ntfy.sh/{NTFY_TOPIC}")
        logger.info(f"[Pairing] Pairing code: {PAIRING_CODE}")
    except Exception as e:
        logger.warning(f"[Pairing] Failed to publish to ntfy.sh: {e}")


def get_cached_tunnel_url_from_ntfy() -> str | None:
    """Fetch the latest tunnel URL from ntfy.sh cache (for the API endpoint)."""
    try:
        import urllib.request
        import json
        req = urllib.request.Request(
            f"{NTFY_URL}/{NTFY_TOPIC}/json?poll=1&since=1h",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            lines = resp.read().decode().strip().split('\n')
        # Get the last message
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                msg = json.loads(line)
                if msg.get("message", "").startswith("https://"):
                    return msg["message"]
            except json.JSONDecodeError:
                continue
    except Exception:
        pass
    return None


# ============================================================
# Metrics Logger — periodic stats written to log
# ============================================================

def metrics_logger():
    """Background thread that logs metrics every 60 seconds."""
    from src.state import state
    while True:
        time.sleep(60)
        try:
            snap = state.tracking_snapshot()
            active_sessions = len(state.list_sessions())
            logger.info(
                "METRICS | "
                f"tasks={snap.get('tasks_completed', 0)} "
                f"llm_calls={snap.get('total_llm_calls', 0)} "
                f"sessions={active_sessions} "
                f"msgs={snap.get('session_messages', 0)} "
                f"cmds={snap.get('commands_run', 0)} "
                f"tok_in={snap.get('tokens_in', 0)} "
                f"tok_out={snap.get('tokens_out', 0)} "
                f"gpu={snap.get('gpu', '--')} "
                f"status={snap.get('status', 'Idle')}"
            )
        except Exception as e:
            logger.debug(f"Metrics collection error: {e}")


# ============================================================
# BitNet
# ============================================================

def start_bitnet():
    global BITNET_PROCESS
    import src.config as config
    bitnet_dir = Path(__file__).parent / "bitnet"
    server_bin = bitnet_dir / "llama-server"
    model_path = bitnet_dir / "model" / "ggml-model-i2_s.gguf"
    port = int(os.environ.get("BITNET_PORT", "8081"))

    # Check if BitNet is already running (from a previous launch or external start)
    try:
        import urllib.request as _ur
        with _ur.urlopen(f"http://localhost:{port}/v1/models", timeout=2) as resp:
            if resp.status == 200:
                config.BITNET_ENABLED = True
                logger.info(f"[BitNet] Already running on port {port} — enabled")
                return
    except Exception:
        pass

    if not server_bin.exists():
        logger.info("[BitNet] Server binary not found, skipping")
        return
    if not model_path.exists():
        logger.info("[BitNet] Model not found, skipping")
        return

    threads = int(os.environ.get("BITNET_THREADS", "4"))
    ctx = int(os.environ.get("BITNET_CTX", "2048"))

    logger.info(f"[BitNet] Starting b1.58-2B on port {port} ({threads} threads, ctx={ctx})")
    BITNET_PROCESS = subprocess.Popen(
        [
            str(server_bin), "-m", str(model_path),
            "--host", "0.0.0.0", "--port", str(port),
            "-t", str(threads), "-c", str(ctx),
            "-n", "4096", "--temp", "0.7", "-cb",
        ],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    # Wait a moment for the server to start, then verify
    time.sleep(2)
    try:
        import urllib.request as _ur
        with _ur.urlopen(f"http://localhost:{port}/v1/models", timeout=3) as resp:
            if resp.status == 200:
                config.BITNET_ENABLED = True
                logger.info(f"[BitNet] Server started (PID {BITNET_PROCESS.pid})")
                return
    except Exception:
        pass
    config.BITNET_ENABLED = True  # Assume it'll come up
    logger.info(f"[BitNet] Server launched (PID {BITNET_PROCESS.pid}), waiting for ready")


# ============================================================
# Cloudflare Tunnel
# ============================================================

def start_tunnel():
    """Start a free Cloudflare quick tunnel for internet access."""
    global TUNNEL_PROCESS

    # Find cloudflared binary
    cloudflared = None
    for path in [
        os.path.expanduser("~/.local/bin/cloudflared"),
        "/usr/local/bin/cloudflared",
        "/usr/bin/cloudflared",
    ]:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            cloudflared = path
            break

    if not cloudflared:
        logger.info("[Tunnel] cloudflared not found — running local only")
        logger.info("[Tunnel] Install: curl -sL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o ~/.local/bin/cloudflared && chmod +x ~/.local/bin/cloudflared")
        return

    if os.environ.get("OMNI_NO_TUNNEL", "").lower() in ("1", "true", "yes"):
        logger.info("[Tunnel] Disabled via OMNI_NO_TUNNEL env var")
        return

    logger.info("[Tunnel] Starting Cloudflare quick tunnel...")
    TUNNEL_PROCESS = subprocess.Popen(
        [cloudflared, "tunnel", "--url", "http://localhost:8000"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )

    # Parse output in background to extract the tunnel URL
    def watch_tunnel():
        url_found = False
        for line in iter(TUNNEL_PROCESS.stdout.readline, ""):
            if TUNNEL_PROCESS.poll() is not None:
                break
            line = line.strip()
            if "trycloudflare.com" in line and not url_found:
                import re
                match = re.search(r'(https://[a-z0-9-]+\.trycloudflare\.com)', line)
                if match:
                    url = match.group(1)
                    url_found = True
                    logger.info(f"[Tunnel] PUBLIC URL: {url}")
                    print()
                    print("=" * 56)
                    print(f"  PUBLIC URL:   {url}")
                    print(f"  PAIRING CODE: {PAIRING_CODE}")
                    print("=" * 56)
                    print("  Enter the pairing code in the Android app")
                    print("  to connect from anywhere (no LAN needed).")
                    print()
                    # Save URL to file for other tools to read
                    try:
                        (Path(__file__).parent / ".tunnel_url").write_text(url)
                    except Exception:
                        pass
                    # Publish to ntfy.sh for remote discovery
                    publish_tunnel_url(url)

    thread = threading.Thread(target=watch_tunnel, daemon=True)
    thread.start()


# ============================================================
# Cleanup
# ============================================================

def cleanup():
    global BITNET_PROCESS, TUNNEL_PROCESS
    # Save global counters and session state before exit
    try:
        from src.state import state
        from src.persistence import save_global_counters
        save_global_counters(state.tasks_completed, state.total_llm_calls)
        state.save_session()
        logger.info("[State] Saved global counters and session state")
    except Exception as e:
        logger.warning(f"[State] Failed to save on shutdown: {e}")

    if BITNET_PROCESS and BITNET_PROCESS.poll() is None:
        logger.info(f"[BitNet] Stopping server (PID {BITNET_PROCESS.pid})")
        BITNET_PROCESS.terminate()
        try:
            BITNET_PROCESS.wait(timeout=3)
        except subprocess.TimeoutExpired:
            BITNET_PROCESS.kill()
        BITNET_PROCESS = None

    if TUNNEL_PROCESS and TUNNEL_PROCESS.poll() is None:
        logger.info(f"[Tunnel] Stopping (PID {TUNNEL_PROCESS.pid})")
        TUNNEL_PROCESS.terminate()
        try:
            TUNNEL_PROCESS.wait(timeout=3)
        except subprocess.TimeoutExpired:
            TUNNEL_PROCESS.kill()
        TUNNEL_PROCESS = None
        # Clean up URL file
        try:
            (Path(__file__).parent / ".tunnel_url").unlink(missing_ok=True)
        except Exception:
            pass

    logger.info("Shutdown complete.")


def force_exit(sig, frame):
    global CTRL_C_COUNT
    CTRL_C_COUNT += 1
    if CTRL_C_COUNT == 1:
        print("\nShutting down (press Ctrl+C again to force)...")
        cleanup()
        os._exit(0)
    else:
        print("\nForce exit!")
        cleanup()
        os._exit(1)


# ============================================================
# Main
# ============================================================

def main():
    signal.signal(signal.SIGINT, force_exit)
    signal.signal(signal.SIGTERM, force_exit)

    logger.info("=" * 50)
    logger.info("  OmniAgent v8.0 - Parallel Autonomous Agent")
    logger.info(f"  Pairing Code: {PAIRING_CODE}")
    logger.info("=" * 50)

    # Log system info
    import platform
    logger.info(f"Host: {platform.node()} ({platform.system()} {platform.release()})")
    logger.info(f"Python: {platform.python_version()}")
    logger.info(f"PID: {os.getpid()}")
    logger.info(f"Working dir: {os.getcwd()}")

    # Log available models and preload the primary one
    try:
        from src.tools import ollama_list_models
        models = ollama_list_models()
        if models and not any("error" in str(m) for m in models):
            names = [m.get("name", "?") for m in models]
            logger.info(f"Ollama models: {', '.join(names)}")
            # Preload the general model to eliminate cold-start lag
            def preload_model():
                try:
                    import urllib.request as _ur, json as _j
                    from src.config import EXPERTS
                    model = EXPERTS.get("general", "dolphin3:8b")
                    body = _j.dumps({"model": model, "prompt": "", "keep_alive": "10m"}).encode()
                    req = _ur.Request("http://localhost:11434/api/generate", data=body,
                                     headers={"Content-Type": "application/json"})
                    _ur.urlopen(req, timeout=30)
                    logger.info(f"[Preload] Model '{model}' loaded into memory")
                except Exception as e:
                    logger.debug(f"[Preload] Failed: {e}")
            threading.Thread(target=preload_model, daemon=True).start()
        else:
            logger.warning("Ollama not responding or no models installed")
    except Exception:
        logger.warning("Could not query Ollama models")

    # Log capabilities
    try:
        from src.multimodal import detect_capabilities
        caps = detect_capabilities()
        active = [k for k, v in caps.items() if v.get("available")]
        logger.info(f"Capabilities: {', '.join(active) if active else 'none'}")
    except Exception:
        pass

    # Start GPU worker discovery (optional — works without workers)
    try:
        from src.gpu_client import pool, set_secret, add_worker_manually
        worker_secret = os.environ.get("WORKER_SECRET", "")
        if worker_secret:
            set_secret(worker_secret)
            logger.info("[GPU Workers] E2E encryption enabled")
        pool.start_discovery()
        logger.info("[GPU Workers] LAN discovery started (UDP 5199)")
        # Manual worker URL for WSL2 or non-broadcast setups
        worker_url = os.environ.get("WORKER_URL", "")
        if worker_url:
            if add_worker_manually(worker_url):
                logger.info(f"[GPU Workers] Manually connected to {worker_url}")
            else:
                logger.warning(f"[GPU Workers] Could not reach {worker_url}")
    except Exception as e:
        logger.debug(f"[GPU Workers] Discovery disabled: {e}")

    # Initialize upgrade systems (RAG indexing, health checks, session cleanup)
    try:
        from src.upgrades import init_upgrades
        init_upgrades()
        logger.info("[Upgrades] All systems initialized")
    except Exception as e:
        logger.debug(f"[Upgrades] Init error: {e}")

    # Start scheduled task runner
    try:
        from src.features import start_scheduler
        start_scheduler()
        logger.info("[Scheduler] Task scheduler started")
    except Exception as e:
        logger.debug(f"[Scheduler] Init error: {e}")

    # Start metrics recording for dashboard
    try:
        from src.experiments import record_metrics_snapshot
        import threading
        def _metrics_loop():
            import time
            while True:
                try:
                    record_metrics_snapshot()
                except Exception:
                    pass
                time.sleep(60)
        threading.Thread(target=_metrics_loop, daemon=True).start()
        logger.info("[Dashboard] Metrics recording started (1/min)")
    except Exception as e:
        logger.debug(f"[Dashboard] Init error: {e}")

    # Start services
    start_bitnet()

    # Start metrics logger thread
    metrics_thread = threading.Thread(target=metrics_logger, daemon=True)
    metrics_thread.start()
    logger.info("[Metrics] Background metrics logger started (60s interval)")

    # Start server
    dev_mode = os.environ.get("DEV", "").lower() in ("1", "true", "yes")
    if dev_mode:
        logger.info("[Server] Starting on http://0.0.0.0:8000 (HOT RELOAD enabled)")
    else:
        logger.info("[Server] Starting on http://0.0.0.0:8000")
    config = uvicorn.Config(
        app, host="0.0.0.0", port=8000, log_level="warning",
        reload=dev_mode, reload_dirs=["src", "templates"] if dev_mode else None,
    )
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None

    # Start tunnel after a short delay (server needs to be up first)
    def delayed_tunnel():
        time.sleep(3)
        start_tunnel()
    tunnel_thread = threading.Thread(target=delayed_tunnel, daemon=True)
    tunnel_thread.start()

    try:
        server.run()
    finally:
        cleanup()


if __name__ == "__main__":
    main()
