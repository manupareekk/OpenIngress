"""Internal gateway for Codex model traffic."""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from typing import Any, Dict, Tuple

from ..config import Config


def _azure_gateway_base_url() -> str:
    if Config.AZURE_OPENAI_BASE_URL:
        return Config.AZURE_OPENAI_BASE_URL.rstrip("/")
    endpoint = str(Config.AZURE_OPENAI_ENDPOINT or "").rstrip("/")
    if not endpoint:
        raise ValueError("Azure OpenAI endpoint is not configured.")
    if endpoint.endswith("/openai/v1"):
        return endpoint
    return f"{endpoint}/openai/v1"


def _azure_auth_headers() -> Dict[str, str]:
    if Config.AZURE_OPENAI_API_KEY and Config.OPENINGRESS_INTERNAL_GATEWAY_ALLOW_API_KEY_FALLBACK:
        return {"api-key": Config.AZURE_OPENAI_API_KEY}

    try:
        from azure.identity import DefaultAzureCredential
    except ImportError as exc:
        raise ValueError("azure-identity is required for managed identity gateway auth.") from exc

    credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
    token = credential.get_token("https://cognitiveservices.azure.com/.default")
    return {"Authorization": f"Bearer {token.token}"}


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def forward_responses_request(payload: Dict[str, Any]) -> Tuple[int, Dict[str, str], bytes]:
    body = json.dumps(payload or {}).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        **_azure_auth_headers(),
    }
    request = urllib.request.Request(
        f"{_azure_gateway_base_url()}/responses",
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120, context=_ssl_context()) as response:
            raw = response.read()
            return int(response.status), {"Content-Type": response.headers.get("Content-Type", "application/json")}, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read() if hasattr(exc, "read") else b""
        return int(exc.code), {"Content-Type": exc.headers.get("Content-Type", "application/json")}, raw
