import json
import os

import pytest

from app.config import Config
from app.models import RunStatus
from app.services import readiness_manager as readiness_module
from app.services.notifications import EmailNotifier, completion_recipients
from app.services.readiness_manager import ReadinessManager


def _read_state(base_dir, run_id):
    with open(os.path.join(base_dir, run_id, "state.json"), encoding="utf-8") as handle:
        return json.load(handle)


def test_queued_import_enqueues_exact_message(monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr(Config, "JOB_EXECUTION_MODE", "queued")
    monkeypatch.setattr(readiness_module, "enqueue_job", lambda payload: sent.append(payload))

    manager = ReadinessManager(base_dir=str(tmp_path))
    state = manager.create_run({"title": "queued"}, user_id="dev", user_email="dev@example.com")
    result = manager.import_snapshot(state["run_id"], "before", "https://example.com", user_id="dev")

    assert result["started"] is True
    assert result["queued"] is True
    assert len(sent) == 1
    payload = sent[0]
    assert payload["message_version"] == 1
    assert payload["job_id"] == f"{state['run_id']}:import_snapshot:before"
    assert payload["run_id"] == state["run_id"]
    assert payload["user_id"] == "dev"
    assert payload["job_type"] == "import_snapshot"
    assert payload["phase"] == "before"
    assert payload["url"] == "https://example.com"
    assert payload["requested_at"].endswith("Z")

    queued_state = _read_state(str(tmp_path), state["run_id"])
    assert queued_state["status"] == RunStatus.QUEUED.value
    assert queued_state["job_phase"] == "crawl"
    assert queued_state["requester_email"] == "dev@example.com"


def test_process_queued_execute_job_completes_with_fake_worker(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "JOB_NOTIFICATION_ENABLED", False)
    manager = ReadinessManager(base_dir=str(tmp_path))
    state = manager.create_run({"title": "execute"}, user_id="dev")
    run_id = state["run_id"]

    def fake_execute(self, queued_run_id):
        run_dir = self._run_dir(queued_run_id)
        final_state = self._read_json(os.path.join(run_dir, "state.json"))
        final_state["status"] = RunStatus.COMPLETED.value
        final_state["job_phase"] = None
        final_state["progress"] = "Complete"
        self._write_json(run_dir, "state.json", final_state)

    monkeypatch.setattr(ReadinessManager, "_execute_run_worker", fake_execute)

    result = manager.process_queued_job(
        {
            "message_version": 1,
            "job_id": f"{run_id}:execute:none",
            "run_id": run_id,
            "user_id": "dev",
            "job_type": "execute",
            "phase": None,
            "url": None,
            "requested_at": "2026-06-01T00:00:00Z",
        }
    )

    assert result["status"] == RunStatus.COMPLETED.value
    final_state = _read_state(str(tmp_path), run_id)
    assert final_state["status"] == RunStatus.COMPLETED.value
    assert final_state["job_phase"] is None


def test_linked_codex_run_email_waits_for_combined_completion(monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr(Config, "JOB_NOTIFICATION_ENABLED", True)
    monkeypatch.setattr(
        readiness_module.EmailNotifier,
        "send_completion",
        lambda self, *, state, requester_email="": sent.append((state["run_id"], requester_email)) or [requester_email],
    )
    manager = ReadinessManager(base_dir=str(tmp_path))
    state = manager.create_run(
        {"title": "paired", "linked_codex_run_id": "codex_run_123"},
        user_id="dev",
        user_email="owner@example.com",
    )
    run_id = state["run_id"]

    def fake_execute(self, queued_run_id):
        run_dir = self._run_dir(queued_run_id)
        final_state = self._read_json(os.path.join(run_dir, "state.json"))
        final_state["status"] = RunStatus.COMPLETED.value
        final_state["job_phase"] = None
        final_state["progress"] = "Complete"
        self._write_json(run_dir, "state.json", final_state)

    monkeypatch.setattr(ReadinessManager, "_execute_run_worker", fake_execute)

    manager.process_queued_job(
        {
            "message_version": 1,
            "job_id": f"{run_id}:execute:none",
            "run_id": run_id,
            "user_id": "dev",
            "job_type": "execute",
            "phase": None,
            "url": None,
            "requested_at": "2026-06-01T00:00:00Z",
        }
    )

    assert sent == []

    codex_dir = tmp_path / "codex_run_123"
    codex_dir.mkdir()
    manager._write_json(
        str(codex_dir),
        "codex_state.json",
        {"run_id": "codex_run_123", "status": RunStatus.COMPLETED.value},
    )
    manager._send_completion_notification_when_ready(os.path.join(tmp_path, run_id))

    assert sent == [(run_id, "owner@example.com")]
    final_state = _read_state(str(tmp_path), run_id)
    assert final_state["completion_email_sent"] is True


def test_process_queued_explore_job_fails_if_worker_returns_non_terminal(monkeypatch, tmp_path):
    manager = ReadinessManager(base_dir=str(tmp_path))
    state = manager.create_run({"title": "stuck explore"}, user_id="dev")
    run_id = state["run_id"]

    def fake_explore(self, queued_run_id):
        return None

    monkeypatch.setattr(ReadinessManager, "_explore_run_worker", fake_explore)

    with pytest.raises(RuntimeError, match="Worker exited before finalizing run state"):
        manager.process_queued_job(
            {
                "message_version": 1,
                "job_id": f"{run_id}:explore:none",
                "run_id": run_id,
                "user_id": "dev",
                "job_type": "explore",
                "phase": None,
                "url": None,
                "requested_at": "2026-06-01T00:00:00Z",
            }
        )

    final_state = _read_state(str(tmp_path), run_id)
    assert final_state["status"] == RunStatus.FAILED.value
    assert final_state["job_phase"] is None
    assert final_state["error"] == "Worker exited before finalizing run state"


def test_process_queued_job_skips_completed_and_cancelled(tmp_path):
    manager = ReadinessManager(base_dir=str(tmp_path))
    completed = manager.create_run({"title": "done"}, user_id="dev")
    completed_dir = os.path.join(tmp_path, completed["run_id"])
    completed_state = _read_state(str(tmp_path), completed["run_id"])
    completed_state["status"] = RunStatus.COMPLETED.value
    manager._write_json(str(completed_dir), "state.json", completed_state)

    assert manager.process_queued_job(
        {
            "message_version": 1,
            "job_id": f"{completed['run_id']}:execute:none",
            "run_id": completed["run_id"],
            "user_id": "dev",
            "job_type": "execute",
            "phase": None,
            "url": None,
            "requested_at": "2026-06-01T00:00:00Z",
        }
    )["reason"] == "already_completed"

    cancelled = manager.create_run({"title": "cancelled"}, user_id="dev")
    cancelled_state = manager.cancel_run(cancelled["run_id"], user_id="dev")
    assert cancelled_state["error"] == "Cancelled by user"
    assert manager.process_queued_job(
        {
            "message_version": 1,
            "job_id": f"{cancelled['run_id']}:execute:none",
            "run_id": cancelled["run_id"],
            "user_id": "dev",
            "job_type": "execute",
            "phase": None,
            "url": None,
            "requested_at": "2026-06-01T00:00:00Z",
        }
    )["reason"] == "cancelled"


def test_completion_recipients_dedupes_requester_and_team():
    recipients = completion_recipients(
        "Owner@Example.com",
        ["team@example.com", "owner@example.com", "", "TEAM@example.com"],
    )

    assert recipients == ["owner@example.com", "team@example.com"]


def test_email_notifier_uses_fake_smtp(monkeypatch):
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            sent["host"] = host
            sent["port"] = port
            sent["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def starttls(self):
            sent["tls"] = True

        def login(self, username, password):
            sent["login"] = (username, password)

        def send_message(self, message):
            sent["message"] = message

    monkeypatch.setattr(Config, "JOB_NOTIFICATION_ENABLED", True)
    monkeypatch.setattr(Config, "JOB_NOTIFICATION_TEAM_EMAILS", ["team@example.com"])
    monkeypatch.setattr(Config, "SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setattr(Config, "SMTP_PORT", 587)
    monkeypatch.setattr(Config, "SMTP_USERNAME", "sender@gmail.com")
    monkeypatch.setattr(Config, "SMTP_PASSWORD", "app-password")
    monkeypatch.setattr(Config, "SMTP_FROM", "sender@gmail.com")
    monkeypatch.setattr(Config, "SMTP_USE_TLS", True)
    monkeypatch.setattr(Config, "APP_URL", "https://www.openingress.dev")

    recipients = EmailNotifier(smtp_factory=FakeSMTP).send_completion(
        state={
            "run_id": "run_123",
            "title": "Audit",
            "site_url": "https://example.com",
        },
        requester_email="owner@example.com",
    )

    assert recipients == ["owner@example.com", "team@example.com"]
    assert sent["host"] == "smtp.gmail.com"
    assert sent["tls"] is True
    assert sent["login"] == ("sender@gmail.com", "app-password")
    assert sent["message"]["To"] == "owner@example.com, team@example.com"
    assert "https://www.openingress.dev/app/runs/run_123" in sent["message"].get_content()


def test_email_notifier_sends_enterprise_contact_to_team_only(monkeypatch):
    messages = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            self.host = host

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def starttls(self):
            return None

        def login(self, username, password):
            return None

        def send_message(self, message):
            messages.append(message)

    monkeypatch.setattr(Config, "ENTERPRISE_CONTACT_EMAILS", ["team@example.com"])
    monkeypatch.setattr(Config, "SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setattr(Config, "SMTP_PORT", 587)
    monkeypatch.setattr(Config, "SMTP_USERNAME", "sender@gmail.com")
    monkeypatch.setattr(Config, "SMTP_PASSWORD", "app-password")
    monkeypatch.setattr(Config, "SMTP_FROM", "sender@gmail.com")
    monkeypatch.setattr(Config, "SMTP_USE_TLS", True)

    recipients = EmailNotifier(smtp_factory=FakeSMTP).send_enterprise_contact(
        requester_email="buyer@example.com",
        site_url="https://example.com",
        run_id="run_123",
        note="Need auth + checkout coverage",
    )

    assert recipients == ["team@example.com"]
    assert len(messages) == 1
    assert messages[0]["To"] == "team@example.com"
    assert "Need auth + checkout coverage" in messages[0].get_content()
