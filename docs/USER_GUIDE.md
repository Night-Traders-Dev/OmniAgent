# User Guide

## Getting Started

After starting the server (`python omni_agent.py`), open **http://localhost:8000** or launch the Android/Desktop app.

### First Login
1. Click **Register** to create an account (username + password)
2. Or click **Continue as Guest** for quick access

### Sending Messages
Type your message and press **Ctrl+Enter** (or tap **GO** on Android). The agent will:
- Analyze your request
- Choose the right specialist agent(s)
- Execute tools as needed
- Return the result

### Example Tasks

**Coding:**
> "Create a Python script that scrapes headlines from Hacker News"

> "Find and fix the bug in src/web.py where sessions don't expire"

> "Refactor the auth module to use JWT tokens"

**Research:**
> "What are the best practices for rate limiting REST APIs? Show me implementations."

> "Compare React vs Svelte for a new dashboard project"

**System:**
> "What's using the most disk space?"

> "Show me the git log for the last week"

> "Run the test suite and fix any failures"

**Voice:**
> "Speak to me — what's the weather in New York?"

> "Read this aloud: the deployment succeeded"

## Tool Controls

### Toggle Bar
At the bottom of the chat, you'll see:
- **Execute / Teach** — Execute mode runs commands autonomously. Teach mode explains steps for you to do manually.
- **Tools** — Opens the tool toggle popup with 8 categories

### Tool Categories
| Toggle | What It Controls |
|--------|-----------------|
| **Web** | Web search, URL fetching, weather, APIs |
| **Read** | File reading, code search, project analysis |
| **Write** | File creation, editing, regex replace |
| **Shell** | Command execution, tests, Python eval |
| **Vision** | Image analysis via multimodal model |
| **Image** | Image generation via Stable Diffusion |
| **Voice** | Text-to-speech audio generation |
| **Git** | Git commits, checkouts, stashing |

### Acceleration
- **BitNet** — Uses lightweight 2B CPU model for planning (frees GPU)
- **Large Model (32B)** — Routes complex tasks to GPU worker's bigger model
- **On-Device NPU** — (Android only) Uses Gemini Nano on the phone's NPU for query rewriting, intent classification, sentiment analysis, response summarization, and smart replies. Handles greetings, time queries, and general knowledge entirely on-device. Server receives pre-classified intent hints for faster routing

## Chat Features

### Smart Replies
After each response, purple suggestion chips appear:
- Click to send instantly
- Context-aware (error → "How do I fix this?", code → "Write tests")

### Message Actions

**WebUI:**
- Double-click a user message to **edit and resend**
- Right-click the ⌥ button on user messages to **branch** the conversation
- Messages with `/uploads/` links render as **media cards** with download/share/delete

**Android:**
- Long-press user messages → Copy, Resend, Resend with different model, Branch
- Long-press assistant messages → Copy, Share, Pin, Rate (thumbs up/down)

### Media in Chat
- **Images**: Displayed inline, click to view full size
- **Audio**: Embedded player with controls
- **Files**: Card with icon, name, type, download button
- Right-click (WebUI) or long-press (Android) for context menu: Download, Share, Reference in Chat, Delete

### Voice
- Click the **mic button** to record audio (speech-to-text)
- Say voice keywords like "speak to me" or "use voice" to get spoken responses
- TTS preprocessor handles abbreviations, code syntax, and symbols naturally

### Search
- **In-session**: Click the search icon, type to find messages in the current chat
- **Cross-session**: Settings → History → Search All Sessions

### Pinned Messages
Long-press an assistant message → **Pin Message** to mark it as important. Pinned messages:
- Persist across context compression
- Are injected into every prompt so the model always remembers them

## Settings

Open via the **⚙** icon (WebUI) or **gear** button (Android).

### Live Metrics
- Tasks completed, LLM calls, messages, tokens in/out
- GPU temperature and VRAM
- GPU worker count

### System Presets
Quick-switch system prompts: Default, Code Reviewer, Tutor, Writer, DevOps, Data Analyst, Security, Concise.

### Quick Templates
Pre-filled prompts: Code Review, Explain Code, Write Tests, Debug, Refactor, Project Setup.

### Integrations
- **GitHub** — Connect for repo access, gist creation
- **Google** — Connect for Drive, Gmail, Tasks
- Click **Connect with...** for OAuth (if configured) or use token entry

### History
- **Reasoning/Thinking Log** — Full history of agent thinking steps
- **Long-Running Tasks** — View, resume, or rollback multi-phase tasks
- **Conversation Tree** — Visual message flow

### About
- **Changelog** — Full version history rendered in markdown
- **Version** — Current version number

## Long-Running Tasks

For complex requests like "refactor the entire auth system", OmniAgent automatically:

1. **Plans** — Breaks the task into 2-6 phases using the LLM
2. **Checkpoints** — Saves progress after every tool step
3. **Git Branch** — Creates `task/XXXXXXXX` branch for safe rollback
4. **Approval Gates** — Pauses before destructive phases (delete, deploy)
5. **File Manifest** — Tracks every file created/modified/deleted

View task history in Settings → History → Long-Running Tasks.

### Task Queue
Queue multiple tasks to run sequentially:
```
"First refactor the auth module, then run the test suite, then update the docs"
```

### Scheduled Tasks
Set up recurring tasks in Settings:
- Intervals: `hourly`, `daily`, `weekly`, `30m`, `6h`, `2d`
- Example: "Run security audit every Sunday"

## Remote Access

### Android Connection
1. **LAN**: The app auto-discovers the server on your local network
2. **Pairing Code**: Enter the code shown in the server logs
3. **Manual**: Enter the server IP or tunnel URL directly

### Remember Device
Check "Remember this device" on login to save the pairing code. If the tunnel URL changes, the app auto-resolves the new URL.

## Theme

Click the **☼** button (WebUI header) or **sun/moon** icon (Android top bar) to toggle between dark and light themes.

## Keyboard Shortcuts (WebUI)

| Shortcut | Action |
|----------|--------|
| `Ctrl+Enter` | Send message |
| `Ctrl+F` | Toggle search |
| `Escape` | Close panels |
| `Ctrl+V` (image) | Paste image into chat |
| Double-click message | Edit and resend |
| Drag & drop files | Upload files |

## MCP (Model Context Protocol)

OmniAgent supports the full MCP protocol — it can both expose its tools and consume tools from other servers.

### Connecting Claude Desktop

Add to `~/.config/claude/claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "omniagent": {
      "command": "python",
      "args": ["/path/to/OmniAgent/mcp_server.py"]
    }
  }
}
```

Claude Desktop will then have access to all 47 OmniAgent tools, 4 resources, and 6 prompts.

### Connecting Claude Code

```bash
claude mcp add omniagent python /path/to/OmniAgent/mcp_server.py
```

### Connecting External MCP Servers

In Settings, use the **MCP Servers** section to connect to external MCP servers. External tools become available to all agents automatically.

```bash
# Example: connect the official filesystem MCP server
curl -X POST http://localhost:8000/api/mcp/register/stdio \
  -H "Content-Type: application/json" \
  -d '{"name": "fs", "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/home"]}'
```

## Fine-Tuning

Every time you rate a response (thumbs up/down), training data is collected automatically. After 500+ samples:

1. Export the data:
```bash
curl http://localhost:8000/api/finetune/export?format=alpaca
```

2. Fine-tune with your preferred framework (Unsloth, Axolotl, LLaMA-Factory):
```bash
# Example with Unsloth
python finetune.py --data finetune_data/alpaca_export.json --model qwen2.5-coder:7b
```

3. Load the fine-tuned model into Ollama:
```bash
ollama create my-coder -f Modelfile
```
