"""Tests for agent routing, detection, context, and multi-step loops."""
import pytest
from src.agents.base import BaseAgent, AgentResult, AgentStatus
from src.agents.specialists import SPECIALIST_REGISTRY
from src.agents.orchestrator import Orchestrator


class TestSpecialistRegistry:
    def test_all_registered(self):
        for n in ["reasoner","coder","researcher","planner","tool_user"]:
            assert n in SPECIALIST_REGISTRY
    def test_subclasses(self):
        for _,cls in SPECIALIST_REGISTRY.items():
            assert issubclass(cls, BaseAgent)
    def test_names_match(self):
        for n,cls in SPECIALIST_REGISTRY.items():
            assert cls.name == n
    def test_roles(self):
        for _,cls in SPECIALIST_REGISTRY.items():
            assert len(cls.role) > 10
    def test_prompts(self):
        for _,cls in SPECIALIST_REGISTRY.items():
            assert len(cls.system_prompt) > 20


class TestMultiStepAgents:
    def test_coder_has_tool_steps(self):
        from src.agents.specialists import CodingAgent
        assert CodingAgent.max_tool_steps >= 5

    def test_researcher_has_tool_steps(self):
        from src.agents.specialists import ResearchAgent
        assert ResearchAgent.max_tool_steps >= 3

    def test_tool_user_has_tool_steps(self):
        from src.agents.specialists import ToolAgent
        assert ToolAgent.max_tool_steps >= 5

    def test_reasoner_has_tools(self):
        from src.agents.specialists import ReasoningAgent
        assert ReasoningAgent.max_tool_steps == 4  # Reasoner has read-only tool access


class TestOrchestratorRouting:
    def setup_method(self):
        self.orch = Orchestrator()
    def test_weather(self): assert self.orch._detect_simple_query("What is the weather?") == "researcher"
    def test_temperature(self): assert self.orch._detect_simple_query("current temperature Ashland KY") == "researcher"
    def test_price(self): assert self.orch._detect_simple_query("price of Bitcoin") == "researcher"
    def test_who(self): assert self.orch._detect_simple_query("Who is the president?") == "researcher"
    def test_code_no_fast(self): assert self.orch._detect_simple_query("Write a sort function") is None
    def test_generic_no_fast(self): assert self.orch._detect_simple_query("Refactor the module") is None


class TestOrchestratorContext:
    def setup_method(self):
        self.orch = Orchestrator()

    def test_resolve_no_ref(self):
        assert self.orch._resolve_references("What is the weather?") == "What is the weather?"

    def test_resolve_again(self):
        from src.state import state
        state.chat_history = [
            {"role":"user","content":"weather in London"},
            {"role":"assistant","content":"It's 15C in London"},
        ]
        r = self.orch._resolve_references("do that again but fahrenheit")
        assert "CONTEXT" in r and "London" in r
        state.chat_history.clear()

    def test_resolve_but(self):
        from src.state import state
        state.chat_history = [
            {"role":"user","content":"temp in Ashland KY"},
            {"role":"assistant","content":"69F Sunny"},
        ]
        r = self.orch._resolve_references("but in celsius")
        assert "CONTEXT" in r and "Ashland" in r
        state.chat_history.clear()

    def test_empty_context(self):
        from src.state import state
        state.chat_history.clear()
        assert self.orch._build_conversation_context() == ""


class TestBaseAgentMessages:
    def test_no_history(self):
        a = BaseAgent()
        msgs = a._build_messages("task", "ctx", conversation=[])
        assert msgs[0]["role"] == "system"
        assert msgs[-1]["content"] == "task"

    def test_with_conversation(self):
        a = BaseAgent()
        conv = [{"role":"user","content":"q1"},{"role":"assistant","content":"a1"}]
        msgs = a._build_messages("task", "", conversation=conv)
        assert len(msgs) == 4

    def test_truncates_long(self):
        a = BaseAgent()
        conv = [{"role":"user","content":"x"*5000}]
        msgs = a._build_messages("t", "", conversation=conv)
        assert "omitted" in msgs[1]["content"]

    def test_user_system_prompt(self):
        from src.state import state
        state.user_system_prompt = "Always respond in Spanish"
        a = BaseAgent()
        msgs = a._build_messages("hello", "", conversation=[])
        assert "Spanish" in msgs[0]["content"]
        state.user_system_prompt = ""

    def test_teach_mode_injected(self):
        from src.state import state
        state.execution_mode = "teach"
        a = BaseAgent()
        msgs = a._build_messages("hello", "", conversation=[])
        assert "TEACHING" in msgs[0]["content"]
        state.execution_mode = "execute"

    def test_execute_mode_no_teach(self):
        from src.state import state
        state.execution_mode = "execute"
        a = BaseAgent()
        msgs = a._build_messages("hello", "", conversation=[])
        assert "TEACHING" not in msgs[0]["content"]


class TestAgentResult:
    def test_success(self):
        r = AgentResult(agent_name="t", status=AgentStatus.SUCCESS, output="done")
        assert r.output == "done" and r.error is None
    def test_failed(self):
        r = AgentResult(agent_name="t", status=AgentStatus.FAILED, error="broke")
        assert r.error == "broke"
    def test_artifacts(self):
        r = AgentResult(agent_name="t", status=AgentStatus.SUCCESS, output="r", artifacts={"tool":"web"})
        assert r.artifacts["tool"] == "web"


# ============================================================
# Tool Awareness & Agent Knowledge Tests
# ============================================================

class TestToolReference:
    """Verify the comprehensive tool reference is complete and valid."""

    def test_reference_exists(self):
        from src.tools import TOOL_DETAILED_REFERENCE
        assert len(TOOL_DETAILED_REFERENCE) > 5000

    def test_all_47_tools_in_reference(self):
        from src.tools import TOOL_DETAILED_REFERENCE, TOOL_REGISTRY
        for tool_name in TOOL_REGISTRY:
            assert tool_name in TOOL_DETAILED_REFERENCE, f"Tool '{tool_name}' missing from TOOL_DETAILED_REFERENCE"

    def test_reference_has_json_examples(self):
        from src.tools import TOOL_DETAILED_REFERENCE
        # Every tool section should have at least one JSON example
        for tool in ["read", "write", "edit", "shell", "web", "grep", "glob", "tree",
                      "git_status", "git_commit", "deep_research", "weather", "done"]:
            assert f'"tool": "{tool}"' in TOOL_DETAILED_REFERENCE, f"No JSON example for '{tool}'"

    def test_reference_has_categories(self):
        from src.tools import TOOL_DETAILED_REFERENCE
        for cat in ["FILE READING", "FILE WRITING", "SHELL", "WEB", "GIT", "MEDIA", "SYSTEM", "CONTROL"]:
            assert cat in TOOL_DETAILED_REFERENCE, f"Missing category: {cat}"

    def test_build_tool_reference_all(self):
        from src.tools import build_tool_reference
        ref = build_tool_reference()
        assert len(ref) > 5000

    def test_build_tool_reference_subset(self):
        from src.tools import build_tool_reference
        ref = build_tool_reference(["read", "write", "edit"])
        assert "read" in ref and "write" in ref and "edit" in ref
        assert "shell" not in ref  # Not in the subset


class TestAgentToolAwareness:
    """Verify each agent's system prompt correctly describes its tools and role."""

    def test_coder_knows_edit_tools(self):
        from src.agents.specialists import CodingAgent
        prompt = CodingAgent.system_prompt
        for tool in ["edit", "write", "batch_edit", "regex_replace", "diff_preview"]:
            assert tool in prompt, f"Coder prompt missing tool: {tool}"

    def test_coder_explains_tool_choice(self):
        from src.agents.specialists import CodingAgent
        prompt = CodingAgent.system_prompt
        assert "CHOOSING THE RIGHT EDIT TOOL" in prompt

    def test_researcher_knows_search_tools(self):
        from src.agents.specialists import ResearchAgent
        prompt = ResearchAgent.system_prompt
        for tool in ["web", "deep_research", "multi_search", "fetch_url", "http_request", "weather"]:
            assert tool in prompt, f"Researcher prompt missing tool: {tool}"

    def test_researcher_prefers_deep_research(self):
        from src.agents.specialists import ResearchAgent
        prompt = ResearchAgent.system_prompt
        assert "deep_research" in prompt and "non-trivial" in prompt.lower()

    def test_planner_knows_analysis_tools(self):
        from src.agents.specialists import PlannerAgent
        prompt = PlannerAgent.system_prompt
        for tool in ["tree", "analyze_file", "project_deps", "find_symbol", "grep"]:
            assert tool in prompt, f"Planner prompt missing tool: {tool}"

    def test_tool_user_has_all_categories(self):
        from src.agents.specialists import ToolAgent
        prompt = ToolAgent.system_prompt
        for cat in ["FILES", "SHELL", "WEB", "GIT", "ANALYZE", "MEDIA", "SYSTEM", "DATA"]:
            assert cat in prompt, f"ToolUser prompt missing category: {cat}"

    def test_tool_user_has_quick_actions(self):
        from src.agents.specialists import ToolAgent
        prompt = ToolAgent.system_prompt
        assert "QUICK ACTIONS" in prompt

    def test_reasoner_knows_read_tools(self):
        from src.agents.specialists import ReasoningAgent
        prompt = ReasoningAgent.system_prompt
        for tool in ["read", "glob", "grep", "tree", "analyze_file", "find_symbol"]:
            assert tool in prompt, f"Reasoner prompt missing tool: {tool}"

    def test_security_no_tool_steps(self):
        from src.agents.specialists import SecurityAgent
        assert SecurityAgent.max_tool_steps == 0

    def test_fast_no_tool_steps(self):
        from src.agents.specialists import FastAgent
        assert FastAgent.max_tool_steps == 0


class TestDispatchPromptAwareness:
    """Verify the orchestrator dispatch prompt knows about all agents and their tools."""

    def test_dispatch_lists_all_agents(self):
        from src.agents.orchestrator import DISPATCH_PROMPT
        for agent in ["REASONER", "CODER", "RESEARCHER", "PLANNER", "TOOL_USER", "SECURITY", "FAST"]:
            assert agent in DISPATCH_PROMPT, f"Dispatch prompt missing agent: {agent}"

    def test_dispatch_lists_agent_tools(self):
        from src.agents.orchestrator import DISPATCH_PROMPT
        # Coder should list its key tools
        assert "edit" in DISPATCH_PROMPT and "write" in DISPATCH_PROMPT
        # Researcher should list its tools
        assert "deep_research" in DISPATCH_PROMPT and "weather" in DISPATCH_PROMPT

    def test_dispatch_has_routing_rules(self):
        from src.agents.orchestrator import DISPATCH_PROMPT
        assert "ROUTING RULES" in DISPATCH_PROMPT

    def test_dispatch_security_routing(self):
        from src.agents.orchestrator import DISPATCH_PROMPT
        assert "security" in DISPATCH_PROMPT.lower() and "NEVER" in DISPATCH_PROMPT

    def test_dispatch_has_output_format(self):
        from src.agents.orchestrator import DISPATCH_PROMPT
        assert "subtasks" in DISPATCH_PROMPT and "depends_on" in DISPATCH_PROMPT

    def test_dispatch_lists_tool_counts(self):
        from src.agents.orchestrator import DISPATCH_PROMPT
        # Each agent should list tool step count
        assert "30 tool steps" in DISPATCH_PROMPT  # coder
        assert "15 tool steps" in DISPATCH_PROMPT  # researcher
        assert "0 tool steps" in DISPATCH_PROMPT   # security/fast


class TestNPUFastRouting:
    """Verify NPU intent hints are extracted and used for fast routing."""

    def setup_method(self):
        self.orch = Orchestrator()

    def test_extract_npu_intent_present(self):
        ctx = "NPU PRE-ANALYSIS (from on-device Gemini Nano): intent=code, mood=neutral."
        assert self.orch._extract_npu_intent(ctx) == "code"

    def test_extract_npu_intent_absent(self):
        assert self.orch._extract_npu_intent("no npu data here") is None

    def test_npu_fast_route_code(self):
        ctx = "NPU PRE-ANALYSIS (from on-device Gemini Nano): intent=code, mood=neutral."
        result = self.orch._detect_simple_query("write a function", ctx)
        assert result == "coder"

    def test_npu_fast_route_question(self):
        ctx = "NPU PRE-ANALYSIS (from on-device Gemini Nano): intent=question, mood=neutral."
        result = self.orch._detect_simple_query("what is docker", ctx)
        assert result == "researcher"

    def test_npu_fast_route_debug(self):
        ctx = "NPU PRE-ANALYSIS (from on-device Gemini Nano): intent=debug, mood=negative."
        result = self.orch._detect_simple_query("fix the crash", ctx)
        assert result == "coder"

    def test_npu_fast_route_greeting(self):
        ctx = "NPU PRE-ANALYSIS (from on-device Gemini Nano): intent=greeting, mood=positive."
        result = self.orch._detect_simple_query("hello there", ctx)
        assert result == "fast"

    def test_npu_command_falls_through(self):
        # "command" intent is not in npu_map, should fall through to keyword detection
        ctx = "NPU PRE-ANALYSIS (from on-device Gemini Nano): intent=command, mood=neutral."
        result = self.orch._detect_simple_query("make it happen", ctx)
        # Should return None since "command" not in npu_map and no keyword match
        assert result is None


class TestEnvironmentContext:
    """Verify the environment context injected into all agents is correct."""

    def test_version_string(self):
        env = BaseAgent._build_environment_context()
        assert "v8.5.0" in env

    def test_tool_count(self):
        env = BaseAgent._build_environment_context()
        assert "47 tools" in env

    def test_agent_count(self):
        env = BaseAgent._build_environment_context()
        assert "7 specialist agents" in env

    def test_has_timestamp(self):
        env = BaseAgent._build_environment_context()
        # Should contain a date like "Monday, March 23"
        assert "202" in env  # Contains a year

    def test_has_host_info(self):
        env = BaseAgent._build_environment_context()
        assert "Host:" in env

    def test_has_tool_categories(self):
        env = BaseAgent._build_environment_context()
        assert "file I/O" in env or "shell execution" in env


class TestNPUHintParsing:
    """Verify server-side NPU hint parsing."""

    def test_parse_npu_hints_present(self):
        from src.web import _parse_npu_hints
        msg, ctx = _parse_npu_hints("[npu:intent=code,mood=neutral] write a function")
        assert msg == "write a function"
        assert "intent=code" in ctx
        assert "mood=neutral" in ctx

    def test_parse_npu_hints_absent(self):
        from src.web import _parse_npu_hints
        msg, ctx = _parse_npu_hints("plain message")
        assert msg == "plain message"
        assert ctx == ""

    def test_parse_npu_hints_strips_prefix(self):
        from src.web import _parse_npu_hints
        msg, _ = _parse_npu_hints("[npu:intent=debug,mood=negative] fix the bug in auth.py")
        assert msg == "fix the bug in auth.py"
        assert "[npu:" not in msg
