"""
Parallel BitNet Scheduler — intelligently runs lightweight tasks on BitNet (CPU)
concurrently with heavyweight tasks on Ollama (GPU).

Use cases:
- Pre-summarize search results on BitNet while GPU agent processes the main task
- Run classification/routing on BitNet while GPU model loads
- Parallel sub-task decomposition: simple subtasks on BitNet, complex on GPU
- Batch process multiple simple queries simultaneously on BitNet
"""
import asyncio
from datetime import datetime
from src.config import BITNET_CLIENT, BITNET_MODEL, BITNET_ENABLED
from src.state import state
from src.agents.base import BaseAgent, AgentResult, AgentStatus
import src.config as config


class BitNetAgent(BaseAgent):
    """A lightweight agent that always routes to BitNet regardless of model_key."""
    name = "bitnet"
    role = "fast parallel task execution"
    model_key = "fast"
    max_tool_steps = 0

    def __init__(self, task_name: str = "bitnet", prompt: str = ""):
        super().__init__()
        self.name = task_name
        if prompt:
            self.system_prompt = prompt


class ParallelScheduler:
    """
    Decides when and how to use BitNet for parallel execution.

    Strategies:
    - PARALLEL_PREFETCH: Run BitNet for quick context while GPU handles main task
    - PARALLEL_BATCH: Run multiple BitNet tasks concurrently
    - PARALLEL_ASSIST: BitNet does prep work, GPU does the heavy lifting
    """

    @staticmethod
    def is_available() -> bool:
        return config.BITNET_ENABLED

    @staticmethod
    def classify_task(task: str) -> str:
        """Classify a task as 'light' (BitNet-suitable) or 'heavy' (needs GPU).
        Light tasks: simple Q&A, formatting, classification, summarization.
        Heavy tasks: code generation, reasoning, tool use, long-form writing."""
        lower = task.lower()

        heavy_signals = [
            "write", "create", "build", "implement", "develop", "code",
            "debug", "fix", "refactor", "analyze", "explain in detail",
            "step by step", "exploit", "reverse engineer",
        ]
        if any(s in lower for s in heavy_signals):
            return "heavy"

        light_signals = [
            "summarize", "classify", "categorize", "format", "convert",
            "list", "name", "define", "translate", "count",
            "yes or no", "true or false", "which one",
            "short answer", "one word", "briefly",
        ]
        if any(s in lower for s in light_signals):
            return "light"

        # Default: short prompts are light, long ones are heavy
        return "light" if len(task) < 100 else "heavy"

    @staticmethod
    async def run_parallel_bitnet(tasks: list[dict]) -> list[AgentResult]:
        """Run multiple tasks on BitNet concurrently.

        Args:
            tasks: List of {"task": str, "system_prompt": str (optional), "name": str (optional)}

        Returns:
            List of AgentResult, one per task
        """
        if not config.BITNET_ENABLED:
            return [AgentResult(agent_name="bitnet", status=AgentStatus.FAILED,
                                error="BitNet is not enabled") for _ in tasks]

        ts = datetime.now().strftime("%H:%M:%S")
        task_names = ", ".join(t.get("name", "task") for t in tasks)
        state.progress_log.append(f"[{ts}] ⚡ BitNet: Running {len(tasks)} parallel CPU tasks [{task_names}]")

        async def run_one(task_spec: dict) -> AgentResult:
            agent = BitNetAgent(
                task_name=task_spec.get("name", "bitnet"),
                prompt=task_spec.get("system_prompt", "You are a fast, concise assistant. Be brief and precise."),
            )
            return await agent.execute(
                task_spec["task"],
                task_spec.get("context", ""),
                task_spec.get("conversation"),
            )

        results = await asyncio.gather(
            *[run_one(t) for t in tasks],
            return_exceptions=True,
        )

        final = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                final.append(AgentResult(
                    agent_name=tasks[i].get("name", "bitnet"),
                    status=AgentStatus.FAILED,
                    error=str(r),
                ))
            else:
                final.append(r)

        ts = datetime.now().strftime("%H:%M:%S")
        success = sum(1 for r in final if r.status == AgentStatus.SUCCESS)
        state.progress_log.append(f"[{ts}] ⚡ BitNet: {success}/{len(tasks)} parallel tasks completed")
        return final

    @staticmethod
    async def run_with_prefetch(
        main_task: str,
        main_agent: BaseAgent,
        prefetch_tasks: list[dict],
        context: str = "",
        conversation: list[dict] | None = None,
    ) -> tuple[AgentResult, list[AgentResult]]:
        """Run the main task on GPU while simultaneously running prefetch tasks on BitNet.

        Returns:
            (main_result, list_of_prefetch_results)
        """
        if not config.BITNET_ENABLED:
            # No BitNet — just run main task
            main_result = await main_agent.execute(main_task, context, conversation)
            return main_result, []

        ts = datetime.now().strftime("%H:%M:%S")
        state.progress_log.append(f"[{ts}] ⚡ BitNet: GPU + {len(prefetch_tasks)} CPU prefetch tasks in parallel")

        # Run both concurrently
        main_coro = main_agent.execute(main_task, context, conversation)
        bitnet_coro = ParallelScheduler.run_parallel_bitnet(prefetch_tasks)

        main_result, prefetch_results = await asyncio.gather(main_coro, bitnet_coro)
        return main_result, prefetch_results

    @staticmethod
    async def quick_classify(text: str) -> str:
        """Use BitNet to quickly classify/route a query. Returns raw LLM output."""
        if not config.BITNET_ENABLED:
            return ""
        agent = BitNetAgent(
            task_name="classifier",
            prompt="Classify the user's intent in one word. Options: code, security, research, question, task, chat.",
        )
        result = await agent.execute(text, "", [])
        return result.output.strip().lower() if result.status == AgentStatus.SUCCESS else ""

    @staticmethod
    async def quick_summarize(text: str, max_words: int = 50) -> str:
        """Use BitNet to quickly summarize text."""
        if not config.BITNET_ENABLED:
            return text[:200]
        agent = BitNetAgent(
            task_name="summarizer",
            prompt=f"Summarize the following in {max_words} words or fewer. Be concise.",
        )
        result = await agent.execute(text, "", [])
        return result.output if result.status == AgentStatus.SUCCESS else text[:200]
