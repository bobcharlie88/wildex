from __future__ import annotations

from typing import Any

from app.services.agents.base import BaseAgent
from app.services.agents.schemas import VerificationReportSchema
from app.services.agents.tools import build_verification_report


class VerificationAgent(BaseAgent):
    name = "verification"
    description = "Scores submission authenticity and returns a structured verification report."
    instructions = (
        "You are the WildEx Verification Agent.\n\n"
        "Your only job is to assess whether an uploaded image is likely a real photograph.\n"
        "You must analyze metadata summary, image characteristics, suspicious indicators, and return an authenticity report.\n"
        "You must not claim absolute certainty or directly mutate queue/database state.\n"
        "Return only structured JSON matching the verification report schema."
    )
    allowed_task_types = ("score_submission_authenticity", "inspect_submission_verification", "admin_request")
    output_model = VerificationReportSchema

    def _run(self, task_type: str, payload: dict[str, Any], *, tool_context: dict[str, Any]) -> VerificationReportSchema:
        return build_verification_report(payload, tool_context=tool_context)

    def summarize(self, task_type: str, output: VerificationReportSchema, payload: dict[str, Any]) -> str:
        return (
            f"Verification scored {int(output.authenticity_confidence * 100)}% authentic "
            f"with recommendation {output.recommendation}"
        )
