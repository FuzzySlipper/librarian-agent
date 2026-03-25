"""Email via Resend API — for users to send bug reports to the developer."""

import json
import logging

import requests

from src.config import EmailConfig

log = logging.getLogger(__name__)


def send_report(
    config: EmailConfig,
    subject: str,
    body: str,
    user_name: str = "User",
) -> dict:
    """Send a bug report / diagnostic email via Resend.

    Returns {"status": "ok"} on success or {"error": "..."} on failure.
    """
    if not config.resend_api_key:
        return {"error": "Email not configured — set resend_api_key in config.yaml"}
    if not config.developer_email:
        return {"error": "No developer_email configured in config.yaml"}

    try:
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {config.resend_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "from": config.from_email,
                "to": [config.developer_email],
                "subject": f"[Narrative System] {subject}",
                "text": f"From: {user_name}\n\n{body}",
            },
            timeout=15,
        )

        if resp.ok:
            log.info("Bug report sent to %s: %s", config.developer_email, subject)
            return {"status": "ok"}
        else:
            error = resp.text[:200]
            log.error("Resend API error: %s", error)
            return {"error": f"Email failed: {error}"}

    except Exception as e:
        log.error("Email send failed: %s", e)
        return {"error": str(e)}
