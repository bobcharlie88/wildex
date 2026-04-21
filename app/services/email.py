from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from app.config import EMAIL_FROM, SMTP_HOST, SMTP_PASSWORD, SMTP_PORT, SMTP_USERNAME, SMTP_USE_TLS

log = logging.getLogger("wildex.email")


def email_configured() -> bool:
    return bool(SMTP_HOST and SMTP_USERNAME and SMTP_PASSWORD)


def send_email(*, to_email: str, subject: str, text_body: str) -> bool:
    if not email_configured():
        log.warning("SMTP not configured; email not sent to %s", to_email)
        return False

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = EMAIL_FROM
    message["To"] = to_email
    message.set_content(text_body)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as client:
        if SMTP_USE_TLS:
            client.starttls()
        client.login(SMTP_USERNAME, SMTP_PASSWORD)
        client.send_message(message)
    log.info("Sent email to %s", to_email)
    return True
