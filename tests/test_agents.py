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

    def test_reasoner_no_tools(self):
        from src.agents.specialists import ReasoningAgent
        assert ReasoningAgent.max_tool_steps == 0


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
