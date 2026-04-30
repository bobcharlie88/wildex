from __future__ import annotations

from typing import Any

from app.services.agents.base import AgentExecutionError, BaseAgent
from app.services.agents.schemas import CardBuilderOutput
from app.services.agents.tools import build_card_payload_tool


class CardBuilderAgent(BaseAgent):
    name = "card_builder"
    description = "Builds structured card payloads from verified species data and source context."
    instructions = (
        "You are the WildEx Card Builder Agent.\n\n"
        "Your only job is to convert verified species data into a structured card payload.\n"
        "You must generate balanced stats, 3-4 moves, concise flavor text, and slot content.\n"
        "You must not generate HTML, duplicate content blocks, or modify database state.\n"
        "Return only structured JSON matching the card payload schema."
    )
    allowed_task_types = ("build_card_payload", "rebuild_card_payload", "inspect_card_payload", "admin_request")
    output_model = CardBuilderOutput

    def _run(self, task_type: str, payload: dict[str, Any], *, tool_context: dict[str, Any]) -> CardBuilderOutput:
        source = payload.get("source")
        if not source:
            raise AgentExecutionError("card_builder requires source data")
        return build_card_payload_tool(source)

    def summarize(self, task_type: str, output: CardBuilderOutput, payload: dict[str, Any]) -> str:
        return f"Built card payload for {output.card_title}"
