"""Optional email notifications for completed study jobs."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Any, Iterable, List

from ..config import Config


def completion_recipients(requester_email: str = "", team_emails: Iterable[str] | None = None) -> List[str]:
    seen: set[str] = set()
    recipients: List[str] = []
    for email in [requester_email, *(team_emails if team_emails is not None else Config.JOB_NOTIFICATION_TEAM_EMAILS)]:
        normalized = str(email or "").strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        recipients.append(normalized)
    return recipients


class EmailNotifier:
    def __init__(self, smtp_factory: Any = smtplib.SMTP) -> None:
        self.smtp_factory = smtp_factory

    def _send_message(self, message: EmailMessage) -> None:
        if not (Config.SMTP_HOST and Config.SMTP_FROM and Config.SMTP_USERNAME and Config.SMTP_PASSWORD):
            raise ValueError("SMTP_HOST, SMTP_FROM, SMTP_USERNAME, and SMTP_PASSWORD are required for notifications.")
        with self.smtp_factory(Config.SMTP_HOST, Config.SMTP_PORT, timeout=20) as smtp:
            if Config.SMTP_USE_TLS:
                smtp.starttls()
            smtp.login(Config.SMTP_USERNAME, Config.SMTP_PASSWORD)
            smtp.send_message(message)

    def send_completion(self, *, state: dict[str, Any], requester_email: str = "") -> List[str]:
        if not Config.JOB_NOTIFICATION_ENABLED:
            return []
        recipients = completion_recipients(requester_email or str(state.get("requester_email") or ""))
        if not recipients:
            return []

        run_id = str(state.get("run_id") or "")
        title = str(state.get("title") or "OpenIngress audit")
        site_url = str(state.get("site_url") or "")
        report_url = f"{Config.APP_URL.rstrip('/')}/app/runs/{run_id}" if run_id else Config.APP_URL

        message = EmailMessage()
        message["Subject"] = f"OpenIngress audit complete: {title}"
        message["From"] = Config.SMTP_FROM
        message["To"] = ", ".join(recipients)
        message.set_content(
            "\n".join(
                [
                    "Your OpenIngress audit is complete.",
                    "",
                    f"Run: {title}",
                    f"Site: {site_url or 'N/A'}",
                    f"Report: {report_url}",
                    "",
                    "OpenIngress",
                ]
            )
        )

        self._send_message(message)
        return recipients

