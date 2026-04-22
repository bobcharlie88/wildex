from __future__ import annotations

from app.services.agents.agents.card_builder_agent import CardBuilderAgent
from app.services.agents.agents.dr_agent import DrAgent
from app.services.agents.agents.map_agent import MapAgent
from app.services.agents.agents.review_agent import ReviewAgent
from app.services.agents.agents.species_agent import SpeciesAgent
from app.services.agents.agents.verification_agent import VerificationAgent


_AGENTS = {
    "dr": DrAgent(),
    "species": SpeciesAgent(),
    "card_builder": CardBuilderAgent(),
    "verification": VerificationAgent(),
    "map": MapAgent(),
    "review": ReviewAgent(),
}


def get_agent(name: str):
    key = (name or "").strip().lower()
    if key not in _AGENTS:
        raise KeyError(f"Unknown agent: {name}")
    return _AGENTS[key]


def list_agents():
    return list(_AGENTS.values())
