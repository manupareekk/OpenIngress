"""Supabase service-role client for credits and run metadata."""

from __future__ import annotations

from typing import Any, Optional

from ..config import Config

_client = None


def supabase_configured() -> bool:
    return bool(Config.SUPABASE_URL and Config.supabase_api_key())


def get_supabase():
    global _client
    if not supabase_configured():
        return None
    if _client is None:
        from supabase import create_client

        _client = create_client(Config.SUPABASE_URL, Config.supabase_api_key())
    return _client


def ensure_profile(user_id: str, email: str = "") -> None:
    client = get_supabase()
    if not client:
        return
    client.table("profiles").upsert(
        {"id": user_id, "email": email or None},
        on_conflict="id",
    ).execute()


def profile_email(user_id: str) -> str:
    client = get_supabase()
    if not client:
        return ""
    result = client.table("profiles").select("email").eq("id", user_id).limit(1).execute()
    rows = result.data or []
    if not rows:
        return ""
    return str(rows[0].get("email") or "")


def credit_balance(user_id: str) -> int:
    """OSS: billing removed — no credit ledger."""
    return 999


def is_enterprise(user_id: str) -> bool:
    client = get_supabase()
    if not client:
        return False
    result = client.table("profiles").select("is_enterprise").eq("id", user_id).limit(1).execute()
    rows = result.data or []
    if not rows:
        return False
    return bool(rows[0].get("is_enterprise"))


def grant_credits(
    user_id: str,
    delta: int,
    reason: str,
    *,
    run_id: str = "",
) -> None:
    """Legacy no-op helper kept for older call sites; OSS has no credit ledger."""
    return





def credit_entry_exists(user_id: str, *, reason: str, run_id: str = "") -> bool:
    client = get_supabase()
    if not client or not user_id:
        return False
    query = (
        client.table("audit_credits")
        .select("id")
        .eq("user_id", user_id)
        .eq("reason", reason)
        .limit(1)
    )
    if run_id:
        query = query.eq("run_id", run_id)
    result = query.execute()
    return bool(result.data or [])


def consume_credit_if_needed(user_id: str, run_id: str) -> None:
    """OSS: billing removed — audits are always allowed."""
    return


def upsert_run_metadata(
    run_id: str,
    user_id: str,
    *,
    status: str = "draft",
    title: str = "",
    site_url: str = "",
    completed_at: str = "",
    json_blob: dict[str, Any] | None = None,
) -> None:
    client = get_supabase()
    if not client:
        return
    payload = {
        "id": run_id,
        "user_id": user_id,
        "status": status,
        "title": title or None,
        "site_url": site_url or None,
        "json_blob": json_blob or {},
        "storage_prefix": run_id,
    }
    if completed_at:
        payload["completed_at"] = completed_at
    try:
        client.table("runs").upsert(payload, on_conflict="id").execute()
    except Exception as exc:
        if "json_blob" not in str(exc):
            raise
        payload.pop("json_blob", None)
        client.table("runs").upsert(payload, on_conflict="id").execute()


def run_json_blob(run_id: str) -> dict[str, Any]:
    client = get_supabase()
    if not client or not run_id:
        return {}
    try:
        result = client.table("runs").select("json_blob").eq("id", run_id).limit(1).execute()
    except Exception as exc:
        if "json_blob" not in str(exc):
            return {}
        try:
            result = client.table("runs").select("commerce_inputs").eq("id", run_id).limit(1).execute()
        except Exception:
            return {}
        rows = result.data or []
        if not rows:
            return {}
        value = rows[0].get("commerce_inputs")
        return {"commerce_inputs": value} if isinstance(value, dict) else {}
    rows = result.data or []
    if not rows:
        return {}
    value = rows[0].get("json_blob")
    return value if isinstance(value, dict) else {}


def run_commerce_inputs(run_id: str) -> dict[str, Any]:
    value = run_json_blob(run_id).get("commerce_inputs")
    return value if isinstance(value, dict) else {}


def capture_audit_intent(
    user_id: str,
    *,
    email: str = "",
    site_url: str = "",
    source: str = "no_credit_paywall",
    run_id: str = "",
    note: str = "",
) -> None:
    client = get_supabase()
    if not client or not user_id or not site_url:
        return
    ensure_profile(user_id, email)
    client.table("audit_intents").insert(
        {
            "user_id": user_id,
            "email": email or None,
            "site_url": site_url,
            "source": source or "no_credit_paywall",
            "run_id": run_id or None,
            "note": note or None,
        }
    ).execute()


def list_run_ids_for_user(user_id: str) -> Optional[set[str]]:
    client = get_supabase()
    if not client:
        return None
    try:
        result = client.table("runs").select("id").eq("user_id", user_id).execute()
        return {row["id"] for row in (result.data or [])}
    except Exception:
        return set()


def _local_teaser_run_ids_for_user(user_id: str, runs_dir: str) -> set[str]:
    import os
    import json

    found: set[str] = set()
    if not user_id or not os.path.isdir(runs_dir):
        return found
    for name in os.listdir(runs_dir):
        if not name.startswith("run_"):
            continue
        state_path = os.path.join(runs_dir, name, "state.json")
        if not os.path.isfile(state_path):
            continue
        try:
            with open(state_path, encoding="utf-8") as handle:
                state = json.load(handle)
        except Exception:
            continue
        if state.get("user_id") != user_id:
            continue
        if str(state.get("run_mode") or "") == "teaser":
            found.add(str(state.get("run_id") or name))
    return found


def has_used_teaser(user_id: str, *, runs_dir: str = "") -> bool:
    if not user_id or user_id == "dev":
        return False
    if runs_dir and _local_teaser_run_ids_for_user(user_id, runs_dir):
        return True
    if Config.BILLING_DISABLED:
        return False
    client = get_supabase()
    if client:
        try:
            result = (
                client.table("profiles")
                .select("teaser_used_at")
                .eq("id", user_id)
                .limit(1)
                .execute()
            )
            rows = result.data or []
            if rows and rows[0].get("teaser_used_at"):
                return True
        except Exception:
            pass
    return False


def mark_teaser_used(user_id: str, run_id: str = "") -> None:
    if not user_id or user_id == "dev":
        return
    client = get_supabase()
    if client:
        try:
            from datetime import datetime, timezone

            client.table("profiles").upsert(
                {
                    "id": user_id,
                    "teaser_used_at": datetime.now(timezone.utc).isoformat(),
                },
                on_conflict="id",
            ).execute()
            return
        except Exception:
            pass


def run_owned_by_user(run_id: str, user_id: str, *, local_owner_id: str | None = None) -> bool:
    if local_owner_id == user_id:
        return True
    allowed = list_run_ids_for_user(user_id)
    if allowed is None:
        return True
    return run_id in allowed
