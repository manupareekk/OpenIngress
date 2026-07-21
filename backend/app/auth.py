"""Supabase JWT authentication for Flask routes."""

from __future__ import annotations

import functools
import ssl
from typing import Any, Callable, Optional

import certifi
import jwt
from flask import g, jsonify, request
from jwt import PyJWKClient

from .config import Config

_jwks_client: PyJWKClient | None = None


class AuthError(Exception):
    def __init__(self, message: str, status: int = 401) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def _jwks_url() -> str:
    return f"{Config.SUPABASE_URL.rstrip('/')}/auth/v1/.well-known/jwks.json"


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        _jwks_client = PyJWKClient(_jwks_url(), cache_keys=True, ssl_context=ssl_context)
    return _jwks_client


def auth_configured() -> bool:
    return bool(Config.SUPABASE_URL)


def _bearer_token() -> Optional[str]:
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[7:].strip()
    return None


def verify_supabase_jwt(token: str) -> dict[str, Any]:
    if not auth_configured():
        raise AuthError("Auth is not configured", 503)

    issuer = f"{Config.SUPABASE_URL.rstrip('/')}/auth/v1"
    decode_kwargs: dict[str, Any] = {
        "algorithms": ["ES256", "RS256", "HS256"],
        "audience": "authenticated",
        "issuer": issuer,
    }

    try:
        if Config.SUPABASE_JWT_SECRET:
            return jwt.decode(token, Config.SUPABASE_JWT_SECRET, algorithms=["HS256"], audience="authenticated")
        signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
        return jwt.decode(token, signing_key.key, **decode_kwargs)
    except jwt.PyJWTError as exc:
        raise AuthError("Invalid or expired session") from exc


def resolve_user(optional: bool = False) -> Optional[dict[str, Any]]:
    if Config.AUTH_DISABLED:
        g.user = {"id": "dev", "email": "dev@local", "is_enterprise": True}
        g.user_id = "dev"
        return g.user

    token = _bearer_token()
    if not token:
        if optional:
            g.user = None
            g.user_id = None
            return None
        raise AuthError("Sign in required")

    claims = verify_supabase_jwt(token)
    user = {
        "id": claims.get("sub"),
        "email": claims.get("email"),
        "is_enterprise": False,
    }
    g.user = user
    g.user_id = user["id"]
    return user


def require_auth(fn: Callable) -> Callable:
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            resolve_user(optional=False)
        except AuthError as exc:
            return jsonify({"error": exc.message}), exc.status
        return fn(*args, **kwargs)

    return wrapper


def optional_auth(fn: Callable) -> Callable:
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            resolve_user(optional=True)
        except AuthError as exc:
            return jsonify({"error": exc.message}), exc.status
        return fn(*args, **kwargs)

    return wrapper
