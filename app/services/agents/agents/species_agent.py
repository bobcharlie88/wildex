from __future__ import annotations

from typing import Any

from app.pipeline.species_id import SpeciesResult
from app.services.agents.base import BaseAgent
from app.services.agents.schemas import AgentCandidate, AgentTaskResult, SpeciesAgentOutput


def _candidate_list(species: SpeciesResult) -> list[AgentCandidate]:
    candidates = [
        AgentCandidate(
            label=species.common_name or species.scientific_name,
            scientific_name=species.scientific_name,
            confidence=round(float(species.confidence or 0.0), 4),
            reason=species.reasoning,
        )
    ]
    if species.iconic_taxon:
        candidates.append(
            AgentCandidate(
                label=f"Iconic taxon: {species.iconic_taxon}",
                scientific_name=None,
                confidence=max(0.2, round(float(species.confidence or 0.0) - 0.18, 4)),
                reason="Higher-level taxon fallback if species certainty degrades.",
            )
        )
    return candidates


class SpeciesAgent(BaseAgent):
    name = "species"
    description = "Normalizes species evidence and confidence into a validated capture result."

    def run(self, task_type: str, payload: dict[str, Any]) -> AgentTaskResult:
        species = payload.get("species")
        if isinstance(species, SpeciesResult):
            needs_review = bool(payload.get("needs_review", species.provisional or species.confidence < 0.7))
            review_reason = payload.get("review_reason") or (
                "Confidence is below automatic-save threshold."
                if needs_review else None
            )
            output = SpeciesAgentOutput(
                common_name=species.common_name or species.scientific_name,
                scientific_name=species.scientific_name,
                confidence=round(float(species.confidence or 0.0), 4),
                needs_review=needs_review,
                review_reason=review_reason,
                evidence_summary=species.reasoning or "Species identified from submitted evidence.",
                candidate_list=_candidate_list(species),
                category=species.category,
                sub_category=species.sub_category,
                rank=species.rank,
                taxon_id=species.taxon_id,
                iconic_taxon=species.iconic_taxon,
                provisional=species.provisional,
            )
        else:
            confidence = round(float(payload.get("confidence") or 0.0), 4)
            output = SpeciesAgentOutput(
                common_name=payload.get("common_name") or payload.get("species_name") or "Unknown",
                scientific_name=payload.get("scientific_name") or "Unknown",
                confidence=confidence,
                needs_review=bool(payload.get("needs_review")),
                review_reason=payload.get("review_reason"),
                evidence_summary=payload.get("evidence_summary") or payload.get("reasoning") or "Stored species evidence inspected.",
                candidate_list=[
                    AgentCandidate(
                        label=payload.get("common_name") or payload.get("species_name") or "Unknown",
                        scientific_name=payload.get("scientific_name"),
                        confidence=confidence,
                        reason=payload.get("reasoning") or payload.get("review_reason"),
                    )
                ],
                category=payload.get("category"),
                sub_category=payload.get("sub_category"),
                rank=payload.get("rank"),
                taxon_id=payload.get("taxon_id"),
                iconic_taxon=payload.get("iconic_taxon"),
                provisional=bool(payload.get("provisional")),
            )
        return AgentTaskResult(
            agent_name="species",
            task_type=task_type,
            summary=f"{output.common_name} at {int(output.confidence * 100)}% confidence",
            payload=output.model_dump(mode="json"),
        )
