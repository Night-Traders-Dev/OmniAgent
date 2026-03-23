"""
Base agent class - all specialist agents inherit from this.
Supports multi-step tool loops, streaming, self-correction, conversation context,
teach mode enforcement, cost tracking, and confidence signaling.
"""
import asyncio
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncGenerator
from src.config import CLIENT, EXPERTS, BITNET_CLIENT, BITNET_MODEL, BITNET_ENABLED, OLLAMA_NUM_CTX, VERSION
from src.state import state
from src.tools import (
    parse_json, execute_tool, TOOL_REGISTRY, TOOL_TIMEOUTS,
    compress_tool_result, detect_uncertainty, ToolErrorKind,
    TOOL_DETAILED_REFERENCE,
)


class AgentStatus(Enum):
    IDLE = "idle"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


@dataclass
class AgentResult:
    agent_name: str
    status: AgentStatus
    output: str = ""
    artifacts: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    confidence: float = 1.0  # Tier 4: Confidence signaling
    token_cost: int = 0      # Tier 4: Cost tracking


# ============================================================
# Tier 4: Cost Awareness
# ============================================================

# Approximate tokens-per-second by model size for routing heuristics
MODEL_COST_HEURISTICS = {
    "fast": 1,     # BitNet — nearly free
    "general": 5,  # 8B models
    "coding": 5,   # 7B models
    "reasoning": 8, # 8B reasoning (slower due to chain-of-thought)
    "security": 5,  # 8B uncensored
}

def estimate_cost(model_key: str, input_len: int) -> int:
    """Estimate relative cost units for a task."""
    weight = MODEL_COST_HEURISTICS.get(model_key, 5)
    return weight * (input_len // 100 + 1)


class BaseAgent:
    name: str = "base"
    role: str = "general assistant"
    model_key: str = "general"
    system_prompt: str = "You are a helpful assistant."
    max_tool_steps: int = 0

    def __init__(self):
        self.status = AgentStatus.IDLE
        self._history: list[dict] = []

    @property
    def history(self) -> list[dict]:
        return self._history[-100:]

    def _append_history(self, entry: dict):
        self._history.append(entry)
        if len(self._history) > 150:
            self._history = self._history[-100:]

    @property
    def model(self) -> str:
        if state.model_override and state.model_override != "auto":
            return state.model_override
        return EXPERTS.get(self.model_key, EXPERTS["general"])

    @property
    def llm_client(self):
        if self.model_key == "fast" and BITNET_ENABLED:
            return BITNET_CLIENT
        return CLIENT

    async def execute(self, task: str, context: str = "", conversation: list[dict] | None = None) -> AgentResult:
        self.status = AgentStatus.RUNNING
        state.active_model = self.model
        loop = asyncio.get_event_loop()

        # Log when BitNet is being used
        if self.model_key == "fast" and BITNET_ENABLED:
            from datetime import datetime
            ts = datetime.now().strftime("%H:%M:%S")
            state.progress_log.append(f"[{ts}] ⚡ BitNet: {self.name} running on CPU ({BITNET_MODEL})")

        if self.max_tool_steps > 0:
            # Tier 4: Teach mode enforcement — no tool execution in teach mode
            if state.execution_mode == "teach":
                return await self._execute_teach_mode(task, context, conversation, loop)
            return await self._execute_with_tools(task, context, conversation, loop)

        try:
            messages = self._build_messages(task, context, conversation)
            cost = estimate_cost(self.model_key, len(str(messages)))
            response = await loop.run_in_executor(
                None,
                lambda: self.llm_client.chat.completions.create(model=self.model, messages=messages),
            )
            state.total_llm_calls += 1
            token_cost = 0
            if hasattr(response, 'usage') and response.usage:
                pin = getattr(response.usage, 'prompt_tokens', 0)
                pout = getattr(response.usage, 'completion_tokens', 0)
                state.session.total_tokens_in += pin
                state.session.total_tokens_out += pout
                token_cost = pin + pout
            output = response.choices[0].message.content
            confidence = detect_uncertainty(output)
            self._append_history({"task": task, "output": output})
            self.status = AgentStatus.SUCCESS
            return AgentResult(agent_name=self.name, status=AgentStatus.SUCCESS, output=output,
                             confidence=confidence, token_cost=token_cost)
        except Exception as e:
            self.status = AgentStatus.FAILED
            return AgentResult(agent_name=self.name, status=AgentStatus.FAILED, error=str(e))

    async def execute_streaming(self, task: str, context: str = "", conversation: list[dict] | None = None) -> AsyncGenerator[str, None]:
        state.active_model = self.model
        loop = asyncio.get_event_loop()
        messages = self._build_messages(task, context, conversation)
        try:
            response = await loop.run_in_executor(
                None,
                lambda: self.llm_client.chat.completions.create(model=self.model, messages=messages, stream=True),
            )
            state.total_llm_calls += 1
            full = []
            for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    token = chunk.choices[0].delta.content
                    full.append(token)
                    yield token
            self._append_history({"task": task, "output": "".join(full)})
        except Exception as e:
            yield f"\n[ERROR: {e}]"

    # ============================================================
    # Tier 4: Teach Mode Enforcement
    # ============================================================

    async def _execute_teach_mode(self, task: str, context: str, conversation: list[dict] | None, loop) -> AgentResult:
        """In teach mode, explain what tools would be used but don't execute them."""
        teach_system = (
            f"{self.system_prompt}\n\n"
            f"{self._build_environment_context()}\n\n"
            "You are in TEACHING mode. The user wants to LEARN.\n"
            f"Available tools (DO NOT EXECUTE, just explain what you would use and why):\n{TOOL_DETAILED_REFERENCE}\n\n"
            "For each step:\n"
            "1. Explain WHAT you would do and WHY\n"
            "2. Show the exact tool call JSON as a code block\n"
            "3. Explain what the expected output would look like\n"
            "4. Then move to the next step\n"
            "Be educational, thorough, and show your reasoning."
        )
        messages = [{"role": "system", "content": teach_system}]
        if conversation is None:
            conversation = state.get_recent_history(max_turns=10)
        for msg in (conversation or []):
            messages.append({"role": msg.get("role", "user"), "content": self._summarize_message(msg.get("content", ""))})
        messages.append({"role": "user", "content": task})

        try:
            response = await loop.run_in_executor(
                None, lambda: self.llm_client.chat.completions.create(model=self.model, messages=messages),
            )
            state.total_llm_calls += 1
            output = response.choices[0].message.content
            self.status = AgentStatus.SUCCESS
            return AgentResult(agent_name=self.name, status=AgentStatus.SUCCESS, output=output)
        except Exception as e:
            self.status = AgentStatus.FAILED
            return AgentResult(agent_name=self.name, status=AgentStatus.FAILED, error=str(e))

    # ============================================================
    # Tier 1: Self-Correction Loop + Streaming Tool Steps
    # ============================================================

    async def _execute_with_tools(self, task: str, context: str, conversation: list[dict] | None, loop) -> AgentResult:
        """Multi-step agentic loop with self-correction and streaming progress."""
        from datetime import datetime

        from src.agents.specialists import EXECUTE_MODE_DIRECTIVE
        env_context = self._build_environment_context()

        tool_system = (
            f"{self.system_prompt}\n\n"
            f"{env_context}\n\n"
            f"{EXECUTE_MODE_DIRECTIVE}\n\n"
            f"{TOOL_DETAILED_REFERENCE}\n\n"
            "HOW TO CALL TOOLS:\n"
            "Respond with ONLY a JSON object — no text before or after:\n"
            '{"tool": "tool_name", "args": {"arg1": "value1"}, "reasoning": "why I chose this tool"}\n\n'
            "To finish, respond with:\n"
            '{"tool": "done", "args": {}, "result": "your final answer to the user"}\n\n'
            "RULES:\n"
            "- Your FIRST response MUST be a tool call JSON, not plain text.\n"
            "- NEVER explain steps. EXECUTE them with tool calls.\n"
            "- EVERY response must be exactly ONE JSON tool call.\n"
            "- Choose the RIGHT tool: use 'edit' for small changes, 'write' for new files, 'batch_edit' for multi-file changes.\n"
            "- Use 'grep' to find code before editing. Use 'read' to verify file contents. Use 'glob' to discover files.\n"
            "- After write/edit, use 'run_tests' to verify your changes work.\n"
            "- Use 'deep_research' instead of 'web' for complex questions.\n"
            "\nSELF-CORRECTION RULES:\n"
            "- After each tool result, check if it contains errors\n"
            "- If a tool returned an error, analyze what went wrong and try a different approach\n"
            "- If a file wasn't found, check the path or search for it with glob/grep\n"
            "- If a command failed, read the error and fix the issue\n"
            "- Don't repeat the same failed operation — adapt your approach\n"
        )

        messages = [{"role": "system", "content": tool_system}]
        if context:
            messages[0]["content"] += f"\nCONTEXT:\n{context}"

        # Tier 1: Improved context — more turns, smarter summarization
        if conversation is None:
            conversation = state.get_recent_history(max_turns=10)
        for msg in (conversation or []):
            messages.append({"role": msg.get("role", "user"), "content": self._summarize_message(msg.get("content", ""))})
        messages.append({"role": "user", "content": task})

        all_tool_outputs = []
        consecutive_failures = 0
        total_tokens = 0

        for step in range(self.max_tool_steps):
            # Context compression: after 15 steps, summarize older messages to prevent context overflow
            if step > 0 and step % 15 == 0 and len(messages) > 20:
                try:
                    from src.task_engine import compress_context
                    messages = [messages[0]] + compress_context(messages[1:], max_keep=12)
                    state.progress_log.append(f"[{datetime.now().strftime('%H:%M:%S')}]   [{self.name}] context compressed at step {step}")
                except Exception:
                    pass

            try:
                response = await loop.run_in_executor(
                    None,
                    lambda: self.llm_client.chat.completions.create(model=self.model, messages=messages),
                )
                state.total_llm_calls += 1
                if hasattr(response, 'usage') and response.usage:
                    pin = getattr(response.usage, 'prompt_tokens', 0)
                    pout = getattr(response.usage, 'completion_tokens', 0)
                    state.session.total_tokens_in += pin
                    state.session.total_tokens_out += pout
                    total_tokens += pin + pout
                reply = response.choices[0].message.content
            except Exception as e:
                return AgentResult(agent_name=self.name, status=AgentStatus.FAILED, error=str(e),
                                 token_cost=total_tokens)

            data = parse_json(reply)
            if not data or "tool" not in data:
                self.status = AgentStatus.SUCCESS
                confidence = detect_uncertainty(reply)
                return AgentResult(agent_name=self.name, status=AgentStatus.SUCCESS, output=reply,
                                 artifacts={"steps": step + 1, "tool_outputs": all_tool_outputs},
                                 confidence=confidence, token_cost=total_tokens)

            tool_name = data["tool"].lower().strip()  # Normalize case
            tool_args = data.get("args", {})
            reasoning = data.get("reasoning", "")

            if tool_name == "done":
                final = data.get("result", reply)
                self.status = AgentStatus.SUCCESS
                confidence = detect_uncertainty(final)
                return AgentResult(agent_name=self.name, status=AgentStatus.SUCCESS, output=final,
                                 artifacts={"steps": step + 1, "tool_outputs": all_tool_outputs},
                                 confidence=confidence, token_cost=total_tokens)

            # Check tool toggles — map tools to their toggle category
            _tool_toggle_map = {
                "read": "file_read", "glob": "file_read", "grep": "file_read",
                "tree": "file_read", "list_dir": "file_read", "file_info": "file_read",
                "analyze_file": "file_read", "project_deps": "file_read",
                "find_symbol": "file_read", "semantic_search": "file_read",
                "write": "file_write", "edit": "file_write",
                "batch_edit": "file_write", "regex_replace": "file_write",
                "shell": "shell", "run_tests": "shell", "python_eval": "shell",
                "process_list": "shell", "kill_process": "shell",
                "web": "web_search", "fetch_url": "web_search",
                "weather": "web_search", "http_request": "web_search",
                "deep_research": "web_search", "multi_search": "web_search",
                "vision": "vision",
                "generate_image": "image_gen",
                "speak": "voice",
                "git_commit": "git", "git_checkout": "git",
                "git_stash": "git",
            }
            toggle = _tool_toggle_map.get(tool_name)
            tool_blocked = toggle is not None and not state.enabled_tools.get(toggle, True)

            if tool_blocked:
                tool_result = f"ERROR[blocked]: Tool '{tool_name}' is disabled by user. Use a different approach or skip this step."
                consecutive_failures += 1
            else:
                # Tier 4: Stream tool step progress (sanitize for log injection + redact secrets)
                ts = datetime.now().strftime("%H:%M:%S")
                safe_args = json.dumps(tool_args)[:80].replace('\n', '\\n').replace('\r', '')
                # Redact tokens/passwords/keys from logs
                import re as _re
                for _pat in (r'(token|password|key|secret|auth)["\']?\s*[:=]\s*["\']?[\w\-./]+',):
                    safe_args = _re.sub(_pat, r'\1=***', safe_args, flags=_re.IGNORECASE)
                state.progress_log.append(f"[{ts}]   [{self.name}] tool: {tool_name}({safe_args})")
                if reasoning:
                    safe_reason = reasoning[:100].replace('\n', '\\n').replace('\r', '')
                    state.progress_log.append(f"[{ts}]   [{self.name}] reasoning: {safe_reason}")

                tool_result = execute_tool(tool_name, tool_args)

                # Tier 4: Auto-validate code after write/edit operations
                if tool_name in ("write", "edit") and "ERROR" not in tool_result:
                    try:
                        file_path = tool_args.get("path", tool_args.get("file_path", ""))
                        if file_path and file_path.endswith('.py'):
                            from src.reasoning import validate_code_output
                            issues = validate_code_output(file_path)
                            if issues:
                                issue_text = "; ".join(issues)[:200]
                                tool_result += f"\n⚠ CODE VALIDATION: {issue_text}"
                                state.progress_log.append(f"[{ts}]   [{self.name}] validation: {issue_text[:80]}")
                    except Exception:
                        pass

                # Tier 1: Self-correction — track consecutive failures
                if "ERROR" in tool_result:
                    consecutive_failures += 1
                    # Log the error for visibility
                    state.progress_log.append(f"[{ts}]   [{self.name}] error: {tool_result[:120]}")
                else:
                    consecutive_failures = 0

            all_tool_outputs.append({"tool": tool_name, "args": tool_args, "result": tool_result[:2000]})

            # Feed result back to LLM with self-correction hint on failure
            messages.append({"role": "assistant", "content": reply})
            feedback = f"TOOL_RESULT ({tool_name}):\n{compress_tool_result(tool_result)}"
            if consecutive_failures >= 2:
                feedback += "\n\nWARNING: Multiple consecutive tool failures. Consider a different approach or provide your best answer with 'done'."
            messages.append({"role": "user", "content": feedback})

            # Bail out if too many consecutive failures
            if consecutive_failures >= 4:
                state.progress_log.append(f"[{ts}]   [{self.name}] Too many failures, forcing completion")
                break

        # Exhausted steps
        messages.append({"role": "user", "content": "You've used all available tool steps. Please provide your final answer now."})
        try:
            response = await loop.run_in_executor(
                None,
                lambda: self.llm_client.chat.completions.create(model=self.model, messages=messages),
            )
            state.total_llm_calls += 1
            output = response.choices[0].message.content
        except Exception as e:
            output = f"Error in final step: {e}"

        self.status = AgentStatus.SUCCESS
        return AgentResult(agent_name=self.name, status=AgentStatus.SUCCESS, output=output,
                         artifacts={"steps": self.max_tool_steps, "tool_outputs": all_tool_outputs, "exhausted": True},
                         token_cost=total_tokens)

    # ============================================================
    # Tier 1: Context Window Management
    # ============================================================

    @staticmethod
    def _summarize_message(content: str, max_chars: int = 2000) -> str:
        """Smart message summarization — preserve structure, compress middle."""
        if len(content) <= max_chars:
            return content
        # Preserve code blocks fully (they're usually the important part)
        code_blocks = []
        remaining = content
        import re
        for match in re.finditer(r'```[\s\S]*?```', content):
            code_blocks.append(match.group())
        code_total = sum(len(b) for b in code_blocks)
        if code_total > 0 and code_total < max_chars * 0.7:
            # Keep code blocks, summarize prose
            prose_budget = max_chars - code_total
            prose = re.sub(r'```[\s\S]*?```', '[CODE_BLOCK]', content)
            if len(prose) > prose_budget:
                prose = prose[:prose_budget // 2] + "\n[...middle omitted...]\n" + prose[-(prose_budget // 2):]
            # Restore code blocks
            for block in code_blocks:
                prose = prose.replace('[CODE_BLOCK]', block, 1)
            return prose
        # Default: keep head + tail
        head = content[:max_chars * 2 // 3]
        tail = content[-(max_chars // 3):]
        return f"{head}\n[...{len(content) - len(head) - len(tail)} chars omitted...]\n{tail}"

    # Cache static environment info (computed once)
    _cached_env: str | None = None

    @staticmethod
    def _build_environment_context() -> str:
        if BaseAgent._cached_env is not None:
            # Only refresh the timestamp
            from datetime import datetime
            now = datetime.now()
            return BaseAgent._cached_env.replace("__TIMESTAMP__", now.strftime('%A, %B %d, %Y at %I:%M %p').strip())

        from datetime import datetime
        import platform
        import os
        from src.config import EXPERTS

        try:
            import subprocess as _sp
            _r = _sp.run(['hostname', '-I'], capture_output=True, text=True, timeout=3)
            net_parts = _r.stdout.strip().split()
            network_ip = net_parts[0] if net_parts else 'unknown'
        except Exception:
            network_ip = 'unknown'

        BaseAgent._cached_env = (
            f"\n\nENVIRONMENT:\n"
            f"- Current date and time: __TIMESTAMP__\n"
            f"- Host: {platform.node()} ({platform.system()} {platform.release()}, {platform.machine()})\n"
            f"- User: {os.environ.get('USER', 'unknown')}\n"
            f"- Working directory: {os.getcwd()}\n"
            f"- Python: {platform.python_version()}\n"
            f"- Network: {network_ip}\n"
            f"\nYou are OmniAgent v{VERSION} — a modular autonomous AI agent framework running locally with 47 tools and 7 specialist agents.\n"
            f"You have multiple specialist agents: {', '.join(EXPERTS.keys())}.\n"
            f"Models: {', '.join(f'{k}={v}' for k,v in EXPERTS.items())}.\n"
            f"You have 47 tools across 8 categories: file I/O (read/write/edit/glob/grep/tree), "
            f"shell execution, web search (web/deep_research/fetch_url), git, media (vision/image gen/TTS), "
            f"system (process/network/docker), data (database/PDF/archive), and sub-agent spawning.\n"
            f"You can read/write/edit files on THIS machine. You run commands on THIS machine.\n"
            f"When asked about 'your system' or 'what OS', answer about THIS host — not in general terms.\n"
            f"When asked about GitHub, Google, etc — check if integrations are connected and use them.\n"
        )
        now = datetime.now()
        return BaseAgent._cached_env.replace("__TIMESTAMP__", now.strftime('%A, %B %d, %Y at %I:%M %p').strip())

    def _build_messages(self, task: str, context: str, conversation: list[dict] | None) -> list[dict]:
        system_content = self.system_prompt
        system_content += self._build_environment_context()
        if state.execution_mode == "teach":
            system_content += "\n\nYou are in TEACHING mode. Explain steps clearly so the user can learn. Show commands they would run but don't execute them."
        if state.user_system_prompt:
            system_content += f"\n\nUSER INSTRUCTIONS:\n{state.user_system_prompt}"
        if context:
            system_content += f"\n\nCONTEXT:\n{context}"
        messages = [{"role": "system", "content": system_content}]
        # Tier 1: More turns (10 instead of 6), smart summarization
        if conversation is None:
            conversation = state.get_recent_history(max_turns=10)
        if conversation:
            for msg in conversation:
                content = self._summarize_message(msg.get("content", ""))
                messages.append({"role": msg.get("role", "user"), "content": content})
        messages.append({"role": "user", "content": task})
        return messages
