import json
import io
import os
import subprocess

import pytest

from app import create_app
from app.config import Config
from app.models import RunStatus
from app.services.codex_nav_audit import (
    CodexNavigabilityAuditManager,
    _apply_runtime_limitations,
    _codex_subprocess_env,
    ensure_codex_config,
)


def _result(url="https://example.com/"):
    return {
        "url": url,
        "score": 88,
        "verdict": "agent-ready",
        "confidence": "high",
        "executive_summary": "Agents can understand and operate the page.",
        "metrics": {
            "agent_visibility": 90,
            "control_addressability": 88,
            "action_success": 85,
            "friction": 91,
        },
        "what_agents_can_see": ["Headings and primary navigation are visible."],
        "what_agents_can_do": ["Open primary navigation links."],
        "blockers": [],
        "recommended_fixes": [],
        "evidence": {
            "steps_taken": ["Opened the submitted page."],
            "tools_used": ["Codex CLI"],
            "limitations": [],
        },
    }


class _FakePopen:
    last_cmd = []
    last_env = {}

    def __init__(self, cmd, stdin=None, stdout=None, stderr=None, text=None, env=None):
        _FakePopen.last_cmd = list(cmd)
        _FakePopen.last_env = dict(env or {})
        self.cmd = cmd
        self.args = cmd
        self.stdin = io.StringIO()
        self.stdout = stdout
        self.stderr = stderr
        self.text = text
        self.result_path = cmd[cmd.index("--output-last-message") + 1]
        self.returncode = None
        self.polled = False

    def _finish(self):
        with open(self.result_path, "w", encoding="utf-8") as handle:
            json.dump(_result(), handle)
        if self.stdout:
            self.stdout.write(json.dumps({"event": "done"}) + "\n")
        self.returncode = 0

    def communicate(self, prompt=None, timeout=None):
        self._finish()
        return ("", "")

    def poll(self):
        if self.returncode is None and not self.polled:
            self.polled = True
            self._finish()
        return self.returncode

    def terminate(self):
        self.returncode = -15

    def kill(self):
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


def test_codex_audit_route_disabled(monkeypatch):
    monkeypatch.setattr(Config, "AUTH_DISABLED", True)
    monkeypatch.setattr(Config, "CODEX_NAV_AUDIT_ENABLED", False)
    client = create_app().test_client()

    response = client.post("/api/ingress/codex-audits", json={"url": "https://example.com"})

    assert response.status_code == 404


def test_codex_audit_route_validates_url(monkeypatch):
    monkeypatch.setattr(Config, "AUTH_DISABLED", True)
    monkeypatch.setattr(Config, "CODEX_NAV_AUDIT_ENABLED", True)
    client = create_app().test_client()

    response = client.post("/api/ingress/codex-audits", json={})

    assert response.status_code == 400


def test_codex_audit_route_creates_async_state(monkeypatch):
    monkeypatch.setattr(Config, "AUTH_DISABLED", True)
    monkeypatch.setattr(Config, "CODEX_NAV_AUDIT_ENABLED", True)

    class FakeManager:
        def create_audit(self, url, title="", user_id=None, user_email="", commerce_inputs=None):
            return {
                "run_id": "codex_run_123",
                "status": RunStatus.RUNNING.value,
                "url": url,
                "title": title,
                "user_id": user_id,
                "requester_email": user_email,
                "commerce_inputs": commerce_inputs or {},
            }

    monkeypatch.setattr("app.api.ingress.CodexNavigabilityAuditManager", lambda: FakeManager())
    client = create_app().test_client()

    response = client.post(
        "/api/ingress/codex-audits",
        json={
            "url": "https://example.com",
            "title": "Homepage regression",
            "commerce_inputs": {"monthly_sessions": 50000},
        },
    )

    assert response.status_code == 200
    assert response.get_json()["state"]["run_id"] == "codex_run_123"
    assert response.get_json()["state"]["user_id"] == "dev"
    assert response.get_json()["state"]["title"] == "Homepage regression"
    assert response.get_json()["state"]["requester_email"] == "dev@local"
    assert response.get_json()["state"]["commerce_inputs"] == {"monthly_sessions": 50000}


def test_codex_audit_queued_mode_enqueues_job(monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr(Config, "JOB_EXECUTION_MODE", "queued")
    monkeypatch.setattr(Config, "OPENINGRESS_JOB_TOKEN_SIGNING_SECRET", "secret-signing-key-0123456789abcdef")
    monkeypatch.setattr("app.services.codex_nav_audit.enqueue_job", lambda payload: sent.append(payload))
    monkeypatch.setattr(
        CodexNavigabilityAuditManager,
        "_create_paired_readiness_run",
        lambda self, url, title, user_id=None, user_email="", linked_codex_run_id="", commerce_inputs=None: {
            "state": {
                "run_id": "run_pair_123",
                "title": title,
                "requester_email": user_email,
            }
        },
    )

    manager = CodexNavigabilityAuditManager(base_dir=str(tmp_path))
    state = manager.create_audit(
        "https://example.com",
        title="Homepage regression",
        user_id="dev",
        user_email="owner@example.com",
        commerce_inputs={"monthly_sessions": 50000, "agent_traffic_share": 5},
    )

    assert state["status"] == RunStatus.QUEUED.value
    assert state["progress"] == "Queued combined Codex + Playwright audit..."
    assert state["title"] == "Homepage regression"
    assert len(sent) == 1
    assert sent[0]["job_type"] == "codex_nav_audit"
    assert sent[0]["run_id"] == state["run_id"]
    assert sent[0]["url"] == "https://example.com"
    assert sent[0]["paired_run_id"] == "run_pair_123"
    assert sent[0]["commerce_inputs"] == {"monthly_sessions": 50000, "agent_traffic_share": 5}
    assert sent[0]["job_token"]


def test_codex_paired_readiness_run_preserves_title_and_requester(monkeypatch, tmp_path):
    captured = {}

    class FakeReadinessManager:
        def __init__(self, base_dir):
            captured["base_dir"] = base_dir

        def create_run(self, payload, user_id=None, user_email=None):
            captured["payload"] = dict(payload)
            captured["user_id"] = user_id
            captured["user_email"] = user_email
            return {"run_id": "run_pair_123"}

        def import_snapshot(self, run_id, phase, url, user_id=None):
            captured["import"] = {
                "run_id": run_id,
                "phase": phase,
                "url": url,
                "user_id": user_id,
            }

    monkeypatch.setattr("app.services.codex_nav_audit.ReadinessManager", FakeReadinessManager)

    manager = CodexNavigabilityAuditManager(base_dir=str(tmp_path))
    paired = manager._create_paired_readiness_run(
        "https://example.com",
        title="Homepage regression",
        user_id="user_123",
        user_email="owner@example.com",
        linked_codex_run_id="codex_run_123",
        commerce_inputs={"monthly_sessions": 50000, "average_order_value": 85},
    )

    assert paired["run_id"] == "run_pair_123"
    assert captured["payload"]["title"] == "Homepage regression"
    assert captured["payload"]["linked_codex_run_id"] == "codex_run_123"
    assert captured["payload"]["commerce_inputs"] == {"monthly_sessions": 50000, "average_order_value": 85}
    assert captured["user_id"] == "user_123"
    assert captured["user_email"] == "owner@example.com"
    assert captured["import"] == {
        "run_id": "run_pair_123",
        "phase": "before",
        "url": "https://example.com",
        "user_id": "user_123",
    }


def test_codex_worker_success_writes_result(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "CODEX_NAV_AUDIT_TIMEOUT_SECONDS", 10)
    monkeypatch.setattr(Config, "CODEX_NAV_AUDIT_SANDBOX", "workspace-write")
    monkeypatch.setattr("app.services.codex_nav_audit.subprocess.Popen", _FakePopen)
    manager = CodexNavigabilityAuditManager(base_dir=str(tmp_path))
    run_id = "codex_run_success"
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    manager._write_json(
        str(run_dir),
        "codex_state.json",
        {"run_id": run_id, "status": RunStatus.RUNNING.value, "url": "https://example.com/"},
    )
    manager._write_json(
        str(run_dir),
        "codex_private.json",
        {
            "job_token": "token-123",
            "internal_gateway_base_url": "https://gateway.internal/openai",
            "internal_proxy_url": "http://proxy.internal:8877",
            "allowed_internal_hosts": ["gateway.internal", "proxy.internal"],
        },
    )

    manager._run_worker(run_id)

    state = manager._read_json(str(run_dir / "codex_state.json"))
    result = manager._read_json(str(run_dir / "codex_result.json"))
    assert state["status"] == RunStatus.COMPLETED.value
    assert result["verdict"] == "agent-ready"
    assert not (run_dir / "audit.json").exists()
    assert not (run_dir / "agent_report.json").exists()
    assert "--ask-for-approval" not in _FakePopen.last_cmd
    assert _FakePopen.last_cmd[_FakePopen.last_cmd.index("--sandbox") + 1] == "workspace-write"
    assert "sandbox_workspace_write.network_access=true" in _FakePopen.last_cmd
    assert "--ignore-rules" in _FakePopen.last_cmd
    assert "--search" in _FakePopen.last_cmd
    assert _FakePopen.last_env["OPENINGRESS_GATEWAY_TOKEN"] == "token-123"
    assert _FakePopen.last_env["HTTP_PROXY"].startswith("http://token:")


def test_codex_completion_sends_paired_email_when_rendered_audit_already_done(monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr(
        "app.services.readiness_manager.EmailNotifier.send_completion",
        lambda self, *, state, requester_email="": sent.append((state["run_id"], requester_email)) or [requester_email],
    )
    manager = CodexNavigabilityAuditManager(base_dir=str(tmp_path))
    paired_dir = tmp_path / "run_pair_123"
    paired_dir.mkdir()
    manager._write_json(
        str(paired_dir),
        "state.json",
        {
            "run_id": "run_pair_123",
            "status": RunStatus.COMPLETED.value,
            "requester_email": "owner@example.com",
            "linked_codex_run_id": "codex_run_123",
        },
    )

    manager._send_paired_completion_notification_when_ready(
        {
            "run_id": "codex_run_123",
            "status": RunStatus.COMPLETED.value,
            "paired_run_id": "run_pair_123",
        }
    )

    assert sent == [("run_pair_123", "owner@example.com")]
    state = manager._read_json(str(paired_dir / "state.json"))
    assert state["completion_email_sent"] is True


def test_codex_env_skips_unavailable_loopback_proxy(monkeypatch, tmp_path):
    monkeypatch.setenv("HTTP_PROXY", "http://stale.proxy:8080")
    monkeypatch.setenv("HTTPS_PROXY", "http://stale.proxy:8080")

    env = _codex_subprocess_env(
        codex_home=str(tmp_path),
        gateway_token="token-123",
        proxy_url="http://token:token-123@127.0.0.1:1",
        allowed_internal_hosts=["127.0.0.1"],
    )

    assert "HTTP_PROXY" not in env
    assert "HTTPS_PROXY" not in env
    assert env["OPENINGRESS_GATEWAY_TOKEN"] == "token-123"


def test_codex_worker_isolates_home_and_uses_unsandboxed_danger_mode(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "CODEX_NAV_AUDIT_TIMEOUT_SECONDS", 10)
    monkeypatch.setattr(Config, "CODEX_NAV_AUDIT_SANDBOX", "danger-full-access")
    monkeypatch.setenv("AZURE_SERVICE_BUS_CONNECTION_STRING", "secret-bus")
    monkeypatch.setenv("HOME", "/Users/shared-real-home")
    monkeypatch.setenv("CODEX_HOME", "/Users/shared-real-home/.codex")
    monkeypatch.setattr("app.services.codex_nav_audit.subprocess.Popen", _FakePopen)
    manager = CodexNavigabilityAuditManager(base_dir=str(tmp_path))
    run_id = "codex_run_danger"
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    manager._write_json(
        str(run_dir),
        "codex_state.json",
        {"run_id": run_id, "status": RunStatus.RUNNING.value, "url": "https://example.com/"},
    )
    manager._write_json(
        str(run_dir),
        "codex_private.json",
        {
            "job_token": "token-123",
            "internal_gateway_base_url": "https://gateway.internal/openai",
            "internal_proxy_url": "http://proxy.internal:8877",
            "allowed_internal_hosts": ["gateway.internal", "proxy.internal"],
        },
    )

    manager._run_worker(run_id)

    assert "--dangerously-bypass-approvals-and-sandbox" in _FakePopen.last_cmd
    assert "--sandbox" not in _FakePopen.last_cmd
    assert "sandbox_workspace_write.network_access=true" not in _FakePopen.last_cmd
    assert "AZURE_OPENAI_API_KEY" not in _FakePopen.last_env
    assert "AZURE_SERVICE_BUS_CONNECTION_STRING" not in _FakePopen.last_env
    assert _FakePopen.last_env["HOME"] != "/Users/shared-real-home"
    assert _FakePopen.last_env["CODEX_HOME"] != "/Users/shared-real-home/.codex"
    assert _FakePopen.last_env["HOME"] == _FakePopen.last_env["CODEX_HOME"]


def test_codex_worker_timeout_marks_failed(monkeypatch, tmp_path):
    class TimeoutPopen(_FakePopen):
        def poll(self):
            return self.returncode

    monkeypatch.setattr(Config, "CODEX_NAV_AUDIT_TIMEOUT_SECONDS", 1)
    monkeypatch.setattr("app.services.codex_nav_audit.subprocess.Popen", TimeoutPopen)
    monkeypatch.setattr("app.services.codex_nav_audit.time.sleep", lambda seconds: None)
    ticks = iter([0, 2])
    monkeypatch.setattr("app.services.codex_nav_audit.time.monotonic", lambda: next(ticks, 2))
    manager = CodexNavigabilityAuditManager(base_dir=str(tmp_path))
    run_id = "codex_run_timeout"
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    manager._write_json(
        str(run_dir),
        "codex_state.json",
        {"run_id": run_id, "status": RunStatus.RUNNING.value, "url": "https://example.com/"},
    )
    manager._write_json(
        str(run_dir),
        "codex_private.json",
        {
            "job_token": "token-123",
            "internal_gateway_base_url": "https://gateway.internal/openai",
            "internal_proxy_url": "http://proxy.internal:8877",
            "allowed_internal_hosts": ["gateway.internal", "proxy.internal"],
        },
    )

    manager._run_worker(run_id)

    state = manager._read_json(str(run_dir / "codex_state.json"))
    result = manager._read_json(str(run_dir / "codex_result.json"))
    assert state["status"] == RunStatus.COMPLETED.value
    assert state["codex_runtime_error"] == "Codex audit timed out"
    assert result["verdict"] == "inconclusive"
    assert "timed out" in result["evidence"]["limitations"][0]


def test_codex_worker_invalid_json_marks_failed(monkeypatch, tmp_path):
    class InvalidJsonPopen(_FakePopen):
        def _finish(self):
            with open(self.result_path, "w", encoding="utf-8") as handle:
                handle.write("not json")
            self.returncode = 0

    monkeypatch.setattr(Config, "CODEX_NAV_AUDIT_TIMEOUT_SECONDS", 10)
    monkeypatch.setattr("app.services.codex_nav_audit.subprocess.Popen", InvalidJsonPopen)
    manager = CodexNavigabilityAuditManager(base_dir=str(tmp_path))
    run_id = "codex_run_invalid"
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    manager._write_json(
        str(run_dir),
        "codex_state.json",
        {"run_id": run_id, "status": RunStatus.RUNNING.value, "url": "https://example.com/"},
    )
    manager._write_json(
        str(run_dir),
        "codex_private.json",
        {
            "job_token": "token-123",
            "internal_gateway_base_url": "https://gateway.internal/openai",
            "internal_proxy_url": "http://proxy.internal:8877",
            "allowed_internal_hosts": ["gateway.internal", "proxy.internal"],
        },
    )

    manager._run_worker(run_id)

    state = manager._read_json(str(run_dir / "codex_state.json"))
    result = manager._read_json(str(run_dir / "codex_result.json"))
    assert state["status"] == RunStatus.COMPLETED.value
    assert state["codex_runtime_error"] == "Codex returned invalid JSON"
    assert result["verdict"] == "inconclusive"
    assert "invalid JSON" in result["evidence"]["limitations"][0]


def test_codex_worker_cancelled_by_shared_state_terminates(monkeypatch, tmp_path):
    class CancelPopen(_FakePopen):
        def poll(self):
            if self.returncode is None and not self.polled:
                self.polled = True
                with open(run_dir / "codex_state.json", encoding="utf-8") as handle:
                    state = json.load(handle)
                state["cancel_requested"] = True
                with open(run_dir / "codex_state.json", "w", encoding="utf-8") as handle:
                    json.dump(state, handle)
            return self.returncode

    monkeypatch.setattr(Config, "CODEX_NAV_AUDIT_TIMEOUT_SECONDS", 10)
    monkeypatch.setattr("app.services.codex_nav_audit.subprocess.Popen", CancelPopen)
    monkeypatch.setattr("app.services.codex_nav_audit.time.sleep", lambda seconds: None)
    manager = CodexNavigabilityAuditManager(base_dir=str(tmp_path))
    run_id = "codex_run_cancel"
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    manager._write_json(
        str(run_dir),
        "codex_state.json",
        {"run_id": run_id, "status": RunStatus.RUNNING.value, "url": "https://example.com/"},
    )
    manager._write_json(
        str(run_dir),
        "codex_private.json",
        {
            "job_token": "token-123",
            "internal_gateway_base_url": "https://gateway.internal/openai",
            "internal_proxy_url": "http://proxy.internal:8877",
            "allowed_internal_hosts": ["gateway.internal", "proxy.internal"],
        },
    )

    manager._run_worker(run_id)

    state = manager._read_json(str(run_dir / "codex_state.json"))
    assert state["status"] == RunStatus.FAILED.value
    assert state["error"] == "Cancelled by user"
    assert state["cancel_requested"] is True


def test_codex_process_queued_job_skips_cancelled(tmp_path):
    manager = CodexNavigabilityAuditManager(base_dir=str(tmp_path))
    run_id = "codex_run_queued_cancel"
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    manager._write_json(
        str(run_dir),
        "codex_state.json",
        {
            "run_id": run_id,
            "user_id": "dev",
            "status": RunStatus.FAILED.value,
            "error": "Cancelled by user",
            "cancel_requested": True,
            "url": "https://example.com/",
        },
    )

    result = manager.process_queued_job(
        {"job_type": "codex_nav_audit", "job_id": f"{run_id}:codex_nav_audit:none", "run_id": run_id}
    )

    assert result["reason"] == "cancelled"


def test_runtime_limitation_rewrites_inconclusive_site_blame(tmp_path):
    stdout_path = tmp_path / "codex_stdout.jsonl"
    stderr_path = tmp_path / "codex_stderr.log"
    stdout_path.write_text(
        '{"type":"item.completed","item":{"aggregated_output":"bwrap: No permissions to create a new namespace"}}\n',
        encoding="utf-8",
    )
    stderr_path.write_text("", encoding="utf-8")
    result = {
        "url": "https://manupareek.com",
        "score": 0,
        "verdict": "inconclusive",
        "confidence": "low",
        "executive_summary": "Direct inspection did not yield rendered page content.",
        "metrics": {
            "agent_visibility": 0,
            "control_addressability": 0,
            "action_success": 0,
            "friction": 0,
        },
        "what_agents_can_see": ["Nothing inspectable."],
        "what_agents_can_do": ["Nothing verifiable."],
        "blockers": [
            {"severity": "high", "title": "No directly inspectable page content", "detail": "empty", "evidence": "empty"}
        ],
        "recommended_fixes": [{"priority": "high", "title": "Ensure server-rendered baseline content is available", "detail": "site fix"}],
        "evidence": {"steps_taken": [], "tools_used": ["web.open"], "limitations": ["empty page"]},
    }

    _apply_runtime_limitations(
        result,
        expected_url="https://manupareek.com",
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
    )

    assert result["verdict"] == "inconclusive"
    assert result["score"] == 0
    assert "worker-runtime limitation" in result["blockers"][0]["detail"]
    assert "paired rendered-browser audit" in result["recommended_fixes"][0]["detail"]
    assert result["evidence"]["tools_used"] == ["Codex CLI", "native web inspection"]


def test_runtime_limitation_rewrites_chromium_permission_error(tmp_path):
    stdout_path = tmp_path / "codex_stdout.jsonl"
    stderr_path = tmp_path / "codex_stderr.log"
    stdout_path.write_text(
        "browserType.launch: Target page, context or browser has been closed\n"
        "bootstrap_check_in org.chromium.Chromium.MachPortRendezvousServer.77410: Permission denied (1100)\n",
        encoding="utf-8",
    )
    stderr_path.write_text("", encoding="utf-8")
    result = {
        "url": "https://www.miemmo.com/",
        "score": 0,
        "verdict": "inconclusive",
        "confidence": "low",
        "executive_summary": "Headless Chromium could not launch.",
        "metrics": {
            "agent_visibility": 0,
            "control_addressability": 0,
            "action_success": 0,
            "friction": 0,
        },
        "what_agents_can_see": ["Empty root."],
        "what_agents_can_do": ["Fetch HTML."],
        "blockers": [
            {"severity": "high", "title": "Chromium failed", "detail": "site uninspectable", "evidence": "permission"}
        ],
        "recommended_fixes": [{"priority": "high", "title": "Server render", "detail": "site fix"}],
        "evidence": {"steps_taken": [], "tools_used": ["npx playwright"], "limitations": ["permission"]},
    }

    _apply_runtime_limitations(
        result,
        expected_url="https://www.miemmo.com/",
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
    )

    assert result["verdict"] == "inconclusive"
    assert result["score"] == 0
    assert "local tooling path was unavailable" in result["executive_summary"]
    assert "MachPortRendezvousServer Permission denied" in result["blockers"][0]["evidence"]
    assert "Server render" not in result["recommended_fixes"][0]["title"]


def test_ensure_codex_config_writes_gateway_provider_without_secret(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / ".codex"))
    monkeypatch.setattr(Config, "AZURE_OPENAI_DEPLOYMENT", "gpt-5.4")
    monkeypatch.setattr(Config, "CODEX_NAV_AUDIT_REASONING_EFFORT", "medium")

    path = ensure_codex_config(base_url="https://gateway.internal/openai", env_key="OPENINGRESS_GATEWAY_TOKEN")

    assert path
    contents = open(path, encoding="utf-8").read()
    assert 'model_provider = "openingress_gateway"' in contents
    assert 'base_url = "https://gateway.internal/openai"' in contents
    assert 'env_key = "OPENINGRESS_GATEWAY_TOKEN"' in contents


def test_codex_audit_access_checks_owner(tmp_path):
    manager = CodexNavigabilityAuditManager(base_dir=str(tmp_path))
    run_id = "codex_run_owner"
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    manager._write_json(
        str(run_dir),
        "codex_state.json",
        {"run_id": run_id, "user_id": "user-a", "status": RunStatus.RUNNING.value},
    )

    with pytest.raises(PermissionError):
        manager.get_audit(run_id, user_id="user-b")
