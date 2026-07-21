import os
import re

from flask import Blueprint, g, jsonify, request, send_from_directory

from ..auth import require_auth
from ..config import Config
from ..services.codex_nav_audit import CodexAuditError, CodexNavigabilityAuditManager
from ..services.internal_audit_auth import InternalAuditAuthError, verify_job_token
from ..services.internal_model_gateway import forward_responses_request
from ..services.readiness_manager import ReadinessManager, RUNS_DIR
from ..services.site_validation import StorefrontValidationError, assert_storefront_url, validate_storefront_url

ingress_bp = Blueprint("ingress", __name__)
internal_bp = Blueprint("internal", __name__)

_SAFE_FILENAME = re.compile(r"^[a-zA-Z0-9._-]+$")


@ingress_bp.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "auth_disabled": Config.AUTH_DISABLED})


@ingress_bp.route("/account/me", methods=["GET"])
@require_auth
def account_me():
    """OSS account stub — billing is disabled; audits are always allowed when authenticated."""
    user = g.user or {}
    return jsonify(
        {
            "id": user.get("id") or getattr(g, "user_id", None),
            "email": user.get("email") or None,
            "billing_disabled": True,
            "can_run_audit": True,
            "is_enterprise": False,
            "balance": None,
            # Compat fields for frontend useAuth.refreshBilling
            "credits": None,
            "teaser_used": False,
            "teaser_available": True,
        }
    )


@ingress_bp.route("/config/llm", methods=["GET"])
def llm_config():
    from ..config import Config as AppConfig

    return jsonify(AppConfig.llm_status())


@ingress_bp.route("/site-validation", methods=["POST"])
@require_auth
def validate_site():
    data = request.get_json(silent=True) or {}
    url = str(data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "url is required"}), 400
    try:
        return jsonify(validate_storefront_url(url))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


def _codex_nav_enabled_response():
    if Config.CODEX_NAV_AUDIT_ENABLED:
        return None
    return jsonify({"error": "Codex navigability audits are disabled."}), 404


def _internal_bearer_token() -> str:
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[7:].strip()
    raise InternalAuditAuthError("Internal audit token is required.")


@ingress_bp.route("/codex-audits", methods=["POST"])
@require_auth
def create_codex_audit():
    disabled = _codex_nav_enabled_response()
    if disabled:
        return disabled
    data = request.get_json(silent=True) or {}
    url = str(data.get("url") or "").strip()
    title = str(data.get("title") or "").strip()
    if not url:
        return jsonify({"error": "url is required"}), 400
    user_id = getattr(g, "user_id", None)
    user = getattr(g, "user", {}) or {}
    try:
        assert_storefront_url(url)
        state = CodexNavigabilityAuditManager().create_audit(
            url,
            title=title,
            user_id=user_id,
            user_email=user.get("email") or "",
            commerce_inputs=data.get("commerce_inputs") or {},
        )
        return jsonify({"state": state})
    except StorefrontValidationError as exc:
        return jsonify({"error": str(exc), "validation": exc.result}), 422
    except ValueError as exc:
        status = 402 if "credit" in str(exc).lower() or "purchase" in str(exc).lower() else 400
        return jsonify({"error": str(exc)}), status


@ingress_bp.route("/codex-audits/<run_id>", methods=["GET"])
@require_auth
def get_codex_audit(run_id: str):
    disabled = _codex_nav_enabled_response()
    if disabled:
        return disabled
    user_id = getattr(g, "user_id", None)
    try:
        return jsonify(CodexNavigabilityAuditManager().get_audit(run_id, user_id=user_id))
    except FileNotFoundError:
        return jsonify({"error": "Audit not found"}), 404
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except CodexAuditError as exc:
        return jsonify({"error": str(exc)}), 400


@ingress_bp.route("/codex-audits/<run_id>/cancel", methods=["POST"])
@require_auth
def cancel_codex_audit(run_id: str):
    disabled = _codex_nav_enabled_response()
    if disabled:
        return disabled
    user_id = getattr(g, "user_id", None)
    try:
        state = CodexNavigabilityAuditManager().cancel_audit(run_id, user_id=user_id)
        return jsonify({"state": state})
    except FileNotFoundError:
        return jsonify({"error": "Audit not found"}), 404
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403


@internal_bp.route("/openai/responses", methods=["POST"])
def internal_openai_responses():
    try:
        claims = verify_job_token(_internal_bearer_token(), audience="model_gateway")
        payload = request.get_json(silent=True) or {}
        if str(claims.get("run_id") or "") != str(payload.get("metadata", {}).get("run_id") or claims.get("run_id")):
            # Codex may not send metadata.run_id; allow omission but reject mismatches.
            raise InternalAuditAuthError("Internal audit token run id mismatch.")
        status, headers, body = forward_responses_request(payload)
        return body, status, headers
    except InternalAuditAuthError as exc:
        return jsonify({"error": str(exc)}), 401
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 503


@ingress_bp.route("/runs", methods=["GET"])
@require_auth
def list_runs():
    user_id = getattr(g, "user_id", None)
    return jsonify({"runs": ReadinessManager().list_runs(user_id)})


@ingress_bp.route("/runs", methods=["POST"])
@require_auth
def create_run():
    payload = request.get_json(silent=True) or {}
    user_id = getattr(g, "user_id", None)
    user = getattr(g, "user", {}) or {}
    try:
        state = ReadinessManager().create_run(
            payload,
            user_id=user_id,
            user_email=user.get("email") or "",
        )
        return jsonify(state)
    except ValueError as exc:
        message = str(exc)
        status = 400 if "LLM_API_KEY" in message else 402
        return jsonify({"error": message}), status
    except OSError as exc:
        return jsonify({"error": f"Could not create audit workspace: {exc}"}), 500


@ingress_bp.route("/runs/<run_id>/check", methods=["GET"])
@require_auth
def get_run_check(run_id: str):
    user_id = getattr(g, "user_id", None)
    try:
        ReadinessManager().assert_run_access(run_id, user_id)
        return jsonify(ReadinessManager().get_teaser_check(run_id))
    except FileNotFoundError:
        return jsonify({"error": "Audit not found"}), 404
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@ingress_bp.route("/runs/<run_id>", methods=["GET"])
@require_auth
def get_run(run_id: str):
    user_id = getattr(g, "user_id", None)
    try:
        ReadinessManager().assert_run_access(run_id, user_id)
        return jsonify(ReadinessManager().get_run(run_id))
    except FileNotFoundError as exc:
        return jsonify({"error": "Audit not found"}), 404
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@ingress_bp.route("/runs/<run_id>/cancel", methods=["POST"])
@require_auth
def cancel_run(run_id: str):
    user_id = getattr(g, "user_id", None)
    try:
        ReadinessManager().assert_run_access(run_id, user_id)
        state = ReadinessManager().cancel_run(run_id, user_id)
        return jsonify({"state": state})
    except FileNotFoundError:
        return jsonify({"error": "Audit not found"}), 404
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403


@ingress_bp.route("/runs/<run_id>/import", methods=["POST"])
@require_auth
def import_snapshot(run_id: str):
    data = request.get_json(silent=True) or {}
    url = str(data.get("url") or "").strip()
    phase = str(data.get("phase") or "before")
    user_id = getattr(g, "user_id", None)
    if not url:
        return jsonify({"error": "url is required"}), 400
    try:
        ReadinessManager().assert_run_access(run_id, user_id)
        result = ReadinessManager().import_snapshot(run_id, phase, url, user_id=user_id)
        return jsonify(result)
    except FileNotFoundError:
        return jsonify({"error": "Audit not found"}), 404
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 402
    except Exception:
        return jsonify({"error": "Import failed"}), 500


@ingress_bp.route("/runs/<run_id>/navigation", methods=["GET"])
@require_auth
def get_navigation(run_id: str):
    user_id = getattr(g, "user_id", None)
    try:
        ReadinessManager().assert_run_access(run_id, user_id)
        return jsonify(ReadinessManager().get_navigation(run_id))
    except FileNotFoundError:
        return jsonify({"error": "Audit not found"}), 404
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403


@ingress_bp.route("/runs/<run_id>/execute", methods=["POST"])
@require_auth
def execute_run(run_id: str):
    user_id = getattr(g, "user_id", None)
    try:
        ReadinessManager().assert_run_access(run_id, user_id)
        result = ReadinessManager().execute_run(run_id)
        return jsonify(result)
    except FileNotFoundError:
        return jsonify({"error": "Audit not found"}), 404
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except Exception:
        return jsonify({"error": "Execution failed"}), 500


@ingress_bp.route("/runs/<run_id>/explore", methods=["POST"])
@require_auth
def explore_run(run_id: str):
    user_id = getattr(g, "user_id", None)
    try:
        ReadinessManager().assert_run_access(run_id, user_id)
        result = ReadinessManager().explore_run(run_id)
        return jsonify(result)
    except FileNotFoundError:
        return jsonify({"error": "Audit not found"}), 404
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except ValueError as exc:
        message = str(exc)
        status = 400 if "LLM_API_KEY" in message else 402
        return jsonify({"error": message}), status
    except Exception:
        return jsonify({"error": "Exploration failed"}), 500


@ingress_bp.route("/runs/<run_id>/screenshots/<filename>", methods=["GET"])
@require_auth
def run_screenshot(run_id: str, filename: str):
    if not _SAFE_FILENAME.match(filename or ""):
        return jsonify({"error": "Invalid filename"}), 400
    user_id = getattr(g, "user_id", None)
    try:
        ReadinessManager().assert_run_access(run_id, user_id)
    except (FileNotFoundError, PermissionError):
        return jsonify({"error": "Not found"}), 404
    directory = os.path.join(RUNS_DIR, run_id, "screenshots")
    if not os.path.isfile(os.path.join(directory, filename)):
        return jsonify({"error": "Screenshot not found"}), 404
    return send_from_directory(directory, filename)
