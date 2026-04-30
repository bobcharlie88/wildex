from __future__ import annotations

from typing import Any

from app.services.agents.base import BaseAgent
from app.services.agents.schemas import ReviewAgentOutput
from app.services.agents.tools import build_review_recommendation


class ReviewAgent(BaseAgent):
    name = "review"
    description = "Flags unusual or uncertain findings for structured manual review."
    instructions = (
        "You are the WildEx Review Agent.\n\n"
        "Your only job is to decide whether a finding should be escalated to manual review and at what priority.\n"
        "You must not identify species, generate card stats, or modify any queue directly.\n"
        "Return only structured JSON matching the review recommendation schema."
    )
    allowed_task_types = ("flag_capture_review", "flag_unusual_capture", "inspect_review_queue", "admin_request")
    output_model = ReviewAgentOutput

    def _run(self, task_type: str, payload: dict[str, Any], *, tool_context: dict[str, Any]) -> ReviewAgentOutput:
        return build_review_recommendation(payload)

    def summarize(self, task_type: str, output: ReviewAgentOutput, payload: dict[str, Any]) -> str:
        return output.reason
