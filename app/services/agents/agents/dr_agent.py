from __future__ import annotations

from typing import Any

from app.services.agents.base import BaseAgent
from app.services.agents.schemas import AgentTaskResult, DrAgentOutput


class DrAgent(BaseAgent):
    name = "dr"
    description = "Player-facing field guide that explains completed cards and next steps."

    def run(self, task_type: str, payload: dict[str, Any]) -> AgentTaskResult:
        card = payload.get("card") or {}
        question = str(payload.get("question") or "").strip().lower()
        species_name = card.get("species_name") or card.get("card_title") or "this find"
        rarity = card.get("rarity_display") or card.get("rarity") or "Unknown"
        habitat = card.get("habitat_text") or card.get("biome") or "its native habitat"
        fact = card.get("fact_text") or (card.get("fact_snippets") or [""])[0]
        if "rare" in question:
            reply = f"{species_name} rates as {rarity} because WildEx weighs observation scarcity, conservation signals, and how unusual the encounter is for the region."
        elif "next" in question or "what should i do" in question:
            reply = f"Keep capturing around {habitat}. Repeats still strengthen your log, but a new branch in the current region will move your Dex faster."
        elif "what is this" in question or "why" in question:
            reply = f"{species_name} is logged as a verified field encounter. The strongest clue was the species evidence already attached to this card."
        else:
            reply = f"{species_name} is one of your WildEx field records. It is tuned around {habitat}, and one standout note is: {fact or 'its card data is ready for review.'}"
        output = DrAgentOutput(
            reply=reply,
            suggested_actions=[
                "Open the card back to inspect map and biome details",
                "Capture another species in the same unlocked region",
            ],
            referenced_card_id=payload.get("card_id"),
            referenced_capture_job_id=payload.get("capture_job_id"),
        )
        return AgentTaskResult(
            agent_name="dr",
            task_type=task_type,
            summary=f"Answered player guidance for {species_name}",
            payload=output.model_dump(mode="json"),
        )
