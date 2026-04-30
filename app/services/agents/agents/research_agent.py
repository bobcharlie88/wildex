from __future__ import annotations

from typing import Any

from app.services.agents.base import BaseAgent
from app.services.agents.schemas import ResearchConfirmationSchema
from app.services.agents.tools import build_research_confirmation


class ResearchAgent(BaseAgent):
    name = "research"
    description = "Confirms consensus identifications against distribution and evidence plausibility."
    instructions = (
        "You are the WildEx Research Agent.\n\n"
        "Your only job is to confirm the most plausible final species from ranked consensus candidates.\n"
        "You may search broadly across official, scientific, biodiversity, museum, university, news, and niche sites when needed.\n"
        "You must rank source reliability, prefer stronger sources, cross-check important claims, and note conflicts or uncertainty.\n"
        "You must compare repeated evidence, distribution plausibility, and alternatives.\n"
        "You must not generate UI, mutate the database, or invent unsupported certainty.\n"
        "Return only structured JSON matching the research confirmation schema."
    )
    allowed_task_types = ("confirm_consensus_identification", "inspect_candidate_plausibility", "admin_request")
    output_model = ResearchConfirmationSchema

    def _run(self, task_type: str, payload: dict[str, Any], *, tool_context: dict[str, Any]) -> ResearchConfirmationSchema:
        return build_research_confirmation(payload)

    def summarize(self, task_type: str, output: ResearchConfirmationSchema, payload: dict[str, Any]) -> str:
        return f"Confirmed {output.final_species} with {int(output.confidence * 100)}% confidence"
