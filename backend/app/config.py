"""OpenIngress configuration — loads local .env files."""

from __future__ import annotations

import os
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_PROJECT_ROOT = _BACKEND_ROOT.parent


def _load_env_files() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    # Local project wins (do not inherit sibling MiroFish keys).
    for path in (
        _PROJECT_ROOT / ".env",
        _BACKEND_ROOT / ".env",
    ):
        if path.is_file():
            load_dotenv(path, override=True)


_load_env_files()


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _resolve_llm_api_key() -> str:
    return _env("LLM_API_KEY") or _env("OPENAI_API_KEY")


class Config:
    LLM_PROVIDER = _env("LLM_PROVIDER", "openai")
    LLM_API_KEY = _resolve_llm_api_key()
    LLM_BASE_URL = _env("LLM_BASE_URL", "https://api.openai.com/v1")
    LLM_MODEL_NAME = _env("LLM_MODEL_NAME", "gpt-4o-mini")

    AZURE_OPENAI_API_KEY = _env("AZURE_OPENAI_API_KEY")
    AZURE_OPENAI_ENDPOINT = _env("AZURE_OPENAI_ENDPOINT")
    AZURE_OPENAI_BASE_URL = _env("AZURE_OPENAI_BASE_URL")
    AZURE_OPENAI_DEPLOYMENT = _env("AZURE_OPENAI_DEPLOYMENT")

    APP_URL = _env("APP_URL", "http://localhost:5175")
    _default_cors = "http://localhost:5175,http://127.0.0.1:5175,http://localhost:5176,http://127.0.0.1:5176"
    CORS_ORIGINS = [o.strip() for o in _env("CORS_ORIGINS", _default_cors).split(",") if o.strip()]

    AUTH_DISABLED = _env("AUTH_DISABLED", "1") == "1"
    BILLING_DISABLED = _env("BILLING_DISABLED", "1") == "1"
    CODEX_NAV_AUDIT_ENABLED = _env("CODEX_NAV_AUDIT_ENABLED", "1" if AUTH_DISABLED else "0") == "1"
    CODEX_NAV_AUDIT_TIMEOUT_SECONDS = int(_env("CODEX_NAV_AUDIT_TIMEOUT_SECONDS", "300") or "300")
    CODEX_NAV_AUDIT_BIN = _env("CODEX_NAV_AUDIT_BIN", "codex")
    CODEX_NAV_AUDIT_REASONING_EFFORT = _env("CODEX_NAV_AUDIT_REASONING_EFFORT", "medium")
    CODEX_NAV_AUDIT_SANDBOX = _env("CODEX_NAV_AUDIT_SANDBOX", "workspace-write")
    OPENINGRESS_INTERNAL_GATEWAY_BASE_URL = _env("OPENINGRESS_INTERNAL_GATEWAY_BASE_URL")
    OPENINGRESS_INTERNAL_PROXY_URL = _env("OPENINGRESS_INTERNAL_PROXY_URL")
    OPENINGRESS_JOB_TOKEN_SIGNING_SECRET = _env("OPENINGRESS_JOB_TOKEN_SIGNING_SECRET")
    OPENINGRESS_INTERNAL_SERVICE_MODE = _env("OPENINGRESS_INTERNAL_SERVICE_MODE", "public")
    OPENINGRESS_JOB_TOKEN_TTL_SECONDS = int(_env("OPENINGRESS_JOB_TOKEN_TTL_SECONDS", "900") or "900")
    OPENINGRESS_ALLOWED_INTERNAL_HOSTS = [
        host.strip().lower()
        for host in _env("OPENINGRESS_ALLOWED_INTERNAL_HOSTS").split(",")
        if host.strip()
    ]
    OPENINGRESS_INTERNAL_GATEWAY_ALLOW_API_KEY_FALLBACK = (
        _env("OPENINGRESS_INTERNAL_GATEWAY_ALLOW_API_KEY_FALLBACK", "1") != "0"
    )

    JOB_EXECUTION_MODE = _env("JOB_EXECUTION_MODE", "inline")
    AZURE_SERVICE_BUS_CONNECTION_STRING = _env("AZURE_SERVICE_BUS_CONNECTION_STRING")
    AZURE_SERVICE_BUS_QUEUE_NAME = _env("AZURE_SERVICE_BUS_QUEUE_NAME", "audit-jobs")
    QUEUED_RUN_STALE_SECONDS = int(_env("QUEUED_RUN_STALE_SECONDS", "900") or "900")

    JOB_NOTIFICATION_ENABLED = _env("JOB_NOTIFICATION_ENABLED") == "1"
    JOB_NOTIFICATION_TEAM_EMAILS = [
        email.strip()
        for email in _env("JOB_NOTIFICATION_TEAM_EMAILS").split(",")
        if email.strip()
    ]
    SMTP_HOST = _env("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT = int(_env("SMTP_PORT", "587") or "587")
    SMTP_USERNAME = _env("SMTP_USERNAME")
    SMTP_PASSWORD = _env("SMTP_PASSWORD")
    SMTP_FROM = _env("SMTP_FROM") or SMTP_USERNAME
    SMTP_USE_TLS = _env("SMTP_USE_TLS", "1") != "0"

    SUPABASE_URL = _env("SUPABASE_URL")
    SUPABASE_SECRET_KEY = _env("SUPABASE_SECRET_KEY")
    SUPABASE_SERVICE_ROLE_KEY = _env("SUPABASE_SERVICE_ROLE_KEY")
    # Legacy HS256 fallback only — prefer JWKS verification when legacy keys are disabled
    SUPABASE_JWT_SECRET = _env("SUPABASE_JWT_SECRET")

    @classmethod
    def supabase_api_key(cls) -> str:
        return cls.SUPABASE_SECRET_KEY or cls.SUPABASE_SERVICE_ROLE_KEY


    @classmethod
    def llm_available(cls) -> bool:
        if cls.LLM_PROVIDER == "azure_openai":
            return bool(cls.AZURE_OPENAI_API_KEY and (cls.AZURE_OPENAI_BASE_URL or cls.AZURE_OPENAI_ENDPOINT))
        return bool(cls.LLM_API_KEY)

    @classmethod
    def llm_status(cls) -> dict:
        return {
            "available": cls.llm_available(),
            "provider": cls.LLM_PROVIDER,
            "model": cls.LLM_MODEL_NAME if cls.LLM_PROVIDER != "azure_openai" else cls.AZURE_OPENAI_DEPLOYMENT,
            "base_url": cls.LLM_BASE_URL if cls.LLM_PROVIDER != "azure_openai" else (cls.AZURE_OPENAI_BASE_URL or cls.AZURE_OPENAI_ENDPOINT),
            "env_sources_checked": [
                str(p) for p in (_PROJECT_ROOT / ".env", _BACKEND_ROOT / ".env") if p.is_file()
            ],
        }
