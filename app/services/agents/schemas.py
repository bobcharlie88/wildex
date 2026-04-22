from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


AgentName = Literal["dr", "species", "card_builder", "verification", "map", "review", "research"]


class AgentCandidate(BaseModel):
    label: str
    scientific_name: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str | None = None


class SpeciesResultSchema(BaseModel):
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
    consensus_score: float | None = Field(default=None, ge=0.0, le=1.0)
    location_validated: bool | None = None
    alternatives: list[AgentCandidate] = Field(default_factory=list)


class CardStatsPayload(BaseModel):
    hp: int = Field(ge=0, le=999)
    atk: int = Field(ge=0, le=999)
    defn: int = Field(alias="def", ge=0, le=999)
    spd: int = Field(ge=0, le=999)
    stamina_regen: int | None = Field(default=None, ge=0, le=999)

    model_config = {"populate_by_name": True}


class CardBuilderOutput(BaseModel):
    card_title: str
    scientific_name: str
    rarity: str
    stats: CardStatsPayload
    moves: list[str] = Field(default_factory=list, min_length=0, max_length=4)
    diet: str = ""
    habitat_text: str = ""
    flavor_text: str = ""
    fact_snippets: list[str] = Field(default_factory=list)
    slot_content: dict[str, dict[str, Any]] = Field(default_factory=dict)
    render_hints: dict[str, Any] = Field(default_factory=dict)
    front_template: dict[str, Any] = Field(default_factory=dict)
    back_template: dict[str, Any] = Field(default_factory=dict)


class VerificationReportSchema(BaseModel):
    authenticity_confidence: float = Field(ge=0.0, le=1.0)
    ai_suspicion_score: float = Field(ge=0.0, le=1.0)
    metadata_present: bool = False
    metadata_summary: dict[str, Any] = Field(default_factory=dict)
    metadata_summary_text: str = ""
    gps_present: bool = False
    capture_datetime: str | None = None
    date_time_check_result: str | None = None
    device_info: str | None = None
    suspicious_findings: list[str] = Field(default_factory=list)
    recommendation: Literal["cleared", "manual_review", "rejected_or_hold"]
    status: Literal["cleared", "manual_review"]
    verification_reason: str
    raw_report: dict[str, Any] = Field(default_factory=dict)


class MapAgentOutput(BaseModel):
    region: str | None = None
    unlocked: bool = False
    repeat_state: str | None = None
    counts: dict[str, int] = Field(default_factory=dict)
    summary: str


class ReviewAgentOutput(BaseModel):
    needs_review: bool
    priority: Literal["low", "medium", "high"] = "medium"
    reason: str
    evidence_summary: str = ""
    queue_status: Literal["recommended", "not_required", "not_created"] = "not_created"


class DrAgentOutput(BaseModel):
    reply: str
    suggested_actions: list[str] = Field(default_factory=list)
    referenced_card_id: int | None = None
    referenced_capture_job_id: int | None = None


class ResearchConfirmationSchema(BaseModel):
    final_species: str
    scientific_name: str
    confidence: float = Field(ge=0.0, le=1.0)
    consensus_score: float = Field(ge=0.0, le=1.0)
    location_validated: bool = False
    alternatives: list[AgentCandidate] = Field(default_factory=list)
    reasoning: str
    category: str | None = None
    sub_category: str | None = None
    rank: str | None = None
    taxon_id: int | None = None
    iconic_taxon: str | None = None
    provisional: bool = False


class AgentTaskResult(BaseModel):
    agent_name: AgentName
    task_type: str
    summary: str
    payload: dict[str, Any]
