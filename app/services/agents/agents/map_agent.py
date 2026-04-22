from __future__ import annotations

from typing import Any

from app.database import SessionLocal, db_available
from app.models import DexEntry, UserDexDiscovery
from app.services.agents.base import BaseAgent
from app.services.agents.schemas import AgentTaskResult, MapAgentOutput
from app.services.dex import DISCOVERY_CAPTURED, DISCOVERY_SEEN


class MapAgent(BaseAgent):
    name = "map"
    description = "Handles progression summaries and validated map/unlock writes."

    def run(self, task_type: str, payload: dict[str, Any]) -> AgentTaskResult:
        user_id = payload.get("user_id")
        region = payload.get("region")
        counts = {"captured": 0, "seen": 0}
        if user_id and db_available() and SessionLocal is not None:
            db = SessionLocal()
            try:
                query = (
                    db.query(UserDexDiscovery.discovery_state)
                    .join(DexEntry, DexEntry.id == UserDexDiscovery.dex_entry_id)
                    .filter(UserDexDiscovery.user_id == user_id)
                )
                if region:
                    query = query.filter(DexEntry.region == region)
                for (state,) in query.all():
                    if state == DISCOVERY_CAPTURED:
                        counts["captured"] += 1
                    elif state == DISCOVERY_SEEN:
                        counts["seen"] += 1
            finally:
                db.close()
        output = MapAgentOutput(
            region=region,
            unlocked=bool(payload.get("region_unlocked")),
            repeat_state=payload.get("repeat_state"),
            counts=counts,
            summary=payload.get("summary")
            or (
                f"Region {region or 'unknown'} now has {counts['captured']} captured and {counts['seen']} seen entries."
                if counts["captured"] or counts["seen"]
                else "Map state inspected."
            ),
        )
        return AgentTaskResult(
            agent_name="map",
            task_type=task_type,
            summary=output.summary,
            payload=output.model_dump(mode="json"),
        )
