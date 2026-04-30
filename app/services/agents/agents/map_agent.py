from __future__ import annotations

from typing import Any

from app.services.agents.base import BaseAgent
from app.services.agents.schemas import MapAgentOutput
from app.services.agents.tools import inspect_map_progress


class MapAgent(BaseAgent):
    name = "map"
    description = "Reports validated region progress and unlock state from existing saved data."
    instructions = (
        "You are the WildEx Map Agent.\n\n"
        "Your only job is to inspect or summarize region progression from already-verified data.\n"
        "You must not identify species, build cards, or generate UI markup.\n"
        "Return only structured JSON matching the map progress schema."
    )
    allowed_task_types = ("sync_progress", "inspect_region_progress", "recalculate_region_progress", "admin_request")
    output_model = MapAgentOutput

    def _run(self, task_type: str, payload: dict[str, Any], *, tool_context: dict[str, Any]) -> MapAgentOutput:
        return inspect_map_progress(payload)

    def summarize(self, task_type: str, output: MapAgentOutput, payload: dict[str, Any]) -> str:
        return output.summary
