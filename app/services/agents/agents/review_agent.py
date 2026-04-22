from __future__ import annotations

from typing import Any

from app.services.agents.base import BaseAgent
from app.services.agents.schemas import AgentTaskResult, ReviewAgentOutput


class ReviewAgent(BaseAgent):
    name = "review"
    description = "Flags unusual or uncertain sightings into a structured review queue."

    def run(self, task_type: str, payload: dict[str, Any]) -> AgentTaskResult:
        confidence = float(payload.get("confidence") or 0.0)
        reason = payload.get("reason") or ""
        rarity = str(payload.get("rarity") or "").lower()
        needs_review = bool(payload.get("needs_review"))
        priority = "medium"
        if rarity in {"legendary", "mythic", "cryptic", "extinct"} or confidence < 0.45:
            priority = "high"
        elif confidence < 0.7:
            priority = "medium"
        else:
            priority = "low"
        output = ReviewAgentOutput(
            needs_review=needs_review,
            priority=priority,
            reason=reason or ("Capture requires manual review." if needs_review else "No review action required."),
            evidence_summary=payload.get("evidence_summary") or "",
            queue_status="recommended" if needs_review else "not_required",
        )
        return AgentTaskResult(
            agent_name="review",
            task_type=task_type,
            summary=output.reason,
            payload=output.model_dump(mode="json"),
        )
