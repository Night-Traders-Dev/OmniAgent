import os
import asyncio
from src.config import CLIENT, EXPERTS, SYSTEM_PROMPT, PLAN_FILE
from src.state import state
from src.tools import parse_json, read_file, write_file, run_shell, web_search


class Coordinator:
    async def execute_task(self, user_input: str, plan_context: str = "") -> str:
        loop = asyncio.get_event_loop()

        auto_context = self._gather_file_context(user_input)

        route_prompt = (
            "Respond ONLY JSON.\n"
            f"CURRENT_PLAN: {plan_context}\n"
            "SCHEMA: {'expert': 'coding|reasoning|general', "
            "'tool': 'shell|web|write|read|none', "
            "'arg': 'path_or_cmd_or_query', 'content': 'file_body', "
            "'plan': 'updated_steps'}"
        )

        raw_route = await loop.run_in_executor(
            None,
            lambda: CLIENT.chat.completions.create(
                model=EXPERTS["general"],
                messages=[
                    {"role": "system", "content": route_prompt},
                    {"role": "user", "content": f"{auto_context}\n\nREQ: {user_input}"},
                ],
                response_format={"type": "json_object"},
            ),
        )
        data = parse_json(raw_route.choices[0].message.content) or {}

        if data.get("plan"):
            write_file(PLAN_FILE, data["plan"])

        tool_result = self._execute_tool(data)

        expert_model = EXPERTS.get(data.get("expert"), EXPERTS["general"])
        final_response = await loop.run_in_executor(
            None,
            lambda: CLIENT.chat.completions.create(
                model=expert_model,
                messages=[
                    {
                        "role": "system",
                        "content": f"{SYSTEM_PROMPT}\n{auto_context}\nTOOL: {tool_result}",
                    },
                    {"role": "user", "content": user_input},
                ],
            ),
        )
        return final_response.choices[0].message.content

    def _gather_file_context(self, user_input: str) -> str:
        context = ""
        for word in user_input.split():
            clean = word.strip(".,!?;:'\"")
            if os.path.isfile(clean):
                context += f"\nFILE_CONTENT ({clean}):\n{read_file(clean)}"
        return context

    def _execute_tool(self, data: dict) -> str:
        tool = data.get("tool", "none")
        arg = data.get("arg", "").strip()

        if tool == "write" and arg:
            if write_file(arg, data.get("content", "")):
                return f"SUCCESS: Wrote {arg}"
        elif tool == "read" and arg:
            return f"CONTENT: {read_file(arg)}"
        elif tool == "shell" and arg:
            result = run_shell(arg)
            state.cmd_history.append(arg)
            return result
        elif tool == "web" and arg:
            return web_search(arg)
        return ""
