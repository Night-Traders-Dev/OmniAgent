import os
from datetime import datetime
from src.config import PLAN_FILE, MEMORY_FILE
from src.state import state
from src.coordinator import Coordinator
from src.tools import read_file, write_file


class Supervisor:
    def __init__(self, coordinator: Coordinator):
        self.coord = coordinator

    def _log(self, message: str):
        ts = datetime.now().strftime("%H:%M:%S")
        state.progress_log.append(f"[{ts}] {message}")

    async def run(self, user_input: str) -> dict:
        self._log("Supervisor Initialized. Analyzing Workspace...")
        plan = read_file(PLAN_FILE)

        self._log("Routing task to specialized agents...")
        reply = await self.coord.execute_task(user_input, plan_context=plan)

        self._log("Verifying completion...")
        self._archive_plan(user_input)

        state.chat_history.append({"role": "user", "content": user_input})
        state.chat_history.append({"role": "assistant", "content": reply})
        state.save_session()

        self._log("Task Lifecycle Complete.")
        state.current_status = "Finished"
        return {"reply": reply}

    def _archive_plan(self, user_input: str):
        if not os.path.exists(PLAN_FILE):
            return
        plan_content = read_file(PLAN_FILE)
        if not plan_content.strip():
            return
        with open(MEMORY_FILE, "a") as f:
            f.write(f"\n## {datetime.now()}\nCompleted: {user_input}\n{plan_content}\n")
        write_file(PLAN_FILE, "")
