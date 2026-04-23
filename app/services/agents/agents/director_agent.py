from __future__ import annotations

from typing import Any

from app.services.agents.base import BaseAgent
from app.services.agents.schemas import DirectorAgentOutput
from app.services.agents.tools import build_director_response


class DirectorAgent(BaseAgent):
    name = "director"
    description = "Summarizes admin workload, blockers, and the next highest-priority actions."
    instructions = (
        "You are the WildEx Director Agent.\n\n"
        "Your only job is to summarize admin workload, blockers, and the next practical actions.\n"
        "Use queue state, review items, template health, and recent agent activity when provided.\n"
        "Do not invent hidden problems or modify state.\n"
        "Return only structured JSON matching the director response schema."
    )
    allowed_task_types = ("overview", "admin_request", "summarize_workload")
    output_model = DirectorAgentOutput

    def _run(self, task_type: str, payload: dict[str, Any], *, tool_context: dict[str, Any]) -> DirectorAgentOutput:
        return build_director_response(payload)

    def summarize(self, task_type: str, output: DirectorAgentOutput, payload: dict[str, Any]) -> str:
        return output.reply
