# API Reference

**155 endpoints** — Interactive docs at `http://localhost:8000/docs`


## /

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` |  |

## /agents

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/agents` |  |

## /auth

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/auth/login` |  |
| `POST` | `/api/auth/register` |  |
| `GET` | `/api/auth/sessions` |  |
| `POST` | `/api/auth/sessions/archive` |  |
| `GET` | `/api/auth/sessions/archived` |  |
| `POST` | `/api/auth/sessions/delete` |  |
| `POST` | `/api/auth/sessions/load` |  |
| `GET` | `/api/auth/sessions/metrics` |  |
| `POST` | `/api/auth/sessions/metrics/save` | Persist current live metrics for a session. |
| `POST` | `/api/auth/sessions/new` |  |
| `POST` | `/api/auth/sessions/rename` |  |
| `POST` | `/api/auth/sessions/unarchive` |  |
| `GET` | `/api/auth/user` |  |

## /bitnet

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/bitnet` |  |
| `POST` | `/api/bitnet` |  |
| `POST` | `/api/bitnet/classify` | Quick classification using BitNet. |
| `POST` | `/api/bitnet/parallel` | Run multiple tasks on BitNet in parallel. |
| `POST` | `/api/bitnet/summarize` | Quick summarization using BitNet. |

## /capabilities

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/capabilities` |  |

## /changelog

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/changelog` | Serve CHANGELOG.md as JSON with raw markdown content. |

## /chat

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/chat/branch` |  |
| `POST` | `/api/chat/compare` | Send the same prompt to multiple models and return all respo |
| `POST` | `/api/chat/rate` |  |
| `GET` | `/api/chat/search` |  |
| `GET` | `/api/chat/share/{session_id}` | Get a read-only view of a shared conversation. |
| `GET` | `/api/chat/tree/{session_id}` |  |
| `POST` | `/chat` |  |

## /clear-session

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/clear-session` |  |

## /collab

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/collab/invite` |  |
| `GET` | `/api/collab/members` |  |
| `POST` | `/api/collab/share` |  |

## /dashboard

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/dashboard` |  |

## /drive

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/drive/files` |  |
| `POST` | `/api/drive/upload` |  |

## /execute

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/mcp/execute` | Legacy: execute a tool via MCP (prefer POST /mcp with tools/call) |

## /export

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/export/pdf` |  |
| `GET` | `/api/export/{fmt}` |  |

## /finetune

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/finetune/collect` |  |
| `GET` | `/api/finetune/export` |  |
| `GET` | `/api/finetune/stats` |  |

## /git

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/git/worktree/cleanup` |  |
| `POST` | `/api/git/worktree/create` |  |

## /github

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/github/gists` |  |
| `POST` | `/api/github/gists` |  |
| `GET` | `/api/github/repos` |  |

## /hooks

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/hooks` |  |
| `POST` | `/api/hooks/register` |  |

## /identify

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/identify` | Identification endpoint for network discovery by mobile apps |

## /image

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/image/generate` |  |

## /integrations

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/integrations` |  |
| `POST` | `/api/integrations/connect` |  |
| `POST` | `/api/integrations/disconnect` |  |
| `POST` | `/api/integrations/save-chat` |  |

## /legacy

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/chat/legacy` |  |

## /location

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/location` | Store user's location (from browser Geolocation or Android G |
| `GET` | `/api/location` |  |

## /manifest

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/mcp/manifest` | Legacy: get tool manifest (prefer POST /mcp with tools/list) |

## /mcp

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/mcp` | MCP JSON-RPC 2.0 endpoint (initialize, tools/list, tools/call, resources, prompts, completion) |
| `GET` | `/mcp/sse` | MCP SSE transport — server pushes events, client POSTs to /mcp |
| `POST` | `/api/mcp/register` | Legacy: register external MCP server by URL |
| `POST` | `/api/mcp/register/stdio` | Connect to external MCP server via stdio (launches subprocess) |
| `POST` | `/api/mcp/register/sse` | Connect to external MCP server via SSE/HTTP transport |
| `POST` | `/api/mcp/call` | Call a tool on a connected external MCP server |
| `POST` | `/api/mcp/disconnect` | Disconnect from an external MCP server |
| `GET` | `/api/mcp/servers` | List all connected external MCP servers and their tools |
| `GET` | `/api/mcp/tools` | List all tools from all connected external MCP servers |

## /memory

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/memory` |  |
| `POST` | `/api/memory/add` |  |
| `POST` | `/api/memory/forget` |  |

## /metrics

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/metrics` | Metrics scoped to a session, includes global counters. Used  |

## /mode

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/mode` |  |
| `POST` | `/api/mode` |  |

## /model-override

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/model-override` |  |

## /models

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/models` |  |
| `GET` | `/api/models/benchmark` | Benchmark installed models for auto-selection. |
| `GET` | `/api/models/best` |  |
| `POST` | `/api/models/compare` |  |
| `POST` | `/api/models/delete` |  |
| `POST` | `/api/models/pull` |  |
| `GET` | `/api/models/{model_name:path}/info` |  |

## /notifications

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/notifications/config` |  |
| `GET` | `/api/notifications/test` |  |

## /oauth

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/oauth/callback/github` |  |
| `GET` | `/api/oauth/callback/google` |  |
| `POST` | `/api/oauth/config` | Save OAuth client credentials (one-time setup per service). |
| `POST` | `/api/oauth/refresh/google` | Refresh an expired Google access token using the stored refr |
| `GET` | `/api/oauth/status` | Check which OAuth services are configured. |

## /pairing

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/pairing` | Return the current pairing code and tunnel URL (if active). |
| `GET` | `/api/pairing/resolve/{code}` | Resolve a pairing code to a tunnel URL via ntfy.sh. |

## /permissions

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/permissions` |  |
| `POST` | `/api/permissions` |  |
| `POST` | `/api/permissions/approve` |  |
| `GET` | `/api/permissions/pending` |  |

## /pins

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/pins` |  |
| `GET` | `/api/pins` |  |
| `DELETE` | `/api/pins/{pin_id}` |  |

## /plugins

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/plugins` | List all currently loaded user plugins. |
| `POST` | `/api/plugins/install` |  |
| `GET` | `/api/plugins/marketplace` |  |
| `POST` | `/api/plugins/reload` | Unload all plugins and re-scan ~/.omniagent/tools/. |

## /preferences

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/preferences` |  |
| `POST` | `/api/preferences` |  |

## /presets

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/presets` |  |
| `POST` | `/api/presets/apply` |  |

## /project

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/project/context` |  |

## /reasoning

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/reasoning` |  |
| `POST` | `/api/reasoning` |  |
| `GET` | `/api/reasoning/history` | Get the full reasoning/thinking log for a session. |
| `DELETE` | `/api/reasoning/history` | Clear the reasoning log for a session. |
| `POST` | `/api/reasoning/index` | Trigger RAG codebase indexing. |

## /sandbox

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/sandbox/run` |  |

## /schedules

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/schedules` |  |
| `GET` | `/api/schedules` |  |
| `DELETE` | `/api/schedules/{schedule_id}` |  |

## /search

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/search/global` | Search across ALL conversations for the user. |

## /session

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/session/new` | Create a new session and return its ID. |

## /sessions

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/sessions` |  |

## /settings

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/settings` | Settings scoped to a session. |
| `POST` | `/api/settings` |  |

## /stream

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/chat/stream` | Stream the response token-by-token via SSE. |
| `GET` | `/stream` | SSE stream scoped to a specific session. Works over tunnels  |

## /system-prompt

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/system-prompt` |  |
| `POST` | `/api/system-prompt` |  |

## /tasks

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/tasks/background` |  |
| `POST` | `/api/tasks/cancel` |  |
| `POST` | `/api/tasks/create` |  |
| `GET` | `/api/tasks/detail/{task_id}` | Get full task details including phases, checkpoints, manifes |
| `GET` | `/api/tasks/diff/{task_id}` | Get a diff summary of task changes. |
| `POST` | `/api/tasks/execute` | Execute or resume a planned task. |
| `GET` | `/api/tasks/list` | List all tasks for a session. |
| `GET` | `/api/tasks/lists` |  |
| `POST` | `/api/tasks/plan` | Plan a complex task into phases. |
| `POST` | `/api/tasks/queue` | Add a task to the queue. |
| `GET` | `/api/tasks/queue` | Get the task queue. |
| `POST` | `/api/tasks/queue/process` | Start processing the task queue. |
| `POST` | `/api/tasks/resume` | Resume a paused task (approve and continue). |
| `POST` | `/api/tasks/rollback` | Rollback all changes made by a task. |

## /templates

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/templates` |  |

## /test

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/test/run` |  |

## /tools

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/tools` |  |
| `POST` | `/api/tools/toggle` |  |

## /upload

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/upload` |  |

## /uploads

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/uploads/delete` | Delete an uploaded file. Requires valid session. |
| `GET` | `/api/uploads/list` | List all uploaded files. Requires valid session. |

## /verify

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/verify` | Send a result to a GPU worker for independent verification. |

## /video

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/video/generate` |  |

## /vision

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/vision/analyze` |  |

## /voice

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/voice/speak` |  |
| `POST` | `/api/voice/transcribe` |  |

## /workers

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/workers` | Get status of connected GPU workers. |
| `POST` | `/api/workers/add` | Manually register a GPU worker (for WSL2 or non-broadcast se |

## /{session_id}

| Method | Endpoint | Description |
|--------|----------|-------------|
| `WEBSOCKET` | `/ws/{session_id}` |  |