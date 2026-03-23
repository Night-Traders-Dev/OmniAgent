# OmniAgent v8.3 — Documentation

## Guides

| Document | Description |
|----------|-------------|
| [README](../README.md) | Project overview, quick start, features |
| [Setup Guide](SETUP.md) | Installation, configuration, deployment |
| [User Guide](USER_GUIDE.md) | How to use every feature on every platform |
| [Architecture](ARCHITECTURE.md) | System design, module map, developer guide |
| [Tool Reference](TOOLS.md) | All 47 tools with usage examples |
| [API Reference](API.md) | All 147 REST endpoints |
| [GPU Worker](GPU_WORKER.md) | Second PC setup for offloading |
| [Changelog](../CHANGELOG.md) | Full version history (v7.0 → v8.3) |

## Quick Links

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **Health Check**: http://localhost:8000/api/identify
- **Metrics**: http://localhost:8000/api/metrics

## System Stats

```
Backend:    12,269 lines across 29 Python modules
WebUI:      2,169 lines (single HTML file)
Android:    4,851 lines across 11 Kotlin files
Desktop:    Tauri (Rust + WebView, 9.3MB binary)
VS Code:    Extension scaffold (Ask, Explain, Fix, Review)
Tools:      47 registered, all with explicit timeouts
Agents:     7 specialists (Reasoner, Coder, Researcher, Planner, ToolUser, Security, Fast)
Endpoints:  147 REST + 1 WebSocket
DB Tables:  14 (SQLite with Fernet encryption)
Tests:      319 total (88 integration, all passing)
Platforms:  4 (WebUI, Android, Linux Desktop, VS Code)
```
