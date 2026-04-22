from __future__ import annotations

from typing import Any

from app.services.agents.base import BaseAgent
from app.services.agents.schemas import DrAgentOutput
from app.services.agents.tools import build_dr_response


class DrAgent(BaseAgent):
    name = "dr"
    description = "Player-facing assistant that explains completed cards and next actions."
    instructions = (
        "You are the WildEx Dr Agent.\n\n"
        "Your only job is to explain card details, rarity, and next gameplay steps in a controlled assistant voice.\n"
        "You must not modify database state, identify species, or generate UI markup.\n"
        "Return only structured JSON matching the Dr response schema."
    )
    allowed_task_types = ("player_help", "admin_request")
    output_model = DrAgentOutput

    def _run(self, task_type: str, payload: dict[str, Any], *, tool_context: dict[str, Any]) -> DrAgentOutput:
        return build_dr_response(payload)

    def summarize(self, task_type: str, output: DrAgentOutput, payload: dict[str, Any]) -> str:
        return f"Answered player guidance for {output.referenced_card_id or 'general context'}"
