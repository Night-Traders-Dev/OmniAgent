# OmniAgent v8.3 — Setup & Installation Guide

## Prerequisites

- **Python 3.11+** (3.13 recommended)
- **Ollama** — Local LLM inference server
- **NVIDIA GPU** with 8GB+ VRAM (RTX 3060 or better recommended)
- **8GB+ RAM** (16GB recommended)

## Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/yourusername/OmniAgent.git
cd OmniAgent

# 2. Install Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# 3. Pull required models
ollama pull dolphin3:8b          # General/orchestrator (uncensored)
ollama pull qwen2.5-coder:7b     # Coding specialist
ollama pull deepseek-r1:8b       # Reasoning specialist

# 4. Install Python dependencies
pip install -r requirements.txt

# 5. Start OmniAgent
python omni_agent.py
```

Open **http://localhost:8000** in your browser.

## Detailed Installation

### Python Dependencies

Core:
```bash
pip install fastapi uvicorn openai slowapi pydantic cryptography bcrypt
```

Voice (optional):
```bash
pip install faster-whisper piper-tts
# Download voice model
mkdir -p ~/.local/share/piper-voices
cd ~/.local/share/piper-voices
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx.json
```

Image Generation (optional):
```bash
pip install diffusers torch accelerate transformers
```

Search & RAG:
```bash
pip install ddgs faiss-cpu
```

### Ollama Models

| Model | Size | Purpose | Required |
|-------|------|---------|----------|
| `dolphin3:8b` | 4.9GB | General/orchestrator | Yes |
| `qwen2.5-coder:7b` | 4.7GB | Code generation | Yes |
| `deepseek-r1:8b` | 5.2GB | Reasoning | Yes |
| `llama3.2-vision:11b` | 7.8GB | Image analysis | Optional |

```bash
# Pull all models
ollama pull dolphin3:8b
ollama pull qwen2.5-coder:7b
ollama pull deepseek-r1:8b
ollama pull llama3.2-vision:11b  # Optional — for vision
```

### BitNet (Optional — CPU Acceleration)

BitNet runs a lightweight 2B model on CPU for dispatch planning, freeing your GPU:

```bash
# If bitnet/ directory exists with llama-server and model:
# It auto-starts and auto-detects on server boot
ls bitnet/llama-server bitnet/model/ggml-model-i2_s.gguf
```

## Platform Installation

### WebUI
No installation needed — served at `http://localhost:8000` when the server is running.

### Android

1. Enable **Developer Options** → **USB Debugging** on your phone
2. Connect via USB
3. Install:
```bash
cd android
./gradlew assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

Or transfer the APK file to your phone and install manually.

### Linux Desktop

```bash
# Option 1: Run the binary directly
./desktop/src-tauri/target/release/omniagent-desktop

# Option 2: Install the deb package
sudo dpkg -i desktop/src-tauri/target/release/bundle/deb/OmniAgent_8.3.0_amd64.deb

# Option 3: Install the RPM
sudo rpm -i desktop/src-tauri/target/release/bundle/rpm/OmniAgent-8.3.0-1.x86_64.rpm
```

The desktop app requires the server to be running (`python omni_agent.py`).

### VS Code Extension

```bash
cd vscode-extension
npm install
# Press F5 in VS Code to run in development mode
# Or package: npx vsce package
```

## Docker Deployment

```bash
# Start everything with one command
docker compose up -d

# Pull models into the containerized Ollama
docker compose exec ollama ollama pull dolphin3:8b
docker compose exec ollama ollama pull qwen2.5-coder:7b
docker compose exec ollama ollama pull deepseek-r1:8b

# View logs
docker compose logs -f omniagent
```

## systemd Service (Auto-Start on Boot)

```bash
# Copy the service file
sudo cp omniagent.service /etc/systemd/system/

# Enable and start
sudo systemctl enable omniagent
sudo systemctl start omniagent

# Check status
sudo systemctl status omniagent
```

## GPU Worker (Second PC)

See [GPU_WORKER.md](GPU_WORKER.md) for detailed setup.

Quick start:
```bash
# On the second PC
python gpu_worker.py

# With E2E encryption
WORKER_SECRET=mykey python gpu_worker.py
```

## Remote Access (Cloudflare Tunnel)

OmniAgent automatically creates a Cloudflare tunnel for internet access:
- A pairing code is generated and published via ntfy.sh
- Use the pairing code in the Android app to connect remotely
- The tunnel URL rotates — the app auto-resolves via the saved pairing code

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_NUM_CTX` | `32768` | Context window for Ollama models |
| `BITNET_PORT` | `8081` | BitNet llama-server port |
| `WORKER_SECRET` | — | GPU worker E2E encryption key |
| `WORKER_URL` | — | Manual GPU worker URL (WSL2) |
| `GITHUB_CLIENT_ID` | — | GitHub OAuth app client ID |
| `GITHUB_CLIENT_SECRET` | — | GitHub OAuth app secret |
| `GOOGLE_CLIENT_ID` | — | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | — | Google OAuth client secret |
| `DISCORD_WEBHOOK_URL` | — | Discord notification webhook |
| `SLACK_WEBHOOK_URL` | — | Slack notification webhook |
| `SESSION_TTL_HOURS` | `72` | Session expiry time |
| `MAX_UPLOAD_DIR_MB` | `500` | Upload directory size limit |
| `DEV` | — | Set to `1` for hot reload mode |

## Troubleshooting

**Ollama not responding:**
```bash
systemctl status ollama
ollama serve  # Start manually
```

**Models not loading (VRAM):**
The server sets `OLLAMA_MAX_LOADED_MODELS=1` to prevent VRAM exhaustion. Models swap automatically.

**Android can't connect:**
1. Check the server IP: `hostname -I`
2. Ensure port 8000 is open: `curl http://YOUR_IP:8000/api/identify`
3. Try the pairing code if connecting via tunnel

**BitNet not detected:**
```bash
curl http://localhost:8081/v1/models  # Should return model info
```

**TTS not working:**
```bash
python3 -c "from piper import PiperVoice; print('OK')"
ls ~/.local/share/piper-voices/en_US-amy-medium.onnx
```
