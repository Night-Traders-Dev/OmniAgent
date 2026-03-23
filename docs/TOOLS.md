# Tool Reference — 47 Tools

All tools are available to agents during task execution. Users can toggle categories on/off in the Tools popup.

## Toggle Categories

| Category | Tools | Toggle |
|----------|-------|--------|
| **File Read** | read, glob, grep, tree, list_dir, file_info, analyze_file, project_deps, find_symbol, semantic_search | `file_read` |
| **File Write** | write, edit, batch_edit, regex_replace | `file_write` |
| **Shell** | shell, run_tests, python_eval, process_list, kill_process | `shell` |
| **Web Search** | web, deep_research, multi_search, fetch_url, weather, http_request | `web_search` |
| **Vision** | vision | `vision` |
| **Image Gen** | generate_image | `image_gen` |
| **Voice** | speak | `voice` |
| **Git** | git_commit, git_checkout, git_stash | `git` |
| **Always On** | done, database, docker, pdf_read, archive, screenshot, spawn_agent, env_get, env_set, json_extract, network_info, diff_preview, sandbox_run | — |

## File Tools

### `read` — Read a file
```json
{"tool": "read", "args": {"path": "src/web.py", "offset": 0, "limit": 50}}
```
- `offset`: Start line (0-indexed)
- `limit`: Number of lines to read
- Large files auto-truncate at 500 lines with a hint to use offset/limit

### `write` — Write content to a file
```json
{"tool": "write", "args": {"path": "output.py", "content": "print('hello')"}}
```
Creates parent directories automatically.

### `edit` — Surgical text replacement
```json
{"tool": "edit", "args": {"path": "app.py", "old_text": "def foo():", "new_text": "def bar():"}}
```
`old_text` must be unique in the file. Fails if ambiguous.

### `batch_edit` — Multiple edits across files
```json
{"tool": "batch_edit", "args": {"edits": [
    {"path": "a.py", "old_text": "foo", "new_text": "bar"},
    {"path": "b.py", "old_text": "baz", "new_text": "qux"}
]}}
```
Up to 20 edits per call.

### `regex_replace` — Pattern-based replacement
```json
{"tool": "regex_replace", "args": {"path": "file.py", "pattern": "v\\d+\\.\\d+", "replacement": "v2.0", "count": 0}}
```
`count=0` replaces all matches.

### `glob` — Find files by pattern
```json
{"tool": "glob", "args": {"pattern": "**/*.py", "root": "src"}}
```

### `grep` — Search file contents
```json
{"tool": "grep", "args": {"pattern": "def.*search", "path": "src", "file_glob": "*.py", "max_results": 20}}
```

### `tree` — Directory structure
```json
{"tool": "tree", "args": {"path": ".", "max_depth": 3}}
```

### `list_dir` — List directory contents
```json
{"tool": "list_dir", "args": {"path": "src"}}
```

### `file_info` — File metadata
```json
{"tool": "file_info", "args": {"path": "omni_agent.py"}}
```

### `diff_preview` — Preview an edit as unified diff
```json
{"tool": "diff_preview", "args": {"path": "file.py", "old_text": "foo", "new_text": "bar"}}
```

## Code Intelligence

### `analyze_file` — File analysis
```json
{"tool": "analyze_file", "args": {"path": "src/web.py"}}
```
Shows: language, imports, functions, classes, what imports this file.

### `project_deps` — Dependency graph
```json
{"tool": "project_deps", "args": {"root": "src"}}
```

### `find_symbol` — Find function/class definitions
```json
{"tool": "find_symbol", "args": {"name": "execute_tool"}}
```

### `semantic_search` — Semantic code search
```json
{"tool": "semantic_search", "args": {"query": "authentication logic"}}
```

## Shell & Process

### `shell` — Run shell command
```json
{"tool": "shell", "args": {"cmd": "ls -la", "timeout": 30}}
```
Dangerous commands (rm -rf, sudo, etc.) are blocked.

### `python_eval` — Evaluate Python expression
```json
{"tool": "python_eval", "args": {"expression": "sum(range(100))"}}
```
No file/network access — safe for math and data operations.

### `run_tests` — Run project test suite
```json
{"tool": "run_tests", "args": {}}
```

### `sandbox_run` — Sandboxed code execution
```json
{"tool": "sandbox_run", "args": {"code": "import os; print(os.listdir('/'))", "language": "python", "timeout": 10}}
```
Runs in Docker container with no network, limited memory/PIDs.

### `process_list` — List processes
```json
{"tool": "process_list", "args": {}}
```

### `kill_process` — Kill a process
```json
{"tool": "kill_process", "args": {"pid": 1234, "signal": 15}}
```

## Web & Search

### `web` — DuckDuckGo search
```json
{"tool": "web", "args": {"query": "python fastapi tutorial", "max_results": 5}}
```

### `deep_research` — Multi-step research
```json
{"tool": "deep_research", "args": {"query": "best practices for API rate limiting", "max_depth": 2}}
```
Searches → reads top pages → extracts key facts.

### `multi_search` — Multiple queries
```json
{"tool": "multi_search", "args": {"queries": ["python async", "python asyncio tutorial", "fastapi async"]}}
```

### `fetch_url` — Read a web page
```json
{"tool": "fetch_url", "args": {"url": "https://docs.python.org/3/library/asyncio.html", "max_chars": 5000}}
```

### `http_request` — HTTP API call
```json
{"tool": "http_request", "args": {"url": "https://api.example.com/data", "method": "GET"}}
```

### `weather` — Weather data
```json
{"tool": "weather", "args": {"location": "New York", "forecast_days": 3}}
```

### `json_extract` — Navigate JSON
```json
{"tool": "json_extract", "args": {"data": "{\"users\":[{\"name\":\"Alice\"}]}", "path": "users.0.name"}}
```

## Git

### `git_status`, `git_diff`, `git_log`
```json
{"tool": "git_status", "args": {}}
{"tool": "git_diff", "args": {"staged": true}}
{"tool": "git_log", "args": {"n": 5}}
```

### `git_commit` — Stage and commit
```json
{"tool": "git_commit", "args": {"message": "feat: add user auth"}}
```

### `git_checkout` — Restore file
```json
{"tool": "git_checkout", "args": {"path": "src/web.py"}}
```

### `git_stash` — Stash operations
```json
{"tool": "git_stash", "args": {"action": "push"}}
```

## Multimodal

### `vision` — Analyze image
```json
{"tool": "vision", "args": {"image_path": "/path/to/image.png", "prompt": "Describe this screenshot"}}
```

### `generate_image` — Create image from prompt
```json
{"tool": "generate_image", "args": {"prompt": "a futuristic city at sunset", "width": 512, "height": 512}}
```

### `speak` — Text to speech
```json
{"tool": "speak", "args": {"text": "Hello, this is OmniAgent speaking"}}
```

## Other

### `database` — SQLite query
```json
{"tool": "database", "args": {"query": "SELECT COUNT(*) FROM users", "db_path": "omni_data.db"}}
```
Read-only queries only.

### `docker` — Docker commands
```json
{"tool": "docker", "args": {"cmd": "ps"}}
```

### `pdf_read` — Extract PDF text
```json
{"tool": "pdf_read", "args": {"path": "document.pdf", "max_pages": 10}}
```

### `archive` — Archive operations
```json
{"tool": "archive", "args": {"action": "list", "path": "backup.zip"}}
```

### `screenshot` — Capture desktop
```json
{"tool": "screenshot", "args": {}}
```

### `env_get` / `env_set` — Environment variables
```json
{"tool": "env_get", "args": {"name": "HOME"}}
{"tool": "env_set", "args": {"name": "MY_VAR", "value": "42"}}
```

### `network_info` — Network interfaces
```json
{"tool": "network_info", "args": {}}
```

### `spawn_agent` — Sub-agent delegation
```json
{"tool": "spawn_agent", "args": {"agent": "researcher", "task": "find best practices for..."}}
```
