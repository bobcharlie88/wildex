from __future__ import annotations

import json
from datetime import datetime

from app.models import SubmissionRequest


def _load_json(value, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def submission_to_dict(row: SubmissionRequest) -> dict:
    report = row.verification_report
    return {
        "id": row.id,
        "user_id": row.user_id,
        "image_url": row.image_url,
        "original_filename": row.original_filename,
        "mime_type": row.mime_type,
        "submitted_at": row.submitted_at.isoformat() if row.submitted_at else None,
        "entered_name": row.entered_name,
        "entered_species": row.entered_species,
        "location_text": row.location_text,
        "date_observed": row.date_observed,
        "notes": row.notes,
        "status": row.status,
        "verification_reason": row.verification_reason,
        "admin_notes": row.admin_notes,
        "decision_history": _load_json(row.decision_history_json, []),
        "report": {
            "authenticity_confidence": report.authenticity_confidence if report else None,
            "ai_suspicion_score": report.ai_suspicion_score if report else None,
            "metadata_present": bool(report.metadata_present) if report else None,
            "gps_present": bool(report.gps_present) if report else None,
            "capture_datetime": report.capture_datetime if report else None,
            "date_time_check_result": report.date_time_check_result if report else None,
            "device_info": report.device_info if report else None,
            "metadata_summary": _load_json(report.metadata_summary_json, {}) if report else {},
            "suspicious_findings": _load_json(report.suspicious_findings_json, []) if report else [],
            "recommendation": report.recommendation if report else None,
            "raw_report": _load_json(report.raw_report_json, {}) if report else {},
        },
    }


def append_decision_history(row: SubmissionRequest, *, action: str, actor_email: str, notes: str | None = None) -> None:
    history = _load_json(row.decision_history_json, [])
    history.append(
        {
            "action": action,
            "actor_email": actor_email,
            "notes": notes,
            "at": datetime.utcnow().isoformat(),
        }
    )
    row.decision_history_json = json.dumps(history)
