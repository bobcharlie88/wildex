from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


AgentName = Literal["dr", "species", "card_builder", "map", "review"]


class AgentCandidate(BaseModel):
    label: str
    scientific_name: str | None = None
    confidence: float = 0.0
    reason: str | None = None


class SpeciesAgentOutput(BaseModel):
    common_name: str
    scientific_name: str
    confidence: float = Field(ge=0.0, le=1.0)
    needs_review: bool = False
    review_reason: str | None = None
    evidence_summary: str
    candidate_list: list[AgentCandidate] = Field(default_factory=list)
    category: str | None = None
    sub_category: str | None = None
    rank: str | None = None
    taxon_id: int | None = None
    iconic_taxon: str | None = None
    provisional: bool = False


class CardStatsPayload(BaseModel):
    hp: int
    atk: int
    defn: int = Field(alias="def")
    spd: int
    stamina_regen: int | None = None

    model_config = {"populate_by_name": True}


class CardBuilderOutput(BaseModel):
    card_title: str
    scientific_name: str
    rarity: str
    stats: CardStatsPayload
    moves: list[str] = Field(default_factory=list)
    diet: str = ""
    habitat_text: str = ""
    flavor_text: str = ""
    fact_snippets: list[str] = Field(default_factory=list)
    slot_content: dict[str, dict[str, Any]] = Field(default_factory=dict)
    render_hints: dict[str, Any] = Field(default_factory=dict)
    front_template: dict[str, Any] = Field(default_factory=dict)
    back_template: dict[str, Any] = Field(default_factory=dict)


class MapAgentOutput(BaseModel):
    region: str | None = None
    unlocked: bool = False
    repeat_state: str | None = None
    counts: dict[str, int] = Field(default_factory=dict)
    summary: str


class ReviewAgentOutput(BaseModel):
    needs_review: bool
    priority: str = "medium"
    reason: str
    evidence_summary: str = ""
    queue_status: str = "not_created"


class DrAgentOutput(BaseModel):
    reply: str
    suggested_actions: list[str] = Field(default_factory=list)
    referenced_card_id: int | None = None
    referenced_capture_job_id: int | None = None


class AgentTaskResult(BaseModel):
    agent_name: AgentName
    task_type: str
    summary: str
    payload: dict[str, Any]
