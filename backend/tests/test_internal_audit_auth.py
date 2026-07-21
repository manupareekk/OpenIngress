from app.config import Config
from app.services.internal_audit_auth import (
    InternalAuditAuthError,
    allowed_internal_hosts_for_urls,
    build_job_token,
    verify_job_token,
)


def test_build_and_verify_job_token(monkeypatch):
    monkeypatch.setattr(Config, "OPENINGRESS_JOB_TOKEN_SIGNING_SECRET", "secret-signing-key")

    payload = build_job_token(
        run_id="codex_run_123",
        job_type="codex_nav_audit",
        target_url="https://example.com",
        target_registrable_domain="example.com",
        allowed_internal_hosts=["gateway.internal", "proxy.internal"],
        ttl_seconds=900,
    )

    claims = verify_job_token(payload["token"], audience="model_gateway", expected_run_id="codex_run_123")
    assert claims["target_registrable_domain"] == "example.com"
    assert "gateway.internal" in claims["allowed_internal_hosts"]


def test_verify_job_token_rejects_wrong_run_id(monkeypatch):
    monkeypatch.setattr(Config, "OPENINGRESS_JOB_TOKEN_SIGNING_SECRET", "secret-signing-key")

    payload = build_job_token(
        run_id="codex_run_123",
        job_type="codex_nav_audit",
        target_url="https://example.com",
        target_registrable_domain="example.com",
        allowed_internal_hosts=["gateway.internal"],
        ttl_seconds=900,
    )

    try:
        verify_job_token(payload["token"], audience="model_gateway", expected_run_id="codex_run_999")
    except InternalAuditAuthError:
        return
    raise AssertionError("Expected InternalAuditAuthError")


def test_allowed_internal_hosts_collects_unique_hosts(monkeypatch):
    monkeypatch.setattr(Config, "OPENINGRESS_ALLOWED_INTERNAL_HOSTS", ["app.internal", "app.internal"])
    monkeypatch.setattr(Config, "APP_URL", "https://frontend.example.com")

    hosts = allowed_internal_hosts_for_urls(
        ["https://gateway.internal/openai", "http://proxy.internal:8877"]
    )

    assert hosts == sorted(set(hosts))
    assert "gateway.internal" in hosts
    assert "proxy.internal" in hosts
    assert "frontend.example.com" in hosts
