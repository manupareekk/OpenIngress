import worker


def test_worker_dispatches_codex_jobs(monkeypatch):
    calls = {}

    class FakeCodexManager:
        def process_queued_job(self, payload):
            calls["codex"] = payload
            return {"run_id": payload["run_id"], "status": "completed"}

    class FakeReadinessManager:
        def process_queued_job(self, payload):
            calls["readiness"] = payload
            return {"run_id": payload["run_id"], "status": "completed"}

    monkeypatch.setattr(worker, "CodexNavigabilityAuditManager", lambda: FakeCodexManager())
    monkeypatch.setattr(worker, "ReadinessManager", lambda: FakeReadinessManager())

    result = worker.process_worker_payload(
        {
            "message_version": 1,
            "job_id": "codex_run_123:codex_nav_audit:none",
            "run_id": "codex_run_123",
            "user_id": "dev",
            "job_type": "codex_nav_audit",
            "phase": None,
            "url": "https://example.com",
            "requested_at": "2026-06-02T00:00:00Z",
        }
    )

    assert result["status"] == "completed"
    assert calls["codex"]["job_type"] == "codex_nav_audit"
    assert "readiness" not in calls


def test_worker_dispatches_existing_jobs(monkeypatch):
    calls = {}

    class FakeCodexManager:
        def process_queued_job(self, payload):
            calls["codex"] = payload
            return {"run_id": payload["run_id"], "status": "completed"}

    class FakeReadinessManager:
        def process_queued_job(self, payload):
            calls["readiness"] = payload
            return {"run_id": payload["run_id"], "status": "completed"}

    monkeypatch.setattr(worker, "CodexNavigabilityAuditManager", lambda: FakeCodexManager())
    monkeypatch.setattr(worker, "ReadinessManager", lambda: FakeReadinessManager())

    result = worker.process_worker_payload(
        {
            "message_version": 1,
            "job_id": "run_123:execute:none",
            "run_id": "run_123",
            "user_id": "dev",
            "job_type": "execute",
            "phase": None,
            "url": None,
            "requested_at": "2026-06-02T00:00:00Z",
        }
    )

    assert result["status"] == "completed"
    assert calls["readiness"]["job_type"] == "execute"
    assert "codex" not in calls
