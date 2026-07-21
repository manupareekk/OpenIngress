"""Signed job tokens for internal Codex gateway and proxy services."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List
from urllib.parse import urlparse

import jwt

from ..config import Config
from .gap_taxonomy import registrable_domain

_ISSUER = "openingress"


class InternalAuditAuthError(ValueError):
    """Raised when an internal audit token is missing or invalid."""


def internal_service_urls() -> Dict[str, str]:
    default_port = str(os.environ.get("PORT", "5055"))
    gateway = (
        str(Config.OPENINGRESS_INTERNAL_GATEWAY_BASE_URL or "").strip()
        or f"http://127.0.0.1:{default_port}/internal/openai"
    )
    proxy = (
        str(Config.OPENINGRESS_INTERNAL_PROXY_URL or "").strip()
        or "http://127.0.0.1:8877"
    )
    return {"gateway": gateway.rstrip("/"), "proxy": proxy.rstrip("/")}


def _signing_secret() -> str:
    secret = str(Config.OPENINGRESS_JOB_TOKEN_SIGNING_SECRET or "").strip()
    if not secret and Config.AUTH_DISABLED:
        return "dev-openingress-job-token-secret"
    if not secret:
        raise InternalAuditAuthError("OPENINGRESS_JOB_TOKEN_SIGNING_SECRET is required.")
    return secret


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_job_token(
    *,
    run_id: str,
    job_type: str,
    target_url: str,
    target_registrable_domain: str,
    allowed_internal_hosts: Iterable[str],
    ttl_seconds: int | None = None,
) -> Dict[str, Any]:
    now = _utc_now()
    ttl = max(60, int(ttl_seconds or Config.OPENINGRESS_JOB_TOKEN_TTL_SECONDS or 900))
    exp = now + timedelta(seconds=ttl)
    claims = {
        "iss": _ISSUER,
        "sub": str(run_id),
        "run_id": str(run_id),
        "job_type": str(job_type),
        "target_url": str(target_url),
        "target_registrable_domain": str(target_registrable_domain),
        "allowed_internal_hosts": sorted({str(host or "").lower() for host in allowed_internal_hosts if host}),
        "aud": ["model_gateway", "audit_proxy"],
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    token = jwt.encode(claims, _signing_secret(), algorithm="HS256")
    return {"token": token, "expires_at": exp.isoformat().replace("+00:00", "Z"), "claims": claims}


def verify_job_token(token: str, *, audience: str, expected_run_id: str | None = None) -> Dict[str, Any]:
    try:
        claims = jwt.decode(
            token,
            _signing_secret(),
            algorithms=["HS256"],
            audience=audience,
            issuer=_ISSUER,
        )
    except jwt.PyJWTError as exc:
        raise InternalAuditAuthError("Invalid or expired internal audit token.") from exc

    run_id = str(claims.get("run_id") or "")
    if expected_run_id and run_id != str(expected_run_id):
        raise InternalAuditAuthError("Internal audit token run id mismatch.")
    if str(claims.get("job_type") or "") != "codex_nav_audit":
        raise InternalAuditAuthError("Internal audit token job type is invalid.")
    if not str(claims.get("target_registrable_domain") or "").strip():
        raise InternalAuditAuthError("Internal audit token target domain is missing.")
    return claims


def allowed_internal_hosts_for_urls(urls: Iterable[str]) -> List[str]:
    hosts = set(str(host).lower() for host in Config.OPENINGRESS_ALLOWED_INTERNAL_HOSTS if host)
    for value in urls:
        parsed = urlparse(str(value or ""))
        if parsed.hostname:
            hosts.add(parsed.hostname.lower())
    app_host = urlparse(str(Config.APP_URL or "")).hostname
    if app_host:
        hosts.add(app_host.lower())
    return sorted(hosts)


def build_internal_job_auth(*, run_id: str, target_url: str) -> Dict[str, Any]:
    urls = internal_service_urls()
    parsed = urlparse(target_url)
    target_domain = registrable_domain(parsed.netloc)
    allowed_hosts = allowed_internal_hosts_for_urls(urls.values())
    token_payload = build_job_token(
        run_id=run_id,
        job_type="codex_nav_audit",
        target_url=target_url,
        target_registrable_domain=target_domain,
        allowed_internal_hosts=allowed_hosts,
    )
    return {
        "target_url": target_url,
        "target_registrable_domain": target_domain,
        "job_token": token_payload["token"],
        "job_token_expires_at": token_payload["expires_at"],
        "internal_gateway_base_url": urls["gateway"],
        "internal_proxy_url": urls["proxy"],
        "allowed_internal_hosts": allowed_hosts,
    }
