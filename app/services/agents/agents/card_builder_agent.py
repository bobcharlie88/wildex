from __future__ import annotations

from typing import Any

from app.pipeline.card_generator import WildCard
from app.services.agents.base import BaseAgent
from app.services.agents.schemas import AgentTaskResult, CardBuilderOutput, CardStatsPayload
from app.services.card_render import build_card_payload, build_render_card


class CardBuilderAgent(BaseAgent):
    name = "card_builder"
    description = "Builds structured card content payloads and clean renderer slot content."

    def run(self, task_type: str, payload: dict[str, Any]) -> AgentTaskResult:
        source = payload["source"]
        render_card = build_render_card(source)
        card_payload = build_card_payload(source)
        moves = render_card.get("abilities") or []
        output = CardBuilderOutput(
            card_title=card_payload["card_title"],
            scientific_name=card_payload["scientific_name"],
            rarity=card_payload["rarity"],
            stats=CardStatsPayload.model_validate(card_payload["stats"]),
            moves=moves,
            diet=card_payload["diet"],
            habitat_text=card_payload["habitat_text"],
            flavor_text=card_payload["flavor_text"],
            fact_snippets=card_payload["fact_snippets"],
            slot_content=render_card.get("slot_content") or {},
            render_hints=render_card.get("render_hints") or {},
            front_template=render_card.get("front_template") or {},
            back_template=render_card.get("back_template") or {},
        )
        return AgentTaskResult(
            agent_name="card_builder",
            task_type=task_type,
            summary=f"Built card payload for {output.card_title}",
            payload=output.model_dump(mode="json", by_alias=True),
        )
