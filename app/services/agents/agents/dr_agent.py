from __future__ import annotations

from typing import Any

from app.config import DR_AGENT_ENGINE
from app.services.agents.base import BaseAgent
from app.services.agents.schemas import DrAgentOutput
from app.services.agents.local_gemma import LocalGemmaUnavailable, generate_dr_response_with_gemma
from app.services.agents.tools import build_dr_response


class DrAgent(BaseAgent):
    name = "dr"
    description = "Player-facing assistant that explains completed cards and next actions."
    instructions = (
        "You are the WildEx Dr Agent.\n\n"
        "Your only job is to answer player questions using structured WildEx context.\n"
        "You may use only the provided card, biome, player region, collection summary, and hunger/feed state.\n"
        "You must stay inside one response mode at a time: card_explain, feeding_advice, biome_tip, what_next, or read_aloud.\n"
        "If required context is missing, say exactly what is missing instead of inventing facts.\n"
        "Keep the first answer short, practical, and specific. Use follow_up only for one deeper next detail.\n"
        "You must not modify database state, identify species, or generate UI markup.\n"
        "Return only structured JSON matching the Dr response schema."
    )
    allowed_task_types = ("player_help", "admin_request")
    output_model = DrAgentOutput

    def _run(self, task_type: str, payload: dict[str, Any], *, tool_context: dict[str, Any]) -> DrAgentOutput:
        if DR_AGENT_ENGINE == "gemma":
            try:
                return generate_dr_response_with_gemma(payload, self.strict_instructions(task_type))
            except LocalGemmaUnavailable:
                return build_dr_response(payload)
        return build_dr_response(payload)

    def summarize(self, task_type: str, output: DrAgentOutput, payload: dict[str, Any]) -> str:
        return f"Answered player guidance for {output.referenced_card_id or 'general context'}"
