from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse

from app.auth import get_current_user, require_user
from app.database import SessionLocal, db_available
from app.models import SubmissionRequest, SubmissionVerificationReport, User
from app.services.agents.orchestrator import run_agent_task
from app.services.submission_verification import serialize_report_fields
from app.services.submissions import submission_to_dict
from app.utils.storage import upload_named_bytes

router = APIRouter(prefix="/submissions", tags=["submissions"])
log = logging.getLogger("wildex.submissions")


@router.get("")
def submission_page(request: Request):
    if get_current_user(request) is None:
        return RedirectResponse("/login", status_code=303)
    return FileResponse("app/static/submissions.html")


@router.get("/mine")
def my_submissions(current_user: User = Depends(require_user)):
    if not db_available():
        raise HTTPException(503, "Database unavailable")
    db = SessionLocal()
    try:
        rows = (
            db.query(SubmissionRequest)
            .filter(SubmissionRequest.user_id == current_user.id)
            .order_by(SubmissionRequest.submitted_at.desc(), SubmissionRequest.id.desc())
            .all()
        )
        return {"items": [submission_to_dict(row) for row in rows]}
    finally:
        db.close()


@router.post("")
async def create_submission(
    request: Request,
    image: UploadFile = File(...),
    entered_name: str = Form(""),
    entered_species: str = Form(""),
    location_text: str = Form(""),
    date_observed: str = Form(""),
    notes: str = Form(""),
    current_user: User = Depends(require_user),
):
    if not db_available():
        raise HTTPException(503, "Database unavailable")
    content = await image.read()
    if not content:
        raise HTTPException(400, "Uploaded file was empty")
    content_type = image.content_type or "application/octet-stream"
    if not content_type.startswith("image/"):
        raise HTTPException(400, "Only image uploads are supported for submission verification")

    original_filename = image.filename or "submission-image"
    image_url = upload_named_bytes(
        data=content,
        content_type=content_type,
        directory="submissions/raw",
        filename=original_filename,
    )
    log.info("Stored submission image user=%s image=%s", current_user.email, image_url)

    verification_result = run_agent_task(
        agent_name="verification",
        task_type="score_submission_authenticity",
        payload={
            "filename": original_filename,
            "content_type": content_type,
            "observed_date": (date_observed or "").strip() or None,
            "file_size": len(content),
        },
        actor_user_id=current_user.id,
        tool_context={"data": content},
    )
    report = verification_result["payload"]

    db = SessionLocal()
    try:
        submission = SubmissionRequest(
            user_id=current_user.id,
            image_url=image_url,
            original_filename=original_filename,
            mime_type=content_type,
            entered_name=(entered_name or "").strip() or None,
            entered_species=(entered_species or "").strip() or None,
            location_text=(location_text or "").strip() or None,
            date_observed=(date_observed or "").strip() or None,
            notes=(notes or "").strip() or None,
            status=report["status"],
            verification_reason=report["verification_reason"],
        )
        db.add(submission)
        db.flush()
        verification = SubmissionVerificationReport(
            request_id=submission.id,
            **serialize_report_fields(report),
        )
        db.add(verification)
        db.commit()
        db.refresh(submission)
        db.refresh(verification)
        return {"ok": True, "request": submission_to_dict(submission)}
    finally:
        db.close()
