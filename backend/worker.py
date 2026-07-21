"""Azure Container Apps worker for queued OpenIngress jobs."""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from typing import Any

from azure.servicebus import AutoLockRenewer, ServiceBusClient

from app.config import Config
from app.services.codex_nav_audit import CodexNavigabilityAuditManager, ensure_codex_config
from app.services.job_queue import parse_job_message
from app.services.readiness_manager import ReadinessManager


_STOP = False


def _handle_stop(signum: int, frame: Any) -> None:
    global _STOP
    _STOP = True


def _message_body(message: Any) -> str:
    chunks = []
    for chunk in message.body:
        chunks.append(chunk if isinstance(chunk, bytes) else str(chunk).encode("utf-8"))
    return b"".join(chunks).decode("utf-8")


def process_worker_payload(payload: dict[str, Any]) -> dict[str, Any]:
    parsed = parse_job_message(payload)
    if parsed.get("job_type") == "codex_nav_audit":
        return CodexNavigabilityAuditManager().process_queued_job(parsed)
    return ReadinessManager().process_queued_job(parsed)


def run_worker() -> None:
    if not Config.AZURE_SERVICE_BUS_CONNECTION_STRING:
        raise ValueError("AZURE_SERVICE_BUS_CONNECTION_STRING is required.")
    if not Config.AZURE_SERVICE_BUS_QUEUE_NAME:
        raise ValueError("AZURE_SERVICE_BUS_QUEUE_NAME is required.")

    ensure_codex_config()
    with ServiceBusClient.from_connection_string(Config.AZURE_SERVICE_BUS_CONNECTION_STRING) as client:
        with client.get_queue_receiver(queue_name=Config.AZURE_SERVICE_BUS_QUEUE_NAME, max_wait_time=10) as receiver:
            while not _STOP:
                messages = receiver.receive_messages(max_message_count=1, max_wait_time=10)
                if not messages:
                    continue
                for message in messages:
                    if _STOP:
                        receiver.abandon_message(message)
                        break
                    renewer = AutoLockRenewer(max_lock_renewal_duration=60 * 60)
                    try:
                        renewer.register(receiver, message, max_lock_renewal_duration=60 * 60)
                        process_worker_payload(json.loads(_message_body(message)))
                        receiver.complete_message(message)
                    except Exception as exc:
                        print(f"Queued job failed: {exc}", file=sys.stderr, flush=True)
                        receiver.abandon_message(message)
                    finally:
                        renewer.close()


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)
    while not _STOP:
        try:
            run_worker()
        except Exception as exc:
            print(f"Worker loop error: {exc}", file=sys.stderr, flush=True)
            time.sleep(int(os.environ.get("WORKER_RESTART_DELAY_SECONDS", "5")))
