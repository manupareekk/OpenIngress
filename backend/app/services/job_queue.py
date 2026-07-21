"""Production job queue integration for audit work."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict

from ..config import Config


VALID_JOB_TYPES = {"import_snapshot", "explore", "execute", "codex_nav_audit"}


def build_job_message(
    *,
    run_id: str,
    user_id: str | None,
    job_type: str,
    phase: str | None = None,
    url: str | None = None,
    extra: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    if job_type not in VALID_JOB_TYPES:
        raise ValueError(f"Unsupported job type: {job_type}")
    phase_part = phase or "none"
    payload = {
        "message_version": 1,
        "job_id": f"{run_id}:{job_type}:{phase_part}",
        "run_id": run_id,
        "user_id": user_id,
        "job_type": job_type,
        "phase": phase,
        "url": url,
        "requested_at": datetime.utcnow().isoformat() + "Z",
    }
    if extra:
        payload.update(dict(extra))
    return payload


class AzureServiceBusJobQueue:
    def __init__(
        self,
        *,
        connection_string: str | None = None,
        queue_name: str | None = None,
    ) -> None:
        self.connection_string = connection_string or Config.AZURE_SERVICE_BUS_CONNECTION_STRING
        self.queue_name = queue_name or Config.AZURE_SERVICE_BUS_QUEUE_NAME
        if not self.connection_string:
            raise ValueError("AZURE_SERVICE_BUS_CONNECTION_STRING is required in queued mode.")
        if not self.queue_name:
            raise ValueError("AZURE_SERVICE_BUS_QUEUE_NAME is required in queued mode.")

    def send(self, payload: Dict[str, Any]) -> None:
        from azure.servicebus import ServiceBusClient, ServiceBusMessage

        body = json.dumps(payload)
        message = ServiceBusMessage(body, message_id=str(payload.get("job_id") or ""))
        with ServiceBusClient.from_connection_string(self.connection_string) as client:
            with client.get_queue_sender(queue_name=self.queue_name) as sender:
                sender.send_messages(message)


def enqueue_job(payload: Dict[str, Any]) -> None:
    AzureServiceBusJobQueue().send(payload)


def parse_job_message(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        payload = raw
    elif isinstance(raw, bytes):
        payload = json.loads(raw.decode("utf-8"))
    else:
        payload = json.loads(str(raw))

    if int(payload.get("message_version") or 0) != 1:
        raise ValueError("Unsupported job message version.")
    if payload.get("job_type") not in VALID_JOB_TYPES:
        raise ValueError("Unsupported job type.")
    if not payload.get("run_id"):
        raise ValueError("run_id is required.")
    return payload
