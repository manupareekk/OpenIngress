"""OpenIngress data models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class RunStatus(str, Enum):
    DRAFT = "draft"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class SnapshotPhase(str, Enum):
    BEFORE = "before"
    AFTER = "after"


class ProductActionType(str, Enum):
    CLICK_LINK = "CLICK_LINK"
    CLICK_CTA = "CLICK_CTA"
    SUBMIT_FORM = "SUBMIT_FORM"
    CONVERT = "CONVERT"


@dataclass
class ExperimentGoal:
    name: str = "task"
    success_selectors: List[str] = field(default_factory=list)
    success_page_ids: List[str] = field(default_factory=list)
    success_page_paths: List[str] = field(default_factory=list)
    success_text: List[str] = field(default_factory=list)
    success_actions: List[str] = field(default_factory=list)


class OperatorActionType(str, Enum):
    VIEW_PAGE = "VIEW_PAGE"
    CLICK = "CLICK"
    TYPE_TEXT = "TYPE_TEXT"
    SCROLL = "SCROLL"
    EXIT = "EXIT"
    TASK_SUCCESS = "TASK_SUCCESS"


class NavigationTargetKind(str, Enum):
    INTERNAL_PAGE = "internal_page"
    INTERNAL_LINK = "internal_link"
    SAME_PAGE_ANCHOR = "same_page_anchor"
    MODAL_OR_STATE_CHANGE = "modal_or_state_change"
    FORM_SUBMIT = "form_submit"
    EXTERNAL_EXIT = "external_exit"
    DOWNLOAD_EXIT = "download_exit"
    AUTH_REQUIRED = "auth_required"
    DEAD_TARGET = "dead_target"
    UNKNOWN_JS = "unknown_js"
    GOAL_REACHED = "goal_reached"


AGENT_ACCESSIBLE_TARGET_KINDS = {
    NavigationTargetKind.INTERNAL_PAGE.value,
    NavigationTargetKind.INTERNAL_LINK.value,
    NavigationTargetKind.SAME_PAGE_ANCHOR.value,
    NavigationTargetKind.MODAL_OR_STATE_CHANGE.value,
    NavigationTargetKind.FORM_SUBMIT.value,
    NavigationTargetKind.GOAL_REACHED.value,
}


@dataclass
class FlowPage:
    id: str
    path: str = ""
    html: str = ""
    title: str = ""
    is_start: bool = False
    is_conversion: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class NavigationAction:
    id: str
    page_id: str
    action_type: str
    selector: str = ""
    tag: str = ""
    element_id: str = ""
    element_text: str = ""
    role: str = ""
    raw_target: str = ""
    target_kind: str = NavigationTargetKind.DEAD_TARGET.value
    target_page_id: str = ""
    target_path: str = ""
    method: str = "GET"
    issue_code: str = ""
    attributes: Dict[str, Any] = field(default_factory=dict)
    context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class NavigationIssue:
    code: str
    severity: str
    page_id: str = ""
    action_id: str = ""
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class NavigationGraph:
    variant_id: str
    start_page_id: str
    pages: List[Dict[str, Any]] = field(default_factory=list)
    actions: List[NavigationAction] = field(default_factory=list)
    issues: List[NavigationIssue] = field(default_factory=list)
    quality: Dict[str, Any] = field(default_factory=dict)
    extractor: str = "static_html"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "start_page_id": self.start_page_id,
            "pages": self.pages,
            "actions": [action.to_dict() for action in self.actions],
            "issues": [issue.to_dict() for issue in self.issues],
            "quality": self.quality,
            "extractor": self.extractor,
        }


@dataclass
class AgentTask:
    id: str
    name: str
    instruction: str
    success_url_contains: str = ""
    success_text: str = ""
    success_selector: str = ""
    max_steps: int = 20

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SiteSnapshot:
    phase: str
    label: str
    source_url: str
    pages: List[FlowPage] = field(default_factory=list)
    navigation_graph: Dict[str, Any] = field(default_factory=dict)
    static_audits: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "phase": self.phase,
            "label": self.label,
            "source_url": self.source_url,
            "pages": [page.to_dict() for page in self.pages],
            "navigation_graph": self.navigation_graph,
            "static_audits": self.static_audits,
        }


@dataclass
class ReadinessRunConfig:
    run_id: str
    compare_before_after: bool = False
    before: Optional[SiteSnapshot] = None
    after: Optional[SiteSnapshot] = None
    tasks: List[AgentTask] = field(default_factory=list)
    operators_per_task: int = 3
    max_steps_per_session: int = 20
    device: str = "desktop"
    live_operator: bool = True

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["before"] = self.before.to_dict() if self.before else None
        data["after"] = self.after.to_dict() if self.after else None
        data["tasks"] = [task.to_dict() for task in self.tasks]
        return data


@dataclass
class OperatorEvent:
    run_id: str
    session_id: str
    task_id: str
    snapshot_phase: str
    step: int
    action: str
    url: str
    element_name: str = ""
    element_role: str = ""
    duration_ms: int = 0
    success: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
