from __future__ import annotations

from typing import Any

from app.services.agents.base import BaseAgent
from app.services.agents.schemas import SpeciesResultSchema
from app.services.agents.tools import normalize_species_result


class SpeciesAgent(BaseAgent):
    name = "species"
    description = "Identifies and normalizes likely species evidence into a validated species result."
    instructions = (
        "You are the WildEx Species Agent.\n\n"
        "Your only job is to identify or normalize the most likely species from provided evidence.\n"
        "You may estimate confidence and request review when uncertain.\n"
        "You must not generate game stats, card layout, map changes, or UI markup.\n"
        "Return only structured JSON matching the species result schema."
    )
    allowed_task_types = ("normalize_capture_species", "inspect_species_result", "admin_request")
    output_model = SpeciesResultSchema

    def _run(self, task_type: str, payload: dict[str, Any], *, tool_context: dict[str, Any]) -> SpeciesResultSchema:
        return normalize_species_result(payload)

    def summarize(self, task_type: str, output: SpeciesResultSchema, payload: dict[str, Any]) -> str:
        return f"{output.common_name} at {int(output.confidence * 100)}% confidence"
