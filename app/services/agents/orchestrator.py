from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import desc

from app.database import SessionLocal, db_available
from app.models import AgentTask, ReviewQueueItem
from app.services.agents.base import AgentExecutionError
from app.services.agents.registry import get_agent, list_agents

log = logging.getLogger("wildex.agents")
MAX_AGENT_ATTEMPTS = 2


def _sanitize_for_log(value: Any, *, depth: int = 0) -> Any:
    if depth >= 4:
        return "<max-depth>"
    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"
    if isinstance(value, dict):
        return {str(key): _sanitize_for_log(val, depth=depth + 1) for key, val in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_for_log(item, depth=depth + 1) for item in list(value)[:25]]
    if isinstance(value, str):
        return value if len(value) <= 1000 else f"{value[:1000]}...(truncated)"
    if hasattr(value, "model_dump"):
        return _sanitize_for_log(value.model_dump(mode="json"), depth=depth + 1)
    return value


def _json(value: Any) -> str:
    return json.dumps(_sanitize_for_log(value), ensure_ascii=True, default=str)


def run_agent_task(
    *,
    agent_name: str,
    task_type: str,
    payload: dict[str, Any],
    actor_user_id: int | None = None,
    card_id: int | None = None,
    capture_job_id: int | None = None,
    tool_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    agent = get_agent(agent_name)
    db = SessionLocal() if db_available() and SessionLocal is not None else None
    task_row = None
    sanitized_input = {
        "task_type": task_type,
        "payload": payload,
        "tool_context": tool_context or {},
    }
    try:
        if db is not None:
            try:
                task_row = AgentTask(
                    agent_name=agent_name,
                    task_type=task_type,
                    status="running",
                    actor_user_id=actor_user_id,
                    card_id=card_id,
                    capture_job_id=capture_job_id,
                    input_payload=_json(sanitized_input),
                )
                db.add(task_row)
                db.commit()
                db.refresh(task_row)
            except Exception:
                log.warning("Agent task logging unavailable; continuing without DB task row", exc_info=True)
                db.rollback()
                task_row = None

        last_error: Exception | None = None
        for attempt in range(1, MAX_AGENT_ATTEMPTS + 1):
            strict_payload = dict(payload)
            strict_payload["_agent_meta"] = {
                "attempt": attempt,
                "max_attempts": MAX_AGENT_ATTEMPTS,
                "strict_mode": attempt > 1,
                "instructions": agent.strict_instructions(task_type),
            }
            try:
                log.info(
                    "Running agent task agent=%s task=%s attempt=%s payload=%s",
                    agent_name,
                    task_type,
                    attempt,
                    _json(strict_payload),
                )
                result = agent.run(task_type, strict_payload, tool_context=tool_context)
                output = result.model_dump(mode="json")
                log.info(
                    "Agent task complete agent=%s task=%s attempt=%s output=%s",
                    agent_name,
                    task_type,
                    attempt,
                    _json(output),
                )
                if db is not None and task_row is not None:
                    task_row.status = "complete"
                    task_row.summary = result.summary
                    task_row.output_payload = _json(output)
                    task_row.completed_at = datetime.utcnow()
                    db.commit()
                return {
                    "task_id": task_row.id if task_row is not None else None,
                    "agent_name": result.agent_name,
                    "task_type": result.task_type,
                    "summary": result.summary,
                    "payload": result.payload,
                }
            except Exception as exc:
                last_error = exc
                log.warning(
                    "Agent task attempt failed agent=%s task=%s attempt=%s error=%s",
                    agent_name,
                    task_type,
                    attempt,
                    exc,
                    exc_info=True,
                )
                if attempt >= MAX_AGENT_ATTEMPTS:
                    break

        assert last_error is not None
        raise last_error
    except Exception as exc:
        error = exc if isinstance(exc, AgentExecutionError) else AgentExecutionError(str(exc))
        log.exception("Agent task failed agent=%s task=%s", agent_name, task_type)
        if db is not None and task_row is not None:
            db.rollback()
            task_row.status = "failed"
            task_row.error = str(error)
            task_row.completed_at = datetime.utcnow()
            db.commit()
        raise error
    finally:
        if db is not None:
            db.close()


def get_agent_dashboard(*, limit: int = 12) -> dict[str, Any]:
    base_agents = [
        {
            "name": agent.name,
            "description": agent.description,
            "instructions": agent.instructions,
            "task_types": list(agent.allowed_task_types),
            "status": "ready",
            "last_task": None,
            "recent_errors": [],
        }
        for agent in list_agents()
    ]
    if not db_available() or SessionLocal is None:
        return {"agents": base_agents, "recent_tasks": [], "review_queue": []}

    db = SessionLocal()
    try:
        try:
            recent_tasks = (
                db.query(AgentTask)
                .order_by(desc(AgentTask.created_at), desc(AgentTask.id))
                .limit(max(10, limit))
                .all()
            )
            review_rows = (
                db.query(ReviewQueueItem)
                .order_by(desc(ReviewQueueItem.created_at), desc(ReviewQueueItem.id))
                .limit(limit)
                .all()
            )
        except Exception:
            log.warning("Agent dashboard DB reads unavailable; returning empty dashboard state", exc_info=True)
            return {"agents": base_agents, "recent_tasks": [], "review_queue": []}
        by_name = {item["name"]: item for item in base_agents}
        for row in recent_tasks:
            agent = by_name.get(row.agent_name)
            if not agent:
                continue
            if agent["last_task"] is None:
                agent["last_task"] = {
                    "id": row.id,
                    "task_type": row.task_type,
                    "status": row.status,
                    "summary": row.summary,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
            if row.status == "failed" and row.error and len(agent["recent_errors"]) < 3:
                agent["recent_errors"].append({
                    "id": row.id,
                    "task_type": row.task_type,
                    "error": row.error,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                })
        return {
            "agents": base_agents,
            "recent_tasks": [
                {
                    "id": row.id,
                    "agent_name": row.agent_name,
                    "task_type": row.task_type,
                    "status": row.status,
                    "summary": row.summary,
                    "error": row.error,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "completed_at": row.completed_at.isoformat() if row.completed_at else None,
                    "card_id": row.card_id,
                    "capture_job_id": row.capture_job_id,
                    "input_payload": json.loads(row.input_payload) if row.input_payload else {},
                    "output_payload": json.loads(row.output_payload) if row.output_payload else {},
                }
                for row in recent_tasks
            ],
            "review_queue": [
                {
                    "id": row.id,
                    "capture_job_id": row.capture_job_id,
                    "card_id": row.card_id,
                    "species_result_id": row.species_result_id,
                    "reason": row.reason,
                    "priority": row.priority,
                    "status": row.status,
                    "evidence_summary": row.evidence_summary,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
                for row in review_rows
            ],
        }
    finally:
        db.close()
