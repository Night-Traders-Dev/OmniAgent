"""
Parallel Orchestrator - the brain of the agentic framework.

Enhanced with:
- Tier 1: Planning with revision (reflect step between agent executions)
- Tier 1: Improved context management (more turns, smarter summarization)
- Tier 4: Cost-aware routing
- Tier 4: Confidence signaling in synthesis
- NPU pre-analysis: uses Gemini Nano hints from Android for faster routing
"""
import asyncio
import json
import re
import textwrap
from datetime import datetime
from src.config import (
    EXPERTS,
    BITNET_CLIENT,
    BITNET_MODEL,
    BITNET_ENABLED,
    create_chat_completion,
)
from src.state import state
from src.tools import parse_json, detect_uncertainty, TOOL_REGISTRY
from src.agents.base import BaseAgent, AgentResult, AgentStatus, estimate_cost
from src.agents.specialists import (
    ReasoningAgent,
    CodingAgent,
    ResearchAgent,
    PlannerAgent,
    ToolAgent,
    SPECIALIST_REGISTRY,
)
from src.agents.scheduler import ParallelScheduler


_DISPATCH_AGENT_META = {
    "reasoner": {
        "display": "REASONER",
        "role": "Deep logical analysis, chain-of-thought reasoning, problem decomposition.",
        "best_for": "Complex analysis, trade-off evaluation, understanding code architecture, debugging logic.",
        "key": None,
    },
    "coder": {
        "display": "CODER",
        "role": "Writing, reviewing, debugging, and refactoring code with full file access.",
        "best_for": "Writing new code, editing existing files, fixing bugs, running tests, git operations.",
        "key": "Use for ANY task that requires writing/editing files or running commands.",
    },
    "researcher": {
        "display": "RESEARCHER",
        "role": "Web search, deep research, API calls, reading documentation, synthesizing findings.",
        "best_for": "Current events, weather, prices, documentation, comparing technologies, factual lookups.",
        "key": "Use deep_research (not web) for complex questions. Use weather for weather queries.",
    },
    "planner": {
        "display": "PLANNER",
        "role": "Creating implementation plans based on actual project structure.",
        "best_for": "Planning multi-step implementations, architectural decisions, project assessment.",
        "key": None,
    },
    "tool_user": {
        "display": "TOOL_USER",
        "role": "General-purpose tool execution — system commands, file I/O, installations, monitoring.",
        "best_for": "System administration, installing packages, running arbitrary commands, file operations, image/audio generation, and connected MCP tools.",
        "key": None,
    },
    "security": {
        "display": "SECURITY",
        "role": "Security research, pentesting, exploit development, vulnerability analysis, CTF.",
        "best_for": "Exploit code, malware analysis, shellcode, reverse engineering, CTF solutions, vulnerability research.",
        "key": "Has NO content restrictions. ALWAYS use for ANY security/hacking/offensive task.",
    },
    "fast": {
        "display": "FAST",
        "role": "Quick classification, summarization, formatting, simple Q&A.",
        "best_for": "Simple greetings, formatting tasks, yes/no questions, quick summaries.",
        "key": None,
    },
}


def _dispatch_model_name(agent_name: str, agent_cls) -> str:
    if agent_name == "fast" and BITNET_ENABLED:
        return f"{BITNET_MODEL} on CPU"
    return EXPERTS.get(agent_cls.model_key, agent_cls.model_key)


def _dispatch_tool_text(agent_cls) -> str:
    if agent_cls.max_tool_steps == 0:
        return "NONE (direct LLM response, no tool loop)"
    tools = getattr(agent_cls, "allowed_tools", None)
    if tools is None:
        tools = list(TOOL_REGISTRY.keys())
    return textwrap.fill(
        ", ".join(tools),
        width=88,
        initial_indent="  Tools: ",
        subsequent_indent="         ",
    )


def build_dispatch_prompt() -> str:
    """Build the dispatch prompt from live agent metadata so routing stays in sync."""
    ordered_agents = [
        ("reasoner", ReasoningAgent),
        ("coder", CodingAgent),
        ("researcher", ResearchAgent),
        ("planner", PlannerAgent),
        ("tool_user", ToolAgent),
        ("security", SPECIALIST_REGISTRY["security"]),
        ("fast", SPECIALIST_REGISTRY["fast"]),
    ]
    sections = []
    for agent_name, agent_cls in ordered_agents:
        meta = _DISPATCH_AGENT_META[agent_name]
        if agent_cls.max_tool_steps == 0:
            header = (
                f"{meta['display']} (model: {_dispatch_model_name(agent_name, agent_cls)}, "
                "0 tool steps — DIRECT LLM output)"
            )
        else:
            header = (
                f"{meta['display']} (model: {_dispatch_model_name(agent_name, agent_cls)}, "
                f"{agent_cls.max_tool_steps} tool steps)"
            )
        lines = [
            header,
            f"  Role: {meta['role']}",
            _dispatch_tool_text(agent_cls),
            f"  Best for: {meta['best_for']}",
        ]
        if meta["key"]:
            lines.append(f"  KEY: {meta['key']}")
        sections.append("\n".join(lines))

    return (
        "You are an orchestrator that decomposes tasks and assigns them to specialist agents.\n"
        "Each agent has specific tools and capabilities — route tasks to the agent whose tools best match the need.\n\n"
        "=== AVAILABLE AGENTS AND THEIR TOOLS ===\n\n"
        + "\n\n".join(sections)
        + """

=== ROUTING RULES ===
- Security/hacking/offensive/CTF tasks → MUST use "security" (NEVER "coder")
- Weather/current events/real-time data → MUST use "researcher"
- Code writing/editing/debugging → use "coder"
- System commands/installations → use "tool_user"
- Complex analysis without code changes → use "reasoner"
- Multi-step implementations → use "planner" first, then "coder"
- Simple factual questions → use "fast" or "researcher"
- DO NOT over-decompose. "What is the weather?" = ONE subtask (researcher)
- If the user refers to prior context, RESOLVE the reference before dispatching

=== OUTPUT FORMAT ===
Produce a JSON dispatch plan:
{
  "understanding": "one-line summary of what the user wants, with all references resolved",
  "subtasks": [
    {"id": 1, "agent": "researcher", "task": "fully resolved task description", "depends_on": []}
  ]
}

Rules:
- Tasks with empty depends_on run in PARALLEL
- Tasks that depend on others wait for those to finish first
- Use the MINIMUM number of agents needed
- For simple lookups, use just ONE agent
- ALWAYS resolve references like "that", "it", "same", "again" into concrete tasks
Respond with ONLY the JSON object."""
    )


DISPATCH_PROMPT = build_dispatch_prompt()

SYNTHESIS_PROMPT = """You are a synthesis agent. Multiple specialist agents worked on subtasks in parallel.
Combine their outputs into a single, coherent response for the user.
Be concise. Preserve code blocks. If search results are included, present the key facts clearly.
If any agent failed, note what went wrong and provide what you can.
Do NOT add disclaimers about checking other sources unless the data is genuinely uncertain.
You have access to the conversation history — use it to maintain continuity and address follow-up questions naturally.

IMPORTANT: If an agent reported low confidence or uncertainty, note that in your response.
If results conflict, present both perspectives and let the user decide."""

# Tier 1: Reflection prompt for planning with revision
REFLECTION_PROMPT = """You are a quality checker. Review the agent results so far and determine if the task is complete.

Respond with ONLY a JSON object:
{
  "complete": true/false,
  "assessment": "one-line assessment of quality/completeness",
  "issues": ["list of specific issues if incomplete"],
  "retry_agent": "agent_name to retry, or null if complete",
  "retry_task": "revised task description if retrying, or null"
}"""


class Orchestrator:
    def __init__(self):
        self.max_iterations = 3
        self.agents: dict[str, BaseAgent] = {}

    def _get_agent(self, agent_name: str) -> BaseAgent:
        if agent_name not in self.agents:
            agent_class = SPECIALIST_REGISTRY.get(agent_name)
            if agent_class:
                self.agents[agent_name] = agent_class()
            else:
                self.agents[agent_name] = BaseAgent()
        return self.agents[agent_name]

    def _build_conversation_context(self) -> str:
        # Tier 1: Increased context to 10 turns
        return state.format_history_context(max_turns=10)

    def _get_conversation_messages(self) -> list[dict]:
        return state.get_recent_history(max_turns=10)

    def _resolve_references(self, user_input: str) -> str:
        lower = user_input.lower().strip()
        reference_words = ["again", "same", "that", "it", "this", "those", "do it",
                           "the same", "but ", "instead", "also", "too"]
        if not any(word in lower for word in reference_words):
            return user_input
        recent = state.get_recent_history(max_turns=3)
        if not recent:
            return user_input
        last_user = ""
        last_assistant = ""
        for msg in reversed(recent):
            if msg["role"] == "assistant" and not last_assistant:
                last_assistant = msg["content"][:300]
            elif msg["role"] == "user" and not last_user:
                last_user = msg["content"]
            if last_user and last_assistant:
                break
        if last_user:
            return f"{user_input}\n\n[CONTEXT: The user previously asked: \"{last_user}\". The response was about: \"{last_assistant[:200]}\"]"
        return user_input

    @staticmethod
    def _extract_npu_intent(context: str) -> str | None:
        """Extract NPU pre-classified intent from context if present."""
        m = re.search(r"NPU PRE-ANALYSIS.*?intent=(\w+)", context)
        return m.group(1) if m else None

    def _detect_simple_query(self, user_input: str, context: str = "") -> str | None:
        # If NPU already classified intent, use it for fast routing
        npu_intent = self._extract_npu_intent(context)
        if npu_intent:
            npu_map = {
                "code": "coder",
                "debug": "coder",
                "question": "researcher",
                "summarize": "reasoner",
                "greeting": "fast",
            }
            if npu_intent in npu_map:
                self._log(f"⚡ NPU: Fast-route → {npu_map[npu_intent]} (intent={npu_intent})")
                return npu_map[npu_intent]

        lower = user_input.lower().strip()

        security_keywords = [
            "exploit", "payload", "vulnerab", "cve-", "0day", "zero day",
            "proof of concept", "poc", "shellcode", "buffer overflow",
            "heap overflow", "stack overflow", "use after free", "rop chain",
            "return oriented", "format string", "integer overflow",
            "pentest", "penetration test", "red team", "attack vector",
            "privilege escalation", "priv esc", "lateral movement",
            "port scan", "nmap", "metasploit", "burp", "wireshark",
            "packet craft", "packet sniff", "mitm", "man in the middle",
            "arp spoof", "dns spoof", "network intercept",
            "sql injection", "sqli", "xss", "csrf", "ssrf", "rce",
            "remote code execution", "command injection", "lfi", "rfi",
            "directory traversal", "path traversal", "deserialization",
            "malware", "rootkit", "backdoor", "keylogger", "trojan",
            "ransomware", "worm", "virus", "rat ", "remote access trojan",
            "persistence mechanism", "evasion", "obfuscat", "packer",
            "crypter", "dropper", "stager", "implant", "beacon",
            "elf infect", "pe infect", "code injection", "dll inject",
            "process inject", "hook", "detour", "entry point obscur",
            "reverse engineer", "disassembl", "decompil", "binary analys",
            "ida pro", "ghidra", "radare", "gdb exploit", "pwntools",
            "brute force", "hash crack", "john the ripper", "hashcat",
            "rainbow table", "credential stuff", "password spray",
            "ctf", "capture the flag", "pwn challeng", "rev challeng",
            "security audit", "hardening", "fuzzing", "fuzzer",
            "yara rule", "yara", "sigma rule", "detection signature",
            "incident response", "forensic", "c2 ", "c2 beacon",
            "command and control", "covert channel",
        ]
        if any(kw in lower for kw in security_keywords):
            return "security"

        realtime_keywords = [
            "weather", "temperature", "current", "today", "right now",
            "price of", "stock", "news", "latest", "how much",
            "who is", "what is", "where is", "when is", "when did",
            "how do i", "how to", "define", "meaning of",
        ]
        if any(kw in lower for kw in realtime_keywords):
            return "researcher"

        system_keywords = [
            "operating system", "what os", "my system", "my computer",
            "my github", "my repos", "my files", "my drive",
            "disk space", "memory usage", "cpu usage", "uptime",
            "installed", "running process", "list files",
            "what version", "system info",
        ]
        if any(kw in lower for kw in system_keywords):
            return "tool_user"

        return None

    async def dispatch(self, user_input: str, context: str = "") -> dict:
        state.current_status = "Planning..."
        state.begin_task()

        conv_context = self._build_conversation_context()
        conv_messages = self._get_conversation_messages()
        full_context = f"{conv_context}\n\n{context}".strip() if conv_context else context
        resolved_input = self._resolve_references(user_input)

        # Load project-level context (CLAUDE.md etc.)
        try:
            from src.advanced import load_project_context
            project_ctx = load_project_context()
            if project_ctx:
                full_context = f"{project_ctx}\n\n{full_context}"
        except Exception:
            pass

        # Tier 2: RAG — retrieve relevant codebase context
        try:
            from src.reasoning import retrieve_context
            rag_context = retrieve_context(resolved_input)
            if rag_context:
                full_context = f"{rag_context}\n\n{full_context}"
                self._log("Orchestrator: RAG context injected")
        except Exception:
            pass

        # Tier 5: Structured reasoning chain for complex tasks
        try:
            from src.reasoning import should_use_reasoning_chain, structured_reasoning_chain
            if should_use_reasoning_chain(resolved_input):
                self._log("Orchestrator: Complex task detected — using structured reasoning chain")
                state.total_steps = 6
                chain_result = await structured_reasoning_chain(resolved_input, full_context, conv_messages)
                final_reply = chain_result.get('final_output', '')
                if final_reply:
                    state.chat_history.append({"role": "user", "content": user_input})
                    state.chat_history.append({"role": "assistant", "content": final_reply})
                    state.save_session()
                    state.current_status = "Finished"
                    state.finish_task()
                    return {"reply": final_reply}
        except Exception as e:
            self._log(f"Orchestrator: Reasoning chain failed ({e}), continuing with standard dispatch")

        # Fast path
        fast_agent = self._detect_simple_query(resolved_input, full_context)
        if fast_agent:
            self._log(f"Orchestrator: Fast-routing to {fast_agent}")
            state.total_steps = 2
            state.advance_step(f"Running: {fast_agent}", model=EXPERTS.get("general", ""), agents=[fast_agent])
            state.current_status = f"Running: {fast_agent}"

            agent = self._get_agent(fast_agent)
            result = await agent.execute(resolved_input, full_context, conv_messages)
            self._log(f"  [{result.agent_name}] {result.status.value} (confidence: {result.confidence:.0%})")

            if fast_agent == "security":
                final_reply = result.output
                self._log("Orchestrator: Security output — bypassing synthesis")
            else:
                state.current_status = "Synthesizing..."
                state.advance_step("Synthesizing", model=EXPERTS["general"], agents=[])
                self._log("Orchestrator: Synthesizing...")
                final_reply = await self._synthesize(user_input, [result], conv_messages)

            # Tier 4: Confidence signaling — prepend warning if low confidence
            if result.confidence < 0.5:
                final_reply = f"*Note: This response has lower confidence — verify critical details.*\n\n{final_reply}"

            state.chat_history.append({"role": "user", "content": user_input})
            state.chat_history.append({"role": "assistant", "content": final_reply})
            state.save_session()
            self._log("Orchestrator: Task complete.")
            state.current_status = "Finished"
            state.finish_task()
            return {"reply": final_reply}

        # Full dispatch path
        self._log("Orchestrator: Decomposing task into subtasks...")
        state.advance_step("Planning", model=EXPERTS["general"])
        dispatch_plan = await self._create_dispatch_plan(resolved_input, full_context, conv_messages)
        if not dispatch_plan:
            return await self._fallback_single_agent(resolved_input, full_context, conv_messages)

        # Tier 4: Cost estimation
        subtasks = dispatch_plan.get("subtasks", [])
        total_cost = sum(
            estimate_cost(
                self._get_agent(t.get("agent", "general")).model_key,
                len(t.get("task", ""))
            )
            for t in subtasks
        )
        self._log(f"Orchestrator: Estimated cost: {total_cost} units for {len(subtasks)} subtasks")

        understanding = dispatch_plan.get("understanding", "")
        state.total_steps = len(subtasks) + 2
        self._log(f"Orchestrator: {len(subtasks)} subtasks — {understanding}")

        results = await self._execute_dispatch_plan(subtasks, full_context, conv_messages)

        # ============================================================
        # Tier 1: Planning with Revision — reflect before synthesizing
        # ============================================================
        reflection = await self._reflect_on_results(user_input, results, conv_messages)
        if reflection and not reflection.get("complete", True) and reflection.get("retry_agent"):
            retry_agent_name = reflection["retry_agent"]
            retry_task = reflection.get("retry_task", user_input)
            self._log(f"Orchestrator: Reflection — retrying with {retry_agent_name}: {reflection.get('assessment', '')}")
            state.advance_step(f"Retrying: {retry_agent_name}", agents=[retry_agent_name])

            # Build context from previous results
            prior_context = "\n".join(
                f"[{r.agent_name}]: {r.output[:500]}" for r in results if r.output
            )
            retry_agent = self._get_agent(retry_agent_name)
            retry_result = await retry_agent.execute(
                retry_task,
                f"{full_context}\n\nPRIOR ATTEMPT RESULTS:\n{prior_context}\n\nISSUES: {', '.join(reflection.get('issues', []))}",
                conv_messages,
            )
            results.append(retry_result)
            self._log(f"  [{retry_result.agent_name}] retry: {retry_result.status.value}")

        state.current_status = "Synthesizing..."
        state.advance_step("Synthesizing", model=EXPERTS["general"], agents=[])
        self._log("Orchestrator: Synthesizing agent outputs...")
        final_reply = await self._synthesize(user_input, results, conv_messages)

        # Confidence check on all results
        avg_confidence = sum(r.confidence for r in results) / len(results) if results else 1.0
        if avg_confidence < 0.5:
            final_reply = f"*Note: Agent confidence is lower than usual — verify critical details.*\n\n{final_reply}"

        state.chat_history.append({"role": "user", "content": user_input})
        state.chat_history.append({"role": "assistant", "content": final_reply})
        state.save_session()
        self._log("Orchestrator: Task complete.")
        state.current_status = "Finished"
        state.finish_task()
        return {"reply": final_reply}

    async def _create_dispatch_plan(self, user_input: str, context: str, conversation: list[dict]) -> dict | None:
        loop = asyncio.get_event_loop()
        try:
            messages = [{"role": "system", "content": build_dispatch_prompt()}]
            for msg in conversation[-8:]:
                messages.append(msg)
            messages.append({"role": "user", "content": f"CONTEXT:\n{context}\n\nUSER REQUEST:\n{user_input}"})

            if BITNET_ENABLED:
                self._log("⚡ BitNet: Planning dispatch on CPU (bitnet-2b, 1.58-bit)")
                client = BITNET_CLIENT
                model = BITNET_MODEL
                completion_call = lambda: client.chat.completions.create(
                    model=model,
                    messages=messages,
                    response_format={"type": "json_object"},
                )
            else:
                model = EXPERTS["general"]
                completion_call = lambda: create_chat_completion(
                    model=model,
                    model_key="general",
                    messages=messages,
                    response_format={"type": "json_object"},
                )

            response_data = await loop.run_in_executor(None, completion_call)
            state.total_llm_calls += 1
            if BITNET_ENABLED:
                response = response_data
            else:
                response, model = response_data
            plan = parse_json(response.choices[0].message.content)

            if BITNET_ENABLED and plan:
                subtask_count = len(plan.get("subtasks", []))
                agents_used = ", ".join(set(t.get("agent", "?") for t in plan.get("subtasks", [])))
                self._log(f"⚡ BitNet: Plan created — {subtask_count} subtask(s) → [{agents_used}]")

            # Tier 1: Validate dispatch plan schema
            if plan and "subtasks" in plan:
                valid_agents = set(SPECIALIST_REGISTRY.keys())
                for task in plan["subtasks"]:
                    if task.get("agent") not in valid_agents:
                        self._log(f"Orchestrator: Invalid agent '{task.get('agent')}' in plan, fixing to 'reasoner'")
                        task["agent"] = "reasoner"
                    if "id" not in task:
                        task["id"] = plan["subtasks"].index(task) + 1
                    if "depends_on" not in task:
                        task["depends_on"] = []
            return plan
        except Exception as e:
            self._log(f"Orchestrator: Plan generation failed — {e}")
            if BITNET_ENABLED:
                self._log("⚡ BitNet: Plan generation failed, falling back to GPU model")
                try:
                    response, _ = await loop.run_in_executor(
                        None,
                        lambda: create_chat_completion(
                            model=EXPERTS["general"],
                            model_key="general",
                            messages=messages,
                            response_format={"type": "json_object"},
                        ),
                    )
                    state.total_llm_calls += 1
                    return parse_json(response.choices[0].message.content)
                except Exception as e2:
                    self._log(f"Orchestrator: Fallback also failed — {e2}")
            return None

    async def _execute_dispatch_plan(self, subtasks: list[dict], context: str, conversation: list[dict]) -> list[AgentResult]:
        completed: dict[int, AgentResult] = {}
        remaining = list(subtasks)

        while remaining:
            ready = [t for t in remaining if all(d in completed for d in t.get("depends_on", []))]
            if not ready:
                # Tier 1: Better deadlock handling
                self._log("Orchestrator: Deadlock detected — forcing first remaining task")
                ready = remaining[:1]
                # Clear dependencies on this task so it can run
                ready[0]["depends_on"] = []

            parallel_tasks = []
            for task_spec in ready:
                agent = self._get_agent(task_spec.get("agent", "general"))
                dep_context = "\n".join(
                    f"[{completed[d].agent_name}]: {completed[d].output}"
                    for d in task_spec.get("depends_on", [])
                    if d in completed
                )
                full_context = f"{context}\n\nPRIOR RESULTS:\n{dep_context}" if dep_context else context
                parallel_tasks.append((task_spec, agent, full_context))

            agent_names = [t[0].get("agent") for t in parallel_tasks]
            agent_models = [self._get_agent(n).model for n in agent_names]
            state.current_status = f"Running: {', '.join(agent_names)}"
            state.advance_step(
                f"Agents: {', '.join(agent_names)}",
                model=agent_models[0] if len(agent_models) == 1 else ", ".join(set(agent_models)),
                agents=agent_names,
            )
            self._log(f"Orchestrator: Dispatching parallel — [{', '.join(agent_names)}]")

            coros = [
                agent.execute(task_spec["task"], ctx, conversation)
                for task_spec, agent, ctx in parallel_tasks
            ]
            results = await asyncio.gather(*coros, return_exceptions=True)

            for (task_spec, _, _), result in zip(parallel_tasks, results):
                task_id = task_spec.get("id", id(task_spec))
                if isinstance(result, Exception):
                    completed[task_id] = AgentResult(
                        agent_name=task_spec.get("agent", "unknown"),
                        status=AgentStatus.FAILED, error=str(result),
                    )
                else:
                    # Tier 3: Review-revise for coder outputs
                    if task_spec.get("agent") == "coder" and result.status == AgentStatus.SUCCESS and len(result.output) > 50:
                        try:
                            from src.reasoning import review_and_revise
                            review = await review_and_revise(task_spec["task"], result.output, context)
                            if review.get("reviewed") and review.get("output"):
                                result = AgentResult(
                                    agent_name=result.agent_name,
                                    status=result.status,
                                    output=review["output"],
                                    confidence=min(result.confidence + 0.1, 1.0),
                                    token_cost=result.token_cost,
                                )
                        except Exception:
                            pass
                    completed[task_id] = result
                    self._log(f"  [{result.agent_name}] {result.status.value} (confidence: {result.confidence:.0%}, cost: {result.token_cost})")

            for task_spec in ready:
                remaining.remove(task_spec)

        return list(completed.values())

    # ============================================================
    # Tier 1: Planning with Revision — Reflection
    # ============================================================

    async def _reflect_on_results(self, user_input: str, results: list[AgentResult], conversation: list[dict]) -> dict | None:
        """Check if the task is complete or needs revision."""
        # Skip reflection for single, successful results
        if len(results) == 1 and results[0].status == AgentStatus.SUCCESS and results[0].confidence > 0.7:
            return None
        # Skip reflection if all results failed (nothing to reflect on)
        if all(r.status == AgentStatus.FAILED for r in results):
            return None

        loop = asyncio.get_event_loop()
        results_summary = "\n".join(
            f"[{r.agent_name}] status={r.status.value} confidence={r.confidence:.0%}: {(r.output or r.error or '')[:300]}"
            for r in results
        )
        try:
            response, _ = await loop.run_in_executor(
                None,
                lambda: create_chat_completion(
                    model=EXPERTS["general"],
                    model_key="general",
                    messages=[
                        {"role": "system", "content": REFLECTION_PROMPT},
                        {"role": "user", "content": f"USER REQUEST: {user_input}\n\nAGENT RESULTS:\n{results_summary}"},
                    ],
                    response_format={"type": "json_object"},
                ),
            )
            state.total_llm_calls += 1
            reflection = parse_json(response.choices[0].message.content)
            if reflection:
                self._log(f"Orchestrator: Reflection — complete={reflection.get('complete')}, assessment={reflection.get('assessment', '')[:80]}")
            return reflection
        except Exception as e:
            self._log(f"Orchestrator: Reflection failed — {e}")
            return None

    async def _synthesize(self, user_input: str, results: list[AgentResult], conversation: list[dict]) -> str:
        loop = asyncio.get_event_loop()
        results_text = "\n\n".join(
            f"### [{r.agent_name}] (status: {r.status.value}, confidence: {r.confidence:.0%})\n{r.output or r.error or 'No output'}"
            for r in results
        )
        try:
            messages = [{"role": "system", "content": SYNTHESIS_PROMPT}]
            for msg in conversation[-8:]:
                messages.append(msg)
            messages.append({
                "role": "user",
                "content": f"CURRENT REQUEST: {user_input}\n\nAGENT RESULTS:\n{results_text}",
            })
            response, _ = await loop.run_in_executor(
                None,
                lambda: create_chat_completion(
                    model=EXPERTS["general"],
                    model_key="general",
                    messages=messages,
                ),
            )
            state.total_llm_calls += 1
            return response.choices[0].message.content
        except Exception as e:
            return f"Synthesis failed: {e}\n\nRaw results:\n{results_text}"

    async def _fallback_single_agent(self, user_input: str, context: str, conversation: list[dict]) -> dict:
        self._log("Orchestrator: Falling back to single-agent mode")
        state.total_steps = 1
        state.advance_step("Single-agent fallback", model=EXPERTS["reasoning"], agents=["reasoner"])
        agent = self._get_agent("reasoner")
        result = await agent.execute(user_input, context, conversation)
        state.chat_history.append({"role": "user", "content": user_input})
        state.chat_history.append({"role": "assistant", "content": result.output})
        state.save_session()
        self._log("Orchestrator: Task complete.")
        state.current_status = "Finished"
        state.finish_task()
        return {"reply": result.output}

    async def dispatch_streaming(self, user_input: str, context: str = ""):
        state.current_status = "Planning..."
        state.begin_task()

        conv_context = self._build_conversation_context()
        conv_messages = self._get_conversation_messages()
        full_context = f"{conv_context}\n\n{context}".strip() if conv_context else context
        resolved_input = self._resolve_references(user_input)

        # Inject RAG context
        try:
            from src.reasoning import retrieve_context
            rag_context = retrieve_context(resolved_input)
            if rag_context:
                full_context = f"{rag_context}\n\n{full_context}"
        except Exception:
            pass

        # Check for reasoning chain (complex tasks)
        try:
            from src.reasoning import should_use_reasoning_chain, structured_reasoning_chain
            if should_use_reasoning_chain(resolved_input):
                self._log("Orchestrator: Complex task — streaming reasoning chain")
                state.total_steps = 6
                chain_result = await structured_reasoning_chain(resolved_input, full_context, conv_messages)
                final_output = chain_result.get('final_output', '')
                if final_output:
                    # Stream the final output token-by-token
                    for token in final_output.split(' '):
                        yield token + ' '
                    state.chat_history.append({"role": "user", "content": user_input})
                    state.chat_history.append({"role": "assistant", "content": final_output})
                    state.save_session()
                    state.current_status = "Finished"
                    state.finish_task()
                    return
        except Exception as e:
            self._log(f"Orchestrator: Reasoning chain failed ({e})")

        fast_agent = self._detect_simple_query(resolved_input, full_context)
        if fast_agent:
            self._log(f"Orchestrator: Fast-routing to {fast_agent}")
            state.total_steps = 2
            state.advance_step(f"Running: {fast_agent}", model=EXPERTS.get("general", ""), agents=[fast_agent])
            state.current_status = f"Running: {fast_agent}"

            agent = self._get_agent(fast_agent)
            result = await agent.execute(resolved_input, full_context, conv_messages)
            self._log(f"  [{result.agent_name}] {result.status.value}")
            results = [result]
        else:
            self._log("Orchestrator: Decomposing task into subtasks...")
            state.advance_step("Planning", model=EXPERTS["general"])
            dispatch_plan = await self._create_dispatch_plan(resolved_input, full_context, conv_messages)
            if not dispatch_plan:
                agent = self._get_agent("reasoner")
                result = await agent.execute(resolved_input, full_context, conv_messages)
                results = [result]
            else:
                subtasks = dispatch_plan.get("subtasks", [])
                state.total_steps = len(subtasks) + 2
                results = await self._execute_dispatch_plan(subtasks, full_context, conv_messages)

        state.current_status = "Synthesizing..."
        state.advance_step("Synthesizing", model=EXPERTS["general"], agents=[])
        self._log("Orchestrator: Streaming synthesis...")

        full_reply = []
        async for token in self._synthesize_streaming(user_input, results, conv_messages):
            full_reply.append(token)
            yield token

        final_reply = "".join(full_reply)
        state.chat_history.append({"role": "user", "content": user_input})
        state.chat_history.append({"role": "assistant", "content": final_reply})
        state.save_session()
        self._log("Orchestrator: Task complete.")
        state.current_status = "Finished"
        state.finish_task()

    async def _synthesize_streaming(self, user_input: str, results: list[AgentResult], conversation: list[dict]):
        loop = asyncio.get_event_loop()
        results_text = "\n\n".join(
            f"### [{r.agent_name}] (status: {r.status.value})\n{r.output or r.error or 'No output'}"
            for r in results
        )
        messages = [{"role": "system", "content": SYNTHESIS_PROMPT}]
        for msg in conversation[-8:]:
            messages.append(msg)
        messages.append({"role": "user", "content": f"CURRENT REQUEST: {user_input}\n\nAGENT RESULTS:\n{results_text}"})

        try:
            response, _ = await loop.run_in_executor(
                None,
                lambda: create_chat_completion(
                    model=EXPERTS["general"],
                    model_key="general",
                    messages=messages,
                    stream=True,
                ),
            )
            state.total_llm_calls += 1
            for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            yield f"\n[Synthesis error: {e}]"

    def _log(self, message: str):
        ts = datetime.now().strftime("%H:%M:%S")
        state.progress_log.append(f"[{ts}] {message}")
