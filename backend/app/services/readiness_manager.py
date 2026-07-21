"""Orchestrates import, live operator runs, and before/after comparison."""

from __future__ import annotations

import json
import os
import random
import time
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..config import Config
from ..models import AgentTask, FlowPage, RunStatus, SiteSnapshot, SnapshotPhase
from .job_queue import build_job_message, enqueue_job, parse_job_message
from .live_operator_runner import LiveOperatorRunner
from .notifications import EmailNotifier
from .operability_metrics import (
    accessibility_from_graph,
    compare_before_after,
    task_metrics,
)
from .report_builder import build_report_markdown
from .remediation_export import build_remediation_exports
from .agent_gap_report import build_agent_gap_report, build_agent_report_markdown
from .agent_readiness_score import compute_agent_readiness, refresh_audit_overall_score
from .agent_universe import build_site_universe
from .combined_audit_report import build_combined_audit_report
from .cursor_agent_explorer import explore_like_cursor_agent
from .site_audit_analyzer import SiteAuditAnalyzer
from .static_audits import run_static_audits
from .url_page_importer import DEFAULT_RENDERED_MAX_PAGES, ImportCancelled, UrlPageImporter, normalize_url

RUNS_DIR = os.environ.get("OPEN_INGRESS_DATA_DIR") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "uploads",
    "runs",
)

CRAWL_ACTIVITY_VERBS = [
    "Discombobulating",
    "Fuzzing",
    "Brewing",
    "Humming",
    "Inspecting",
    "Mapping",
    "Tracing",
    "Scanning",
    "Peeking",
    "Probing",
    "Untangling",
    "Sifting",
    "Sniffing",
    "Poking",
    "Sampling",
    "Parsing",
    "Indexing",
    "Following",
    "Reading",
    "Cataloging",
    "Sketching",
    "Warming",
    "Stirring",
    "Simmering",
    "Distilling",
    "Weaving",
    "Threading",
    "Listening",
    "Tuning",
    "Assembling",
]

RECOVERY_ANALYSIS_PAGE_LIMIT = 12
RECOVERY_ANALYSIS_HTML_CHAR_LIMIT = 150_000


class RunCancelled(Exception):
    """Raised when a user cancels an in-flight crawl or exploration."""


class ReadinessManager:
    def __init__(self, base_dir: str = RUNS_DIR) -> None:
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)

    def _run_state_path(self, run_id: str) -> str:
        return os.path.join(self._run_dir(run_id), "state.json")

    def _touch_progress(
        self,
        run_id: str,
        *,
        message: str,
        pct: int | None = None,
        phase: str | None = None,
        log_line: str | None = None,
    ) -> None:
        path = self._run_state_path(run_id)
        state = self._read_json(path)
        state["progress"] = message
        if pct is not None:
            state["progress_pct"] = max(0, min(100, int(pct)))
        if phase is not None:
            state["job_phase"] = phase
        state["updated_at"] = datetime.utcnow().isoformat() + "Z"
        if log_line:
            log = list(state.get("activity_log") or [])
            log.append(log_line)
            state["activity_log"] = log[-25:]
        self._write_json(self._run_dir(run_id), "state.json", state)

    def _is_cancelled(self, run_id: str) -> bool:
        state = self._read_json(self._run_state_path(run_id))
        return bool(state.get("cancel_requested"))

    def _check_cancelled(self, run_id: str) -> None:
        if self._is_cancelled(run_id):
            raise RunCancelled("Audit cancelled")

    def _queued_mode(self) -> bool:
        return Config.JOB_EXECUTION_MODE == "queued"

    def _sync_run_metadata(self, state: Dict[str, Any]) -> None:
        user_id = str(state.get("user_id") or "")
        if not user_id or user_id == "dev":
            return
        from .supabase_client import upsert_run_metadata

        upsert_run_metadata(
            str(state.get("run_id") or ""),
            user_id,
            status=str(state.get("status") or RunStatus.DRAFT.value),
            title=str(state.get("title") or ""),
            site_url=str(state.get("site_url") or ""),
            completed_at=str(state.get("completed_at") or ""),
            json_blob={
                "commerce_inputs": self._clean_commerce_inputs(state.get("commerce_inputs")),
            },
        )

    def _pending_credit_authorizations(self, user_id: str, *, exclude_run_id: str = "") -> int:
        if not user_id or user_id == "dev":
            return 0
        pending = 0
        if not os.path.isdir(self.base_dir):
            return pending
        for name in os.listdir(self.base_dir):
            if not name.startswith("run_") or name == exclude_run_id:
                continue
            state_path = os.path.join(self.base_dir, name, "state.json")
            if not os.path.isfile(state_path):
                continue
            try:
                state = self._read_json(state_path)
            except Exception:
                continue
            if str(state.get("user_id") or "") != user_id:
                continue
            if not state.get("credit_authorized") or state.get("credit_consumed"):
                continue
            if str(state.get("status") or "") == RunStatus.COMPLETED.value:
                continue
            pending += 1
        return pending

    def _authorize_credit_if_needed(self, run_id: str, state: Dict[str, Any]) -> Dict[str, Any]:
        state["credit_authorized"] = True
        return state

    def _consume_credit_on_completion(self, run_id: str) -> None:
        state_path = self._run_state_path(run_id)
        state = self._read_json(state_path)
        if state.get("credit_consumed") or not state.get("credit_authorized"):
            return
        state["credit_consumed"] = True
        self._write_json(self._run_dir(run_id), "state.json", state)

    def _enqueue_run_job(
        self,
        run_id: str,
        *,
        job_type: str,
        phase: str | None = None,
        url: str | None = None,
        progress: str,
        job_phase: str | None = None,
    ) -> Dict[str, Any]:
        run_dir = self._run_dir(run_id)
        state = self._read_json(os.path.join(run_dir, "state.json"))
        if state.get("status") in {RunStatus.RUNNING.value, RunStatus.QUEUED.value}:
            return {"state": state, "started": False, "message": "Run already in progress."}

        payload = build_job_message(
            run_id=run_id,
            user_id=state.get("user_id"),
            job_type=job_type,
            phase=phase,
            url=url,
        )
        now = datetime.utcnow().isoformat() + "Z"
        state["status"] = RunStatus.QUEUED.value
        state["job_phase"] = job_phase
        state["progress"] = progress
        state["progress_pct"] = int(state.get("progress_pct") or 0)
        state["active_job_id"] = payload.get("job_id")
        state["active_job_type"] = payload.get("job_type")
        state["queued_at"] = now
        state["updated_at"] = now
        state.pop("error", None)
        state.pop("cancel_requested", None)
        self._write_json(run_dir, "state.json", state)
        self._sync_run_metadata(state)

        try:
            enqueue_job(payload)
        except Exception:
            state = self._read_json(os.path.join(run_dir, "state.json"))
            state["status"] = RunStatus.FAILED.value
            state["job_phase"] = None
            state["error"] = "Queueing failed"
            state["progress"] = "Queueing failed"
            state["progress_pct"] = 0
            state["updated_at"] = datetime.utcnow().isoformat() + "Z"
            self._write_json(run_dir, "state.json", state)
            self._sync_run_metadata(state)
            raise

        return {"state": state, "started": True, "queued": True, "job": payload}

    def cancel_run(self, run_id: str, user_id: str | None = None) -> Dict[str, Any]:
        if user_id:
            self.assert_run_access(run_id, user_id)
        run_dir = self._run_dir(run_id)
        state = self._read_json(os.path.join(run_dir, "state.json"))
        now = datetime.utcnow().isoformat() + "Z"
        state["cancel_requested"] = True
        state["status"] = RunStatus.FAILED.value
        state["job_phase"] = None
        state["error"] = "Cancelled by user"
        state["progress"] = "Cancelled"
        state["progress_pct"] = 0
        state["cancelled_at"] = now
        state["updated_at"] = now
        log = list(state.get("activity_log") or [])
        log.append("Cancel requested by user")
        state["activity_log"] = log[-25:]
        self._write_json(run_dir, "state.json", state)
        if user_id and user_id != "dev":
            self._sync_run_metadata(state)
        return state

    def _is_teaser_run(self, state: Dict[str, Any]) -> bool:
        return str(state.get("run_mode") or "") == "teaser"

    def _teaser_locked(self, state: Dict[str, Any]) -> bool:
        return self._is_teaser_run(state) and not bool(state.get("full_audit_unlocked"))

    def user_teaser_available(self, user_id: str | None) -> bool:
        if not user_id or user_id == "dev":
            return True
        from .supabase_client import has_used_teaser

        return not has_used_teaser(user_id, runs_dir=self.base_dir)

    def create_run(
        self,
        payload: Dict[str, Any],
        user_id: str | None = None,
        user_email: str | None = None,
    ) -> Dict[str, Any]:
        from ..config import Config

        if not Config.llm_available():
            raise ValueError(
                "LLM_API_KEY is required. Set it in backend/.env before creating a run."
            )
        payload = dict(payload or {})
        for key in ("siteUrl", "beforeUrl", "afterUrl"):
            raw = str(payload.get(key) or "").strip()
            if raw:
                payload[key] = normalize_url(raw)
        run_mode = str(payload.get("run_mode") or "audit")
        if run_mode == "teaser":
            # Homepage demo: repeat as often as needed; only API response is limited until paid.
            payload["max_pages"] = DEFAULT_RENDERED_MAX_PAGES
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        run_dir = os.path.join(self.base_dir, run_id)
        os.makedirs(run_dir, exist_ok=True)
        site_url = str(payload.get("siteUrl") or payload.get("beforeUrl") or "").strip()
        state = {
            "run_id": run_id,
            "user_id": user_id,
            "status": RunStatus.DRAFT.value,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "title": str(payload.get("title") or "OpenIngress run"),
            "compare_before_after": bool(payload.get("compare_before_after", False)),
            "run_mode": run_mode,
            "full_audit_unlocked": False,
            "device": str(payload.get("device") or "desktop"),
            "operators_per_task": int(payload.get("operators_per_task") or 3),
            "max_pages": int(payload.get("max_pages") or DEFAULT_RENDERED_MAX_PAGES),
            "use_llm_explorer": True,
            "auto_explore_after_import": bool(payload.get("auto_explore_after_import")),
            "linked_codex_run_id": str(payload.get("linked_codex_run_id") or ""),
            "tasks": payload.get("tasks") or [],
            "commerce_inputs": dict(payload.get("commerce_inputs") or {}),
            "site_url": site_url,
            "job_name": str(payload.get("title") or "OpenIngress run"),
            "credit_authorized": False,
            "credit_consumed": False,
            "requester_email": user_email or "",
        }
        self._write_json(run_dir, "state.json", state)
        self._write_json(run_dir, "draft.json", payload)
        if user_id and user_id != "dev":
            from .supabase_client import ensure_profile, upsert_run_metadata

            ensure_profile(user_id, user_email or "")
            self._sync_run_metadata(state)
        return state

    def list_runs(self, user_id: str | None = None) -> List[Dict[str, Any]]:
        rows = []
        if not os.path.isdir(self.base_dir):
            return rows
        allowed: set[str] | None = None
        if user_id and user_id != "dev":
            from .supabase_client import list_run_ids_for_user

            allowed = list_run_ids_for_user(user_id)
        for name in sorted(os.listdir(self.base_dir), reverse=True):
            path = os.path.join(self.base_dir, name, "state.json")
            if not os.path.isfile(path):
                continue
            state = self._read_json(path)
            if not self._run_visible_to_user(state, user_id, allowed):
                continue
            rows.append(state)
        return rows

    @staticmethod
    def _run_visible_to_user(
        state: Dict[str, Any],
        user_id: str | None,
        allowed: set[str] | None,
    ) -> bool:
        if not user_id or user_id == "dev":
            return True
        owner = state.get("user_id")
        run_id = str(state.get("run_id") or "")
        if owner == user_id:
            return True
        if allowed is None:
            return False
        return run_id in allowed

    def assert_run_access(self, run_id: str, user_id: str | None) -> None:
        if not user_id or user_id == "dev":
            return
        run_dir = self._run_dir(run_id)
        state = self._read_json(os.path.join(run_dir, "state.json"))
        owner = state.get("user_id")
        if owner and owner != user_id:
            raise PermissionError("You do not have access to this audit.")
        from .supabase_client import run_owned_by_user

        if owner and not run_owned_by_user(run_id, user_id, local_owner_id=owner):
            raise PermissionError("You do not have access to this audit.")

    def get_navigation(self, run_id: str) -> Dict[str, Any]:
        run_dir = self._run_dir(run_id)
        variants = []
        for phase in (SnapshotPhase.BEFORE.value, SnapshotPhase.AFTER.value):
            path = os.path.join(run_dir, f"nav_{phase}.json")
            if os.path.isfile(path):
                payload = self._read_json(path)
                variants.extend(payload.get("variants") or [])
        return {"variants": variants}

    def get_teaser_check(self, run_id: str) -> Dict[str, Any]:
        run_dir = self._run_dir(run_id)
        state = self._read_json(os.path.join(run_dir, "state.json"))
        if not self._is_teaser_run(state):
            raise ValueError("This run is not a free site check.")
        audit_path = os.path.join(run_dir, "audit.json")
        audit = self._read_json(audit_path) if os.path.isfile(audit_path) else {}
        snap_path = os.path.join(run_dir, "snapshot_before.json")
        snapshot = self._read_json(snap_path) if os.path.isfile(snap_path) else {}
        static_audits = snapshot.get("static_audits") or {}
        pages_crawled = len(snapshot.get("pages") or [])
        max_pages = int(state.get("max_pages") or DEFAULT_RENDERED_MAX_PAGES)
        crawl_modes = []
        for page in snapshot.get("pages") or []:
            mode = (page.get("metadata") or {}).get("import_mode")
            if mode and mode not in crawl_modes:
                crawl_modes.append(mode)
        crawl_import_mode = state.get("crawl_import_mode") or (
            crawl_modes[0] if len(crawl_modes) == 1 else "mixed"
        )
        if audit:
            refresh_audit_overall_score(audit, static_audits=static_audits, exploration=None)
            self._write_json(run_dir, "audit.json", audit)
            state["overall_score"] = audit.get("overall_score")
            state["agent_accessibility_score"] = audit.get("agent_accessibility_score")
            self._write_json(run_dir, "state.json", state)
        site_url = str(state.get("site_url") or "")
        host = ""
        if site_url:
            try:
                from urllib.parse import urlparse

                host = (urlparse(site_url).hostname or "").replace("www.", "")
            except Exception:
                host = site_url
        return {
            "run_id": run_id,
            "site_url": site_url,
            "host": host,
            "status": state.get("status"),
            "overall_score": audit.get("overall_score"),
            "agent_accessibility_score": audit.get("agent_accessibility_score"),
            "teaser_complete": bool(state.get("teaser_complete") or state.get("import_complete")),
            "full_audit_unlocked": bool(state.get("full_audit_unlocked")),
            "progress": state.get("progress"),
            "progress_pct": state.get("progress_pct"),
            "activity_log": list(state.get("activity_log") or [])[-25:],
            "pages_crawled": pages_crawled,
            "max_pages": max_pages,
            "run_mode": state.get("run_mode"),
            "crawl_import_mode": crawl_import_mode,
            "crawl_used_browser": crawl_import_mode == "rendered_browser"
            or (crawl_import_mode == "mixed" and "rendered_browser" in crawl_modes),
        }

    def get_run(self, run_id: str) -> Dict[str, Any]:
        run_dir = self._run_dir(run_id)
        state = self._recover_stale_run_if_needed(run_dir)
        if self._refresh_stale_navigation_artifacts(run_dir):
            state = self._read_json(os.path.join(run_dir, "state.json"))
        if self._teaser_locked(state):
            raise PermissionError(
                "Full report is not available for a free site check. Unlock a full audit first."
            )
        result = {"state": state}
        for name in ("draft.json", "events.jsonl"):
            path = os.path.join(run_dir, name)
            if os.path.isfile(path):
                if name.endswith(".jsonl"):
                    result["events"] = self._read_jsonl(path)
                else:
                    result[name.replace(".json", "")] = self._read_json(path)
        state = self._hydrate_commerce_inputs(run_dir, state, result.get("draft"))
        result["state"] = state
        audit_path = os.path.join(run_dir, "audit.json")
        if os.path.isfile(audit_path):
            result["audit"] = self._read_json(audit_path)
        report_path = os.path.join(run_dir, "agent_report.json")
        if os.path.isfile(report_path):
            result["agent_report"] = self._read_json(report_path)
        elif (result.get("audit") or {}).get("agent_report"):
            result["agent_report"] = (result.get("audit") or {}).get("agent_report")
        if "agent_report" not in result:
            result["agent_report"] = self._maybe_build_agent_report(run_dir)
        exploration_path = os.path.join(run_dir, "exploration.json")
        if os.path.isfile(exploration_path):
            result["exploration"] = self._read_json(exploration_path)
        if result.get("audit"):
            snapshot_summary = self._snapshot_summary_for_report(run_dir, result.get("agent_report"))
            if snapshot_summary:
                result["snapshot_before"] = snapshot_summary
            self._sync_overall_score(run_dir, result)
            prior_run = self._find_prior_run(run_id, state, result.get("agent_report"))
            result["exports"] = build_remediation_exports(
                run_id=run_id,
                run_payload=result,
                run_dir=None,
                prior_run=prior_run,
            )
            combined_report = self._maybe_build_combined_report(state, result)
            if combined_report:
                result["combined_report"] = combined_report
        return self._public_run_payload(result)

    def _hydrate_commerce_inputs(
        self,
        run_dir: str,
        state: Dict[str, Any],
        draft: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        run_id = str(state.get("run_id") or os.path.basename(run_dir))
        merged: Dict[str, Any] = {}
        for source in (
            self._commerce_inputs_from_supabase(run_id),
            self._commerce_inputs_from_linked_codex_state(state),
            self._clean_commerce_inputs((draft or {}).get("business_inputs")),
            self._clean_commerce_inputs((draft or {}).get("commerce_inputs")),
            self._clean_commerce_inputs(state.get("commerce_inputs")),
        ):
            merged.update(source)
        if not merged or merged == self._clean_commerce_inputs(state.get("commerce_inputs")):
            return state
        updated = dict(state)
        updated["commerce_inputs"] = merged
        self._write_json(run_dir, "state.json", updated)
        self._sync_run_metadata(updated)
        return updated

    def _commerce_inputs_from_linked_codex_state(self, state: Dict[str, Any]) -> Dict[str, Any]:
        linked_codex_run_id = str(state.get("linked_codex_run_id") or "")
        if not linked_codex_run_id:
            return {}
        path = os.path.join(self.base_dir, linked_codex_run_id, "codex_state.json")
        if not os.path.isfile(path):
            return {}
        try:
            linked_state = self._read_json(path)
        except Exception:
            return {}
        return self._clean_commerce_inputs(linked_state.get("commerce_inputs"))

    def _commerce_inputs_from_supabase(self, run_id: str) -> Dict[str, Any]:
        if not run_id:
            return {}
        try:
            from .supabase_client import run_commerce_inputs

            return self._clean_commerce_inputs(run_commerce_inputs(run_id))
        except Exception:
            return {}

    @staticmethod
    def _clean_commerce_inputs(value: Any) -> Dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        allowed = {
            "monthly_sessions",
            "monthlySessions",
            "average_order_value",
            "averageOrderValue",
            "aov",
            "conversion_rate",
            "conversionRate",
            "agent_traffic_share",
            "agentTrafficShare",
        }
        return {
            str(key): item
            for key, item in value.items()
            if str(key) in allowed and item is not None and item != ""
        }

    def _maybe_build_combined_report(self, state: Dict[str, Any], run_payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        linked_codex_run_id = str(state.get("linked_codex_run_id") or "")
        if not linked_codex_run_id:
            return None
        result_path = os.path.join(self.base_dir, linked_codex_run_id, "codex_result.json")
        if not os.path.isfile(result_path):
            return None
        try:
            return build_combined_audit_report(self._read_json(result_path), run_payload)
        except Exception:
            return None

    def _snapshot_summary_for_report(
        self, run_dir: str, agent_report: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        report_static = (agent_report or {}).get("static_audits")
        report_source_url = (agent_report or {}).get("source_url")
        summary: Dict[str, Any] = {}
        if report_static:
            summary["static_audits"] = report_static
        if report_source_url:
            summary["source_url"] = report_source_url

        snapshot_path = os.path.join(run_dir, "snapshot_before.json")
        if os.path.isfile(snapshot_path):
            snapshot = self._read_json(snapshot_path)
            if snapshot.get("source_url"):
                summary["source_url"] = snapshot.get("source_url")
            if snapshot.get("static_audits"):
                summary["static_audits"] = snapshot.get("static_audits")
            strategy = (
                (snapshot.get("navigation_graph") or {}).get("strategy")
                or snapshot.get("strategy")
            )
            if (
                (not strategy or "high_value_skipped_links" not in strategy)
                and snapshot.get("pages")
                and snapshot.get("navigation_graph")
            ):
                from .crawl_strategies.strategy import build_strategy_for_payload

                strategy = build_strategy_for_payload(
                    {
                        "state": {"site_url": summary.get("source_url") or report_source_url or ""},
                        "audit": {},
                        "snapshot_before": snapshot,
                    }
                )
            if strategy:
                summary["strategy"] = strategy
        return summary or None

    def _public_run_payload(self, result: Dict[str, Any]) -> Dict[str, Any]:
        state = result.get("state") or {}
        audit = result.get("audit") or {}
        agent_report = result.get("agent_report") or {}
        exports = result.get("exports") or {}

        payload: Dict[str, Any] = {
            "state": state,
            "events": self._public_events(result.get("events") or []),
        }
        if result.get("draft"):
            payload["draft"] = result["draft"]
        if audit:
            payload["audit"] = self._public_audit(audit)
        if agent_report:
            payload["agent_report"] = self._public_agent_report(agent_report)
        if exports:
            payload["exports"] = self._public_exports(exports)
        if result.get("combined_report"):
            payload["combined_report"] = result["combined_report"]
        return payload

    @staticmethod
    def _public_audit(audit: Dict[str, Any]) -> Dict[str, Any]:
        keys = (
            "overall_score",
            "readiness_score",
            "agent_accessibility_score",
            "agent_speed_score",
            "coverage",
            "page_type",
            "top_actions",
            "recommendations",
            "navigation_issues",
            "readiness",
        )
        return {key: audit.get(key) for key in keys if key in audit}

    @staticmethod
    def _public_agent_report(agent_report: Dict[str, Any]) -> Dict[str, Any]:
        keys = (
            "has_exploration",
            "efficiency",
            "fixes",
            "findings",
            "gaps",
            "summary",
            "gap_sections",
            "explore_jobs",
            "job_results",
        )
        return {key: agent_report.get(key) for key in keys if key in agent_report}

    @staticmethod
    def _public_exports(exports: Dict[str, Any]) -> Dict[str, Any]:
        keys = (
            "verdict",
            "business_summary",
            "user_journeys",
            "checks",
            "fixes",
            "cursor_prompt",
            "github_issue_md",
            "reaudit_diff",
            "skill_md",
            "llms_txt",
            "report_md",
            "skill_name",
        )
        return {key: exports.get(key) for key in keys if key in exports}

    @staticmethod
    def _public_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        public_events = []
        keys = (
            "session_id",
            "task_id",
            "snapshot_phase",
            "step",
            "action",
            "event_type",
            "element_name",
            "url",
            "reasoning_summary",
            "success",
        )
        for event in events:
            item = {key: event.get(key) for key in keys if key in event}
            metadata = event.get("metadata") or {}
            public_metadata = {}
            if metadata.get("screenshots"):
                public_metadata["screenshots"] = metadata.get("screenshots")
            if metadata.get("path"):
                public_metadata["path"] = metadata.get("path")
            if public_metadata:
                item["metadata"] = public_metadata
            public_events.append(item)
        return public_events

    def _sync_overall_score(self, run_dir: str, result: Dict[str, Any]) -> None:
        """Persist headline overall_score from crawl + static + explore metrics."""
        audit = result.get("audit")
        if not audit:
            return
        refresh_audit_overall_score(
            audit,
            static_audits=(result.get("snapshot_before") or {}).get("static_audits")
            or (result.get("agent_report") or {}).get("static_audits"),
            exploration=result.get("exploration"),
            agent_report=result.get("agent_report"),
        )
        self._write_json(run_dir, "audit.json", audit)
        state = self._read_json(os.path.join(run_dir, "state.json"))
        state["overall_score"] = audit.get("overall_score")
        self._write_json(run_dir, "state.json", state)
        result["state"] = state

    def _refresh_stale_navigation_artifacts(self, run_dir: str) -> bool:
        """Rebuild old reports that marked uncrawled same-origin links as dead targets."""
        snapshot_path = os.path.join(run_dir, "snapshot_before.json")
        if not os.path.isfile(snapshot_path):
            return False
        snapshot = self._read_json(snapshot_path)
        graph = snapshot.get("navigation_graph") or {}
        if not self._has_stale_internal_dead_targets(graph):
            return False

        pages = snapshot.get("pages") or []
        if not pages:
            return False

        navigation_graph = UrlPageImporter()._navigation_graph_for_pages(
            pages,
            str((graph.get("quality") or {}).get("extractor") or graph.get("extractor") or "rendered_browser"),
        )
        coverage = accessibility_from_graph(navigation_graph)
        snapshot["navigation_graph"] = navigation_graph
        self._write_json(run_dir, "snapshot_before.json", snapshot)
        self._write_json(run_dir, "coverage_before.json", coverage)
        self._write_json(
            run_dir,
            "nav_before.json",
            {"variants": [{"id": "before", "name": "Before fixes", "navigation_graph": navigation_graph}]},
        )

        source_url = str(snapshot.get("source_url") or "")
        universe = build_site_universe(
            source_url=source_url,
            pages=pages,
            navigation_graph=navigation_graph,
        )
        self._write_json(run_dir, "universe.json", universe)

        imported_payload = {
            "source_url": source_url,
            "final_url": source_url,
            "title": pages[0].get("title") if pages else "",
            "html": pages[0].get("html") if pages else "",
            "pages": pages,
            "navigation_graph": navigation_graph,
        }
        static_audits = snapshot.get("static_audits") or {}
        audit = SiteAuditAnalyzer().analyze(
            imported=imported_payload,
            navigation_graph=navigation_graph,
            coverage=coverage,
            static_audits=static_audits,
            phase=SnapshotPhase.BEFORE.value,
        ).to_dict()

        exploration = self._read_json_optional(run_dir, "exploration.json") or None
        readiness = compute_agent_readiness(coverage=coverage, universe=universe, exploration=exploration)
        audit["readiness"] = readiness
        audit["universe_totals"] = universe.get("totals") or {}

        agent_report = None
        if exploration:
            events_path = os.path.join(run_dir, "events.jsonl")
            events = self._read_jsonl(events_path) if os.path.isfile(events_path) else []
            agent_report = self._build_agent_report(run_dir, universe, exploration, audit, events)
            audit["agent_report"] = agent_report
            self._write_json(run_dir, "agent_report.json", agent_report)
            with open(os.path.join(run_dir, "report.md"), "w", encoding="utf-8") as handle:
                handle.write(build_agent_report_markdown(agent_report))

        refresh_audit_overall_score(
            audit,
            static_audits=static_audits,
            exploration=exploration,
            agent_report=agent_report,
        )
        self._write_json(run_dir, "audit_before.json", audit)
        self._write_json(run_dir, "audit.json", audit)

        state_path = os.path.join(run_dir, "state.json")
        state = self._read_json(state_path)
        state["agent_accessibility_score"] = audit.get("agent_accessibility_score")
        state["agent_speed_score"] = audit.get("agent_speed_score")
        state["overall_score"] = audit.get("overall_score")
        state["readiness_score"] = readiness.get("readiness_score")
        if source_url:
            state["site_url"] = source_url
        if agent_report:
            eff = agent_report.get("efficiency") or {}
            state["actions_lost_percent"] = eff.get("actions_lost_percent")
            state["time_lost_percent"] = eff.get("time_lost_percent")
            state["gap_count"] = eff.get("gap_count")
        self._write_json(run_dir, "state.json", state)
        return True

    @staticmethod
    def _has_stale_internal_dead_targets(graph: Dict[str, Any]) -> bool:
        for action in graph.get("actions") or []:
            if str(action.get("target_kind") or "") != "dead_target":
                continue
            target = str(action.get("raw_target") or action.get("target_path") or "")
            if target.startswith("/") and not target.startswith("//"):
                return True
        return False

    def _recover_stale_run_if_needed(self, run_dir: str) -> Dict[str, Any]:
        state = self._read_json(os.path.join(run_dir, "state.json"))
        can_recover_failed_artifacts = (
            state.get("status") == RunStatus.FAILED.value
            and str(state.get("recovery_reason") or "") == "missing_artifacts"
            and os.path.isfile(os.path.join(run_dir, "snapshot_before.json"))
        )
        if state.get("status") not in {RunStatus.RUNNING.value, RunStatus.QUEUED.value} and not can_recover_failed_artifacts:
            return state
        stale_seconds = int(getattr(Config, "QUEUED_RUN_STALE_SECONDS", 900) or 0)
        if stale_seconds <= 0:
            return state
        last_update = self._parse_state_time(
            state.get("updated_at")
            or state.get("job_heartbeat_at")
            or state.get("started_at")
            or state.get("queued_at")
            or state.get("created_at")
        )
        if not last_update:
            return state
        age = (datetime.now(timezone.utc) - last_update).total_seconds()
        if age < stale_seconds and not can_recover_failed_artifacts:
            return state

        recovered = dict(state)
        now = datetime.utcnow().isoformat() + "Z"
        report = self._read_json_optional(run_dir, "agent_report.json") or {}
        audit_exists = os.path.isfile(os.path.join(run_dir, "audit.json"))
        snapshot_exists = os.path.isfile(os.path.join(run_dir, "snapshot_before.json"))
        if snapshot_exists and not audit_exists:
            try:
                self._rebuild_audit_from_snapshot(run_dir, SnapshotPhase.BEFORE.value)
                audit_exists = os.path.isfile(os.path.join(run_dir, "audit.json"))
            except Exception:
                audit_exists = False
        if report:
            recovered["status"] = RunStatus.COMPLETED.value
            recovered["job_phase"] = None
            recovered["progress_pct"] = 100
            recovered["progress"] = (
                "Agent exploration complete"
                if report.get("has_exploration")
                else "Agent exploration incomplete"
            )
            recovered["completed_at"] = recovered.get("completed_at") or now
            recovered.pop("error", None)
            recovery_reason = "agent_report_present"
        elif snapshot_exists and audit_exists:
            snapshot_data = self._read_json_optional(run_dir, "snapshot_before.json") or {}
            recovered["status"] = RunStatus.DRAFT.value
            recovered["job_phase"] = None
            recovered["progress_pct"] = max(int(recovered.get("progress_pct") or 0), 50)
            recovered["progress"] = "Crawl complete"
            recovered["import_complete"] = True
            recovered["pages_crawled"] = len(snapshot_data.get("pages") or []) or recovered.get("pages_crawled")
            recovered["site_url"] = snapshot_data.get("source_url") or recovered.get("site_url")
            recovered.pop("error", None)
            recovery_reason = "crawl_artifacts_present"
        else:
            recovered["status"] = RunStatus.FAILED.value
            recovered["job_phase"] = None
            recovered["progress_pct"] = 0
            recovered["progress"] = "Job interrupted"
            recovered["error"] = "Worker stopped before producing report artifacts"
            recovery_reason = "missing_artifacts"
        recovered["recovered_at"] = now
        recovered["recovery_reason"] = recovery_reason
        recovered["updated_at"] = now
        self._write_json(run_dir, "state.json", recovered)
        if recovered.get("status") == RunStatus.COMPLETED.value:
            self._consume_credit_on_completion(str(recovered.get("run_id") or ""))
            recovered = self._read_json(os.path.join(run_dir, "state.json"))
        self._sync_run_metadata(recovered)
        return recovered

    def _rebuild_audit_from_snapshot(self, run_dir: str, phase: str) -> None:
        snapshot_data = self._read_json(os.path.join(run_dir, f"snapshot_{phase}.json"))
        pages = []
        for index, page in enumerate(snapshot_data.get("pages") or []):
            if index >= RECOVERY_ANALYSIS_PAGE_LIMIT:
                break
            pages.append(
                FlowPage(
                    id=str(page.get("id") or f"page_{index + 1}"),
                    path=str(page.get("path") or "/"),
                    html=str(page.get("html") or "")[:RECOVERY_ANALYSIS_HTML_CHAR_LIMIT],
                    title=str(page.get("title") or ""),
                    is_start=bool(page.get("is_start")),
                    is_conversion=bool(page.get("is_conversion")),
                    metadata=dict(page.get("metadata") or {}),
                )
            )
        if not pages:
            raise ValueError("Snapshot has no pages to rebuild audit.")
        source_url = str(snapshot_data.get("source_url") or "")
        navigation_graph = snapshot_data.get("navigation_graph") or {}
        static_audits = snapshot_data.get("static_audits") or run_static_audits(source_url, pages[0].html)
        coverage_path = os.path.join(run_dir, f"coverage_{phase}.json")
        coverage = self._read_json(coverage_path) if os.path.isfile(coverage_path) else accessibility_from_graph(navigation_graph)
        self._write_json(run_dir, f"coverage_{phase}.json", coverage)
        self._write_json(run_dir, f"nav_{phase}.json", {"variants": [{"id": phase, "name": snapshot_data.get("label") or phase, "navigation_graph": navigation_graph}]})
        imported_payload = {
            "source_url": source_url,
            "final_url": source_url,
            "title": pages[0].title,
            "html": pages[0].html,
            "pages": [page.to_dict() for page in pages],
            "navigation_graph": navigation_graph,
        }
        audit = SiteAuditAnalyzer().analyze(
            imported=imported_payload,
            navigation_graph=navigation_graph,
            coverage=coverage,
            static_audits=static_audits,
            phase=phase,
        )
        audit_dict = audit.to_dict()
        universe = build_site_universe(
            source_url=source_url,
            pages=[page.to_dict() for page in pages],
            navigation_graph=navigation_graph,
        )
        self._write_json(run_dir, "universe.json", universe)
        readiness = compute_agent_readiness(
            coverage=coverage,
            universe=universe,
            exploration=self._read_json_optional(run_dir, "exploration.json"),
        )
        audit_dict["readiness"] = readiness
        audit_dict["universe_totals"] = universe.get("totals") or {}
        self._write_json(run_dir, f"audit_{phase}.json", audit_dict)
        if phase == SnapshotPhase.BEFORE.value:
            refresh_audit_overall_score(audit_dict, static_audits=static_audits, exploration=None)
            self._write_json(run_dir, "audit.json", audit_dict)

    @staticmethod
    def _parse_state_time(value: Any) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _find_prior_run(
        self,
        run_id: str,
        state: Dict[str, Any],
        agent_report: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        site_url = normalize_url(str(state.get("site_url") or ""))
        user_id = state.get("user_id")
        current_created = str(state.get("created_at") or "")
        if not site_url or not current_created:
            return None

        best: Optional[Dict[str, Any]] = None
        best_created = ""
        for name in os.listdir(self.base_dir):
            if name == run_id or not name.startswith("run_"):
                continue
            other_dir = os.path.join(self.base_dir, name)
            state_path = os.path.join(other_dir, "state.json")
            if not os.path.isfile(state_path):
                continue
            other_state = self._read_json(state_path)
            other_url = str(other_state.get("site_url") or "").strip()
            if not other_url:
                continue
            try:
                if normalize_url(other_url) != site_url:
                    continue
            except ValueError:
                continue
            if user_id and other_state.get("user_id") not in (user_id, None):
                continue
            created = str(other_state.get("created_at") or "")
            if not created or created >= current_created:
                continue
            if created <= best_created:
                continue

            prior_score = None
            prior_gaps = 0
            audit_path = os.path.join(other_dir, "audit.json")
            if os.path.isfile(audit_path):
                audit = self._read_json(audit_path)
                prior_score = audit.get("overall_score") or audit.get("readiness_score")
            report_path = os.path.join(other_dir, "agent_report.json")
            if os.path.isfile(report_path):
                report = self._read_json(report_path)
                prior_gaps = int((report.get("efficiency") or {}).get("gap_count") or len(report.get("gaps") or []))
                if prior_score is None:
                    pass
            elif other_state.get("overall_score") is not None:
                prior_score = other_state.get("overall_score")

            best_created = created
            best = {
                "run_id": name,
                "created_at": created,
                "overall_score": prior_score,
                "gap_count": prior_gaps,
            }
        return best

    def explore_run(self, run_id: str) -> Dict[str, Any]:
        from ..config import Config

        if not Config.llm_available():
            raise ValueError(
                "LLM_API_KEY is required. Set it in backend/.env before running exploration."
            )
        if self._queued_mode():
            return self._enqueue_run_job(
                run_id,
                job_type="explore",
                progress="Queued agent exploration...",
                job_phase="explore",
            )
        run_dir = self._run_dir(run_id)
        state = self._read_json(os.path.join(run_dir, "state.json"))
        if self._is_teaser_run(state) and not state.get("credit_consumed"):
            state = self._authorize_credit_if_needed(run_id, state)
            state["full_audit_unlocked"] = True
            self._write_json(run_dir, "state.json", state)
            self._sync_run_metadata(state)
        if state.get("status") == RunStatus.RUNNING.value:
            return {"state": state, "started": False, "message": "Run already in progress."}
        state["status"] = RunStatus.RUNNING.value
        state["job_phase"] = "explore"
        state["progress_pct"] = 55
        state["progress"] = "Starting agent exploration…"
        state["started_at"] = state.get("started_at") or datetime.utcnow().isoformat() + "Z"
        state.pop("error", None)
        state.pop("cancel_requested", None)
        log = list(state.get("activity_log") or [])
        log.append("Agent exploration started")
        state["activity_log"] = log[-25:]
        self._write_json(run_dir, "state.json", state)
        self._sync_run_metadata(state)
        thread = threading.Thread(target=self._explore_run_worker, args=(run_id,), daemon=True)
        thread.start()
        return {"state": state, "started": True}

    def _explore_run_worker(self, run_id: str) -> None:
        run_dir = self._run_dir(run_id)
        max_total_steps = 40

        def on_progress(message: str, step: int) -> None:
            pct = 55 + int((step / max(max_total_steps, 1)) * 40)
            self._touch_progress(run_id, message=message, pct=pct, phase="explore", log_line=message)

        def should_cancel() -> bool:
            return self._is_cancelled(run_id)

        try:
            self._check_cancelled(run_id)
            for stale in ("exploration.json", "agent_report.json", "events.jsonl"):
                stale_path = os.path.join(run_dir, stale)
                if os.path.isfile(stale_path):
                    os.remove(stale_path)
            snapshot_path = os.path.join(run_dir, "snapshot_before.json")
            if not os.path.isfile(snapshot_path):
                raise FileNotFoundError("Run an audit import before agent exploration.")
            snapshot_data = self._read_json(snapshot_path)
            snapshot = SiteSnapshot(
                phase=snapshot_data.get("phase") or SnapshotPhase.BEFORE.value,
                label=snapshot_data.get("label") or "site",
                source_url=snapshot_data.get("source_url") or "",
                pages=[FlowPage(**page) for page in snapshot_data.get("pages") or []],
                navigation_graph=snapshot_data.get("navigation_graph") or {},
                static_audits=snapshot_data.get("static_audits") or {},
            )
            universe = self._read_json(os.path.join(run_dir, "universe.json"))
            state = self._read_json(os.path.join(run_dir, "state.json"))
            draft = self._read_json(os.path.join(run_dir, "draft.json")) if os.path.isfile(
                os.path.join(run_dir, "draft.json")
            ) else {}
            audit_path = os.path.join(run_dir, "audit.json")
            audit = self._read_json(audit_path) if os.path.isfile(audit_path) else {}
            exploration = explore_like_cursor_agent(
                run_id=run_id,
                snapshot=snapshot,
                universe=universe,
                run_dir=run_dir,
                max_pages=min(30, int(state.get("max_pages") or 30)),
                device=state.get("device") or "desktop",
                use_llm=draft.get("use_llm_explorer", state.get("use_llm_explorer", True)),
                audit=audit,
                on_progress=on_progress,
                should_cancel=should_cancel,
            )
            self._write_json(run_dir, "exploration.json", exploration)
            events = exploration.pop("events", [])
            if events:
                self._write_jsonl(run_dir, "events.jsonl", events)

            coverage_path = os.path.join(run_dir, "coverage_before.json")
            coverage = self._read_json(coverage_path) if os.path.isfile(coverage_path) else {}
            readiness = compute_agent_readiness(
                coverage=coverage,
                universe=universe,
                exploration=exploration,
            )
            audit_path = os.path.join(run_dir, "audit.json")
            audit = self._read_json(audit_path) if os.path.isfile(audit_path) else {}
            agent_report: Dict[str, Any] = {}
            if audit:
                audit["readiness"] = readiness
                audit["exploration_summary"] = {
                    "mode": exploration.get("mode"),
                    "llm_enabled": exploration.get("llm_enabled"),
                    "policy_counts": exploration.get("policy_counts"),
                    "aria_match_percent": round(float(exploration.get("aria_match_rate") or 0) * 100, 2),
                    "activation_percent": round(float(exploration.get("activation_rate") or 0) * 100, 2),
                    "pages_visited": exploration.get("pages_visited"),
                    "total_steps": exploration.get("total_steps"),
                    "crawler_quality": exploration.get("crawler_quality") or {},
                }
                agent_report = self._build_agent_report(run_dir, universe, exploration, audit, events)
                audit["agent_report"] = agent_report
                static_audits = (snapshot.static_audits if snapshot else None) or agent_report.get(
                    "static_audits"
                )
                refresh_audit_overall_score(
                    audit,
                    static_audits=static_audits,
                    exploration=exploration,
                    agent_report=agent_report,
                )
                self._write_json(run_dir, "agent_report.json", agent_report)
                with open(os.path.join(run_dir, "report.md"), "w", encoding="utf-8") as handle:
                    handle.write(build_agent_report_markdown(agent_report))
                self._write_json(run_dir, "audit.json", audit)

            state = self._read_json(os.path.join(run_dir, "state.json"))
            state["status"] = RunStatus.COMPLETED.value
            state["job_phase"] = None
            state["progress_pct"] = 100
            state["progress"] = "Agent exploration complete"
            now = datetime.utcnow().isoformat() + "Z"
            state["completed_at"] = now
            state["updated_at"] = now
            state["readiness_score"] = readiness.get("readiness_score")
            if audit:
                state["overall_score"] = audit.get("overall_score")
            if agent_report:
                eff = agent_report.get("efficiency") or {}
                state["actions_lost_percent"] = eff.get("actions_lost_percent")
                state["time_lost_percent"] = eff.get("time_lost_percent")
                state["gap_count"] = eff.get("gap_count")
            state.pop("error", None)
            self._write_json(run_dir, "state.json", state)
            self._consume_credit_on_completion(run_id)
            final_state = self._read_json(os.path.join(run_dir, "state.json"))
            self._sync_run_metadata(final_state)
            if final_state.get("linked_codex_run_id"):
                self._send_completion_notification_when_ready(run_dir)
        except RunCancelled:
            state = self._read_json(os.path.join(run_dir, "state.json"))
            state["status"] = RunStatus.FAILED.value
            state["job_phase"] = None
            state["error"] = "Cancelled by user"
            state["progress"] = "Cancelled"
            state["progress_pct"] = 0
            self._write_json(run_dir, "state.json", state)
            self._sync_run_metadata(state)
        except Exception as exc:
            if str(exc) == "CANCELLED":
                state = self._read_json(os.path.join(run_dir, "state.json"))
                state["status"] = RunStatus.FAILED.value
                state["job_phase"] = None
                state["error"] = "Cancelled by user"
                state["progress"] = "Cancelled"
                state["progress_pct"] = 0
                self._write_json(run_dir, "state.json", state)
                self._sync_run_metadata(state)
                return
            state = self._read_json(os.path.join(run_dir, "state.json"))
            state["status"] = RunStatus.FAILED.value
            state["job_phase"] = None
            state["error"] = str(exc)
            state["progress"] = "Exploration failed"
            state["progress_pct"] = 0
            self._write_json(run_dir, "state.json", state)
            self._sync_run_metadata(state)

    def _write_partial_crawl_snapshot(
        self,
        *,
        run_dir: str,
        run_id: str,
        phase: str,
        source_url: str,
        imported_pages: List[Dict[str, Any]],
        navigation_graph: Dict[str, Any],
        warnings: List[str],
    ) -> None:
        if not imported_pages:
            return
        pages = [
            FlowPage(
                id=str(page.get("id") or f"page_{index + 1}"),
                path=str(page.get("path") or "/"),
                html=str(page.get("html") or ""),
                title=str(page.get("title") or ""),
                is_start=bool(page.get("is_start")),
                is_conversion=bool(page.get("is_conversion")),
                metadata=dict(page.get("metadata") or {}),
            )
            for index, page in enumerate(imported_pages)
        ]
        final_url = str((pages[0].metadata or {}).get("final_url") or source_url)
        existing_snapshot = self._read_json_optional(run_dir, f"snapshot_{phase}.json") or {}
        audits = existing_snapshot.get("static_audits") or run_static_audits(source_url, pages[0].html)
        snapshot = SiteSnapshot(
            phase=phase,
            label="Before fixes" if phase == SnapshotPhase.BEFORE.value else "After fixes",
            source_url=final_url,
            pages=pages,
            navigation_graph=navigation_graph,
            static_audits=audits,
        )
        self._write_json(run_dir, f"snapshot_{phase}.json", snapshot.to_dict())
        coverage = accessibility_from_graph(navigation_graph)
        self._write_json(run_dir, f"coverage_{phase}.json", coverage)
        self._write_json(
            run_dir,
            f"nav_{phase}.json",
            {"variants": [{"id": phase, "name": snapshot.label, "navigation_graph": navigation_graph}]},
        )
        state = self._read_json(os.path.join(run_dir, "state.json"))
        state["partial_crawl_available"] = True
        state["partial_crawl_page_count"] = len(pages)
        state["partial_crawl_warnings"] = list(warnings or [])[-5:]
        state["pages_crawled"] = len(pages)
        state["site_url"] = final_url
        state["crawl_import_mode"] = "rendered_browser"
        state["updated_at"] = datetime.utcnow().isoformat() + "Z"
        self._write_json(run_dir, "state.json", state)

    def start_import_snapshot(
        self, run_id: str, phase: str, url: str, user_id: str | None = None
    ) -> Dict[str, Any]:
        if self._queued_mode():
            if user_id:
                self.assert_run_access(run_id, user_id)
            return self._enqueue_run_job(
                run_id,
                job_type="import_snapshot",
                phase=phase,
                url=url,
                progress="Queued site crawl...",
                job_phase="crawl",
            )
        run_dir = self._run_dir(run_id)
        state = self._read_json(os.path.join(run_dir, "state.json"))
        if state.get("status") == RunStatus.RUNNING.value:
            return {"state": state, "started": False, "message": "Run already in progress."}
        state["status"] = RunStatus.RUNNING.value
        state["job_phase"] = "crawl"
        state["progress_pct"] = 5
        state["progress"] = "Starting site crawl…"
        state["started_at"] = datetime.utcnow().isoformat() + "Z"
        state.pop("error", None)
        state.pop("cancel_requested", None)
        state.pop("import_complete", None)
        state["activity_log"] = ["Crawl started"]
        self._write_json(run_dir, "state.json", state)
        self._sync_run_metadata(state)
        thread = threading.Thread(
            target=self._import_snapshot_worker,
            args=(run_id, phase, url, user_id),
            daemon=True,
        )
        thread.start()
        return {"state": state, "started": True}

    def _import_snapshot_worker(
        self, run_id: str, phase: str, url: str, user_id: str | None = None
    ) -> None:
        try:
            self._import_snapshot_impl(run_id, phase, url, user_id=user_id)
        except (RunCancelled, ImportCancelled):
            run_dir = self._run_dir(run_id)
            state = self._read_json(os.path.join(run_dir, "state.json"))
            state["status"] = RunStatus.FAILED.value
            state["job_phase"] = None
            state["error"] = "Cancelled by user"
            state["progress"] = "Cancelled"
            state["progress_pct"] = 0
            self._write_json(run_dir, "state.json", state)
            self._sync_run_metadata(state)
        except Exception as exc:
            run_dir = self._run_dir(run_id)
            state = self._read_json(os.path.join(run_dir, "state.json"))
            state["status"] = RunStatus.FAILED.value
            state["job_phase"] = None
            state["error"] = str(exc)
            state["progress"] = "Import failed"
            state["progress_pct"] = 0
            self._write_json(run_dir, "state.json", state)
            self._sync_run_metadata(state)

    def import_snapshot(self, run_id: str, phase: str, url: str, user_id: str | None = None) -> Dict[str, Any]:
        return self.start_import_snapshot(run_id, phase, url, user_id=user_id)

    def _import_snapshot_impl(
        self, run_id: str, phase: str, url: str, user_id: str | None = None
    ) -> Dict[str, Any]:
        phase = phase if phase in {SnapshotPhase.BEFORE.value, SnapshotPhase.AFTER.value} else SnapshotPhase.BEFORE.value
        run_dir = self._run_dir(run_id)
        state = self._read_json(os.path.join(run_dir, "state.json"))
        if user_id:
            self.assert_run_access(run_id, user_id)
        if (
            phase == SnapshotPhase.BEFORE.value
            and not state.get("credit_authorized")
            and not self._is_teaser_run(state)
        ):
            state = self._authorize_credit_if_needed(run_id, state)
            self._write_json(run_dir, "state.json", state)
            self._sync_run_metadata(state)
        draft = self._read_json(os.path.join(run_dir, "draft.json")) if os.path.isfile(
            os.path.join(run_dir, "draft.json")
        ) else {}
        device = state.get("device") or "desktop"
        device_mix = "mobile" if device == "mobile" else "desktop"
        source_url = normalize_url(url)
        max_pages = int(draft.get("max_pages") or state.get("max_pages") or DEFAULT_RENDERED_MAX_PAGES)

        def on_crawl_progress(done: int, total: int, current_url: str) -> None:
            pct = 5 + int((done / max(total, 1)) * 45)
            activity_verb = random.choice(CRAWL_ACTIVITY_VERBS)
            self._touch_progress(
                run_id,
                message=f"Crawling page {done}/{total}…",
                pct=pct,
                phase="crawl",
                log_line=f"{activity_verb} {current_url[:120]}",
            )

        def on_crawl_page(
            imported_pages: List[Dict[str, Any]],
            navigation_graph: Dict[str, Any],
            warnings: List[str],
        ) -> None:
            self._write_partial_crawl_snapshot(
                run_dir=run_dir,
                run_id=run_id,
                phase=phase,
                source_url=source_url,
                imported_pages=imported_pages,
                navigation_graph=navigation_graph,
                warnings=warnings,
            )

        imported = UrlPageImporter().import_page(
            url=source_url,
            render=True,
            device_mix=device_mix,
            max_pages=max_pages,
            on_progress=on_crawl_progress,
            on_page=on_crawl_page,
            should_cancel=lambda: self._is_cancelled(run_id),
            require_browser_crawl=True,
        )
        self._check_cancelled(run_id)
        pages = [
            FlowPage(
                id=str(page.get("id") or f"page_{index + 1}"),
                path=str(page.get("path") or "/"),
                html=str(page.get("html") or ""),
                title=str(page.get("title") or ""),
                is_start=bool(page.get("is_start")),
                is_conversion=bool(page.get("is_conversion")),
                metadata=dict(page.get("metadata") or {}),
            )
            for index, page in enumerate(imported.pages or [])
        ]
        navigation_graph = imported.navigation_graph or {}
        audits = run_static_audits(url, pages[0].html if pages else "")
        snapshot = SiteSnapshot(
            phase=phase,
            label="Before fixes" if phase == SnapshotPhase.BEFORE.value else "After fixes",
            source_url=imported.final_url or source_url,
            pages=pages,
            navigation_graph=navigation_graph,
            static_audits=audits,
        )
        self._write_json(run_dir, f"snapshot_{phase}.json", snapshot.to_dict())
        coverage = accessibility_from_graph(navigation_graph)
        self._write_json(run_dir, f"coverage_{phase}.json", coverage)
        nav_variant = {
            "id": phase,
            "name": snapshot.label,
            "navigation_graph": navigation_graph,
        }
        self._write_json(run_dir, f"nav_{phase}.json", {"variants": [nav_variant]})
        imported_payload = imported.to_dict()
        audit = SiteAuditAnalyzer().analyze(
            imported=imported_payload,
            navigation_graph=navigation_graph,
            coverage=coverage,
            static_audits=audits,
            phase=phase,
        )
        audit_dict = audit.to_dict()
        universe = build_site_universe(
            source_url=snapshot.source_url,
            pages=[page.to_dict() for page in pages],
            navigation_graph=navigation_graph,
        )
        self._write_json(run_dir, "universe.json", universe)
        exploration = self._read_json_optional(run_dir, "exploration.json")
        readiness = compute_agent_readiness(
            coverage=coverage,
            universe=universe,
            exploration=exploration,
        )
        audit_dict["readiness"] = readiness
        audit_dict["universe_totals"] = universe.get("totals") or {}
        self._write_json(run_dir, f"audit_{phase}.json", audit_dict)
        if phase == SnapshotPhase.BEFORE.value:
            refresh_audit_overall_score(
                audit_dict,
                static_audits=audits,
                exploration=None,
            )
            self._write_json(run_dir, "audit.json", audit_dict)
            state = self._read_json(os.path.join(run_dir, "state.json"))
            state["agent_accessibility_score"] = audit.agent_accessibility_score
            state["agent_speed_score"] = audit.agent_speed_score
            state["overall_score"] = audit_dict.get("overall_score", audit.overall_score)
            state["readiness_score"] = readiness.get("readiness_score")
            state["site_url"] = snapshot.source_url
            state["import_complete"] = True
            state["job_phase"] = None
            log = list(state.get("activity_log") or [])
            log.append(f"Crawl finished with {len(pages)} page(s)")
            state["activity_log"] = log[-25:]
            state["crawl_import_mode"] = str(imported.import_mode or "")
            state["pages_crawled"] = len(pages)
            if self._is_teaser_run(state):
                owner = user_id or state.get("user_id")
                from .supabase_client import has_used_teaser, mark_teaser_used

                if owner and not has_used_teaser(str(owner), runs_dir=self.base_dir):
                    mark_teaser_used(str(owner), run_id)
                state["status"] = RunStatus.COMPLETED.value
                state["progress_pct"] = 100
                state["progress"] = "Site check complete"
                state["teaser_complete"] = True
            else:
                state["status"] = RunStatus.DRAFT.value
                state["progress_pct"] = 50
                state["progress"] = f"Crawl complete — {len(pages)} page(s)"
            self._write_json(run_dir, "state.json", state)
            self._sync_run_metadata(state)
            if (
                phase == SnapshotPhase.BEFORE.value
                and bool(state.get("auto_explore_after_import"))
                and not self._is_teaser_run(state)
            ):
                state["status"] = RunStatus.RUNNING.value
                state["job_phase"] = "explore"
                state["progress_pct"] = max(int(state.get("progress_pct") or 50), 55)
                state["progress"] = "Starting agent exploration…"
                self._write_json(run_dir, "state.json", state)
                self._sync_run_metadata(state)
                self._explore_run_worker(run_id)
        return {
            "snapshot": snapshot.to_dict(),
            "coverage": coverage,
            "warnings": imported.warnings,
            "navigation": {"variants": [nav_variant]},
            "audit": audit_dict,
            "universe": universe,
            "readiness": readiness,
        }

    def execute_run(self, run_id: str) -> Dict[str, Any]:
        if self._queued_mode():
            return self._enqueue_run_job(
                run_id,
                job_type="execute",
                progress="Queued live operators...",
                job_phase="execute",
            )
        run_dir = self._run_dir(run_id)
        state = self._read_json(os.path.join(run_dir, "state.json"))
        if state.get("status") == RunStatus.RUNNING.value:
            return {"state": state, "started": False, "message": "Run already in progress."}
        state["status"] = RunStatus.RUNNING.value
        state["progress"] = "Queued live operators…"
        state.pop("error", None)
        self._write_json(run_dir, "state.json", state)
        self._sync_run_metadata(state)
        thread = threading.Thread(target=self._execute_run_worker, args=(run_id,), daemon=True)
        thread.start()
        return {"state": state, "started": True}

    def _execute_run_worker(self, run_id: str) -> None:
        run_dir = self._run_dir(run_id)
        try:
            state = self._read_json(os.path.join(run_dir, "state.json"))
            draft = self._read_json(os.path.join(run_dir, "draft.json"))
            state["progress"] = "Running live operators (this may take a few minutes)…"
            self._write_json(run_dir, "state.json", state)

            tasks = [self._task_from_dict(item) for item in draft.get("tasks") or state.get("tasks") or []]
            if not tasks:
                tasks = self._tasks_from_audit(run_dir)
            if not tasks:
                tasks = [
                    AgentTask(
                        id="task_1",
                        name="Accessibility and speed probe",
                        instruction="Navigate the site quickly and identify whether the main interactive actions are accessible.",
                        success_text="",
                    )
                ]

            all_events: List[Dict[str, Any]] = []
            coverage_by_phase: Dict[str, Any] = {}
            task_by_phase: Dict[str, Any] = {}

            for phase in (SnapshotPhase.BEFORE.value, SnapshotPhase.AFTER.value):
                snapshot_path = os.path.join(run_dir, f"snapshot_{phase}.json")
                if not os.path.isfile(snapshot_path):
                    if phase == SnapshotPhase.AFTER.value and draft.get("compare_before_after", False):
                        continue
                    if phase == SnapshotPhase.BEFORE.value:
                        raise FileNotFoundError("Import the BEFORE snapshot before running.")
                    continue
                state["progress"] = f"Live operators on “{phase}” snapshot…"
                self._write_json(run_dir, "state.json", state)

                snapshot_data = self._read_json(snapshot_path)
                snapshot = SiteSnapshot(
                    phase=phase,
                    label=snapshot_data.get("label") or phase,
                    source_url=snapshot_data.get("source_url") or "",
                    pages=[FlowPage(**page) for page in snapshot_data.get("pages") or []],
                    navigation_graph=snapshot_data.get("navigation_graph") or {},
                    static_audits=snapshot_data.get("static_audits") or {},
                )
                coverage_path = os.path.join(run_dir, f"coverage_{phase}.json")
                if os.path.isfile(coverage_path):
                    coverage_by_phase[phase] = self._read_json(coverage_path)
                else:
                    coverage_by_phase[phase] = accessibility_from_graph(snapshot.navigation_graph)

                runner = LiveOperatorRunner()
                phase_events = runner.run_tasks(
                    run_id=run_id,
                    snapshot=snapshot,
                    tasks=tasks,
                    operators_per_task=int(state.get("operators_per_task") or 3),
                    max_steps=int(draft.get("max_steps") or 20),
                    device=state.get("device") or "desktop",
                )
                serialized = [event.to_dict() for event in phase_events]
                all_events.extend(serialized)
                task_by_phase[phase] = task_metrics(serialized)

            self._write_jsonl(run_dir, "events.jsonl", all_events)

            comparison = {}
            if coverage_by_phase.get(SnapshotPhase.BEFORE.value) and coverage_by_phase.get(SnapshotPhase.AFTER.value):
                comparison = compare_before_after(
                    coverage_by_phase[SnapshotPhase.BEFORE.value],
                    coverage_by_phase[SnapshotPhase.AFTER.value],
                    before_tasks=task_by_phase.get(SnapshotPhase.BEFORE.value) or {},
                    after_tasks=task_by_phase.get(SnapshotPhase.AFTER.value) or {},
                )

            audit_bundle = self._load_audit_bundle(run_dir)
            metrics = {
                "coverage_by_phase": coverage_by_phase,
                "task_metrics_by_phase": task_by_phase,
                "before_after": comparison,
                "events_count": len(all_events),
                "audit": audit_bundle,
            }
            self._write_json(run_dir, "metrics.json", metrics)
            report = build_report_markdown(run_id, metrics, all_events)
            with open(os.path.join(run_dir, "report.md"), "w", encoding="utf-8") as handle:
                handle.write(report)

            state = self._read_json(os.path.join(run_dir, "state.json"))
            state["status"] = RunStatus.COMPLETED.value
            state["completed_at"] = datetime.utcnow().isoformat() + "Z"
            state["job_phase"] = None
            state["progress"] = "Complete"
            state.pop("error", None)
            self._write_json(run_dir, "state.json", state)
            self._consume_credit_on_completion(run_id)
            final_state = self._read_json(os.path.join(run_dir, "state.json"))
            self._sync_run_metadata(final_state)
        except Exception as exc:
            state = self._read_json(os.path.join(run_dir, "state.json"))
            state["status"] = RunStatus.FAILED.value
            state["job_phase"] = None
            state["error"] = str(exc)
            state["progress"] = "Failed"
            self._write_json(run_dir, "state.json", state)
            self._sync_run_metadata(state)

    def process_queued_job(self, raw_payload: Dict[str, Any]) -> Dict[str, Any]:
        payload = parse_job_message(raw_payload)
        run_id = str(payload["run_id"])
        run_dir = self._run_dir(run_id)
        state = self._read_json(os.path.join(run_dir, "state.json"))
        if state.get("status") == RunStatus.COMPLETED.value:
            self._send_completion_notification_when_ready(run_dir)
            return {"run_id": run_id, "skipped": True, "reason": "already_completed"}
        if state.get("status") == RunStatus.FAILED.value and state.get("error") == "Cancelled by user":
            return {"run_id": run_id, "skipped": True, "reason": "cancelled"}

        job_type = str(payload["job_type"])
        phase = payload.get("phase")
        url = payload.get("url")
        job_phase = "crawl" if job_type == "import_snapshot" else ("explore" if job_type == "explore" else "execute")

        now = datetime.utcnow().isoformat() + "Z"
        state["status"] = RunStatus.RUNNING.value
        state["job_phase"] = job_phase
        state["progress"] = {
            "import_snapshot": "Running site crawl...",
            "explore": "Running agent exploration...",
            "execute": "Running live operators...",
        }[job_type]
        state["started_at"] = state.get("started_at") or now
        state["active_job_id"] = payload.get("job_id")
        state["active_job_type"] = job_type
        state["job_started_at"] = now
        state["job_heartbeat_at"] = now
        state["updated_at"] = now
        worker_image = os.environ.get("OPEN_INGRESS_WORKER_IMAGE") or os.environ.get("CONTAINER_APP_REVISION")
        if worker_image:
            state["worker_image"] = worker_image
        state.pop("error", None)
        self._write_json(run_dir, "state.json", state)
        self._sync_run_metadata(state)

        try:
            if job_type == "import_snapshot":
                if not phase or not url:
                    raise ValueError("phase and url are required for import_snapshot jobs.")
                self._import_snapshot_impl(run_id, str(phase), str(url), user_id=payload.get("user_id"))
            elif job_type == "explore":
                self._explore_run_worker(run_id)
            elif job_type == "execute":
                self._execute_run_worker(run_id)

            final_state = self._read_json(os.path.join(run_dir, "state.json"))
            if final_state.get("status") == RunStatus.FAILED.value:
                if final_state.get("error") == "Cancelled by user":
                    return {"run_id": run_id, "cancelled": True}
                raise RuntimeError(str(final_state.get("error") or "Queued job failed."))
            if final_state.get("status") == RunStatus.COMPLETED.value:
                self._send_completion_notification_when_ready(run_dir)
            if not self._queued_job_finished(job_type, final_state):
                final_state["status"] = RunStatus.FAILED.value
                final_state["job_phase"] = None
                final_state["error"] = "Worker exited before finalizing run state"
                final_state["progress"] = "Failed"
                final_state["progress_pct"] = 0
                final_state["updated_at"] = datetime.utcnow().isoformat() + "Z"
                self._write_json(run_dir, "state.json", final_state)
                self._sync_run_metadata(final_state)
                raise RuntimeError(final_state["error"])
            return {"run_id": run_id, "status": final_state.get("status")}
        except (RunCancelled, ImportCancelled):
            state = self._read_json(os.path.join(run_dir, "state.json"))
            state["status"] = RunStatus.FAILED.value
            state["job_phase"] = None
            state["error"] = "Cancelled by user"
            state["progress"] = "Cancelled"
            state["progress_pct"] = 0
            self._write_json(run_dir, "state.json", state)
            self._sync_run_metadata(state)
            return {"run_id": run_id, "cancelled": True}
        except Exception as exc:
            state = self._read_json(os.path.join(run_dir, "state.json"))
            state["status"] = RunStatus.FAILED.value
            state["job_phase"] = None
            state["error"] = str(exc)
            state["progress"] = "Failed"
            state["progress_pct"] = 0
            self._write_json(run_dir, "state.json", state)
            self._sync_run_metadata(state)
            raise

    @staticmethod
    def _queued_job_finished(job_type: str, state: Dict[str, Any]) -> bool:
        status = state.get("status")
        if job_type == "import_snapshot":
            return status in {RunStatus.DRAFT.value, RunStatus.COMPLETED.value}
        return status == RunStatus.COMPLETED.value

    def _send_completion_notification_once(self, run_dir: str) -> None:
        state_path = os.path.join(run_dir, "state.json")
        state = self._read_json(state_path)
        if state.get("completion_email_sent"):
            return

        requester_email = str(state.get("requester_email") or "")
        user_id = str(state.get("user_id") or "")
        if not requester_email and user_id and user_id != "dev":
            from .supabase_client import profile_email

            requester_email = profile_email(user_id)

        try:
            recipients = EmailNotifier().send_completion(state=state, requester_email=requester_email)
        except Exception as exc:
            state["completion_email_error"] = str(exc)
        else:
            if recipients:
                state["completion_email_sent"] = True
                state["completion_email_recipients"] = recipients
                state.pop("completion_email_error", None)
        state["updated_at"] = datetime.utcnow().isoformat() + "Z"
        self._write_json(run_dir, "state.json", state)

    def _send_completion_notification_when_ready(self, run_dir: str) -> None:
        state = self._read_json(os.path.join(run_dir, "state.json"))
        linked_codex_run_id = str(state.get("linked_codex_run_id") or "")
        if not linked_codex_run_id:
            self._send_completion_notification_once(run_dir)
            return

        codex_state_path = os.path.join(self.base_dir, linked_codex_run_id, "codex_state.json")
        if not os.path.isfile(codex_state_path):
            return
        codex_state = self._read_json(codex_state_path)
        if codex_state.get("status") == RunStatus.COMPLETED.value:
            self._send_completion_notification_once(run_dir)

    def _tasks_from_audit(self, run_dir: str) -> List[AgentTask]:
        for name in ("audit.json", "audit_before.json"):
            path = os.path.join(run_dir, name)
            if os.path.isfile(path):
                audit = self._read_json(path)
                tasks = audit.get("probe_tasks") or []
                return [self._task_from_dict(item) for item in tasks]
        return []

    def _load_audit_bundle(self, run_dir: str) -> Dict[str, Any]:
        bundle: Dict[str, Any] = {}
        primary = os.path.join(run_dir, "audit.json")
        if os.path.isfile(primary):
            bundle["site"] = self._read_json(primary)
        for phase in (SnapshotPhase.BEFORE.value, SnapshotPhase.AFTER.value):
            path = os.path.join(run_dir, f"audit_{phase}.json")
            if os.path.isfile(path):
                bundle[phase] = self._read_json(path)
        return bundle

    def _task_from_dict(self, data: Dict[str, Any]) -> AgentTask:
        return AgentTask(
            id=str(data.get("id") or uuid.uuid4().hex[:8]),
            name=str(data.get("name") or "Task"),
            instruction=str(data.get("instruction") or ""),
            success_url_contains=str(data.get("success_url_contains") or ""),
            success_text=str(data.get("success_text") or ""),
            success_selector=str(data.get("success_selector") or ""),
            max_steps=int(data.get("max_steps") or 20),
        )

    def _run_dir(self, run_id: str) -> str:
        path = os.path.join(self.base_dir, run_id)
        if not os.path.isdir(path):
            raise FileNotFoundError(f"Run not found: {run_id}")
        return path

    def _build_agent_report(
        self,
        run_dir: str,
        universe: Dict[str, Any],
        exploration: Dict[str, Any],
        audit: Dict[str, Any],
        events: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        snapshot_path = os.path.join(run_dir, "snapshot_before.json")
        static_audits = {}
        source_url = universe.get("source_url") or ""
        page_html_by_id: Dict[str, str] = {}
        if os.path.isfile(snapshot_path):
            snapshot_data = self._read_json(snapshot_path)
            source_url = snapshot_data.get("source_url") or source_url
            for page in snapshot_data.get("pages") or []:
                pid = str(page.get("id") or "")
                html = str(page.get("html") or "")
                if pid and html:
                    page_html_by_id[pid] = html
        if source_url and page_html_by_id:
            from .static_audits import run_static_audits

            first_html = next(iter(page_html_by_id.values()), "")
            static_audits = {"site": run_static_audits(source_url, first_html)}
        return build_agent_gap_report(
            universe=universe,
            exploration=exploration,
            audit=audit,
            events=events,
            static_audits=static_audits,
            page_html_by_id=page_html_by_id,
            source_url=source_url,
        )

    def _maybe_build_agent_report(self, run_dir: str) -> Optional[Dict[str, Any]]:
        universe_path = os.path.join(run_dir, "universe.json")
        if not os.path.isfile(universe_path):
            return None
        universe = self._read_json(universe_path)
        exploration = self._read_json_optional(run_dir, "exploration.json") or {}
        audit = self._read_json_optional(run_dir, "audit.json") or {}
        events_path = os.path.join(run_dir, "events.jsonl")
        events = self._read_jsonl(events_path) if os.path.isfile(events_path) else []
        if not exploration and not events:
            return None
        report = self._build_agent_report(run_dir, universe, exploration, audit, events)
        self._write_json(run_dir, "agent_report.json", report)
        if audit:
            audit["agent_report"] = report
            self._write_json(run_dir, "audit.json", audit)
        state_path = os.path.join(run_dir, "state.json")
        if os.path.isfile(state_path):
            state = self._read_json(state_path)
            eff = report.get("efficiency") or {}
            state["actions_lost_percent"] = eff.get("actions_lost_percent")
            state["time_lost_percent"] = eff.get("time_lost_percent")
            state["gap_count"] = eff.get("gap_count")
            if not state.get("site_url"):
                state["site_url"] = report.get("source_url") or universe.get("source_url")
            self._write_json(run_dir, "state.json", state)
        return report

    @staticmethod
    def _write_json(directory: str, name: str, payload: Dict[str, Any]) -> None:
        path = os.path.join(directory, name)
        tmp_path = f"{path}.tmp.{uuid.uuid4().hex}"
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)

    def _read_json_optional(self, run_dir: str, filename: str) -> Optional[Dict[str, Any]]:
        path = os.path.join(run_dir, filename)
        if os.path.isfile(path):
            return self._read_json(path)
        return None

    @staticmethod
    def _read_json(path: str) -> Dict[str, Any]:
        last_exc: Exception | None = None
        for _ in range(3):
            try:
                with open(path, encoding="utf-8") as handle:
                    return json.load(handle)
            except json.JSONDecodeError as exc:
                last_exc = exc
                time.sleep(0.05)
        if last_exc:
            raise last_exc
        raise FileNotFoundError(path)

    @staticmethod
    def _write_jsonl(directory: str, name: str, rows: List[Dict[str, Any]]) -> None:
        with open(os.path.join(directory, name), "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")

    @staticmethod
    def _read_jsonl(path: str) -> List[Dict[str, Any]]:
        rows = []
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        return rows
