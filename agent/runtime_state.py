"""Mission-state primitives for Hermes runs.

This module provides a canonical in-memory mission state object plus helper
functions to derive it from conversation history and render a human-readable
current-state dashboard.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Iterable, Mapping, Sequence


_DEFAULT_PREVIEW_CHARS = 180


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for block in value:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, Mapping):
                text = block.get("text")
                if isinstance(text, str) and text:
                    parts.append(text)
        return "\n".join(parts)
    return str(value)


def _truncate(text: str, limit: int = _DEFAULT_PREVIEW_CHARS) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _latest_message(messages: Sequence[Mapping[str, Any]], role: str) -> Mapping[str, Any] | None:
    for msg in reversed(messages or []):
        if isinstance(msg, Mapping) and msg.get("role") == role:
            return msg
    return None


def _tool_call_names(message: Mapping[str, Any] | None) -> list[str]:
    if not isinstance(message, Mapping):
        return []
    tool_calls = message.get("tool_calls") or []
    if not isinstance(tool_calls, list):
        return []
    names: list[str] = []
    for call in tool_calls:
        if not isinstance(call, Mapping):
            continue
        fn = call.get("function") or {}
        if not isinstance(fn, Mapping):
            continue
        name = str(fn.get("name") or "").strip()
        if name:
            names.append(name)
    return names


@dataclass(slots=True)
class ToolScopeMatrix:
    """Structured snapshot of the active tool-scope policy."""

    scope_mode: str = "full"
    source: str = ""
    platform: str = ""
    requested_enabled_toolsets: list[str] = field(default_factory=list)
    requested_disabled_toolsets: list[str] = field(default_factory=list)
    effective_toolsets: list[str] = field(default_factory=list)
    effective_tool_names: list[str] = field(default_factory=list)
    visible_tool_count: int = 0
    notes: str = ""
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["requested_enabled_toolsets"] = [
            str(item) for item in payload.get("requested_enabled_toolsets", []) if str(item).strip()
        ]
        payload["requested_disabled_toolsets"] = [
            str(item) for item in payload.get("requested_disabled_toolsets", []) if str(item).strip()
        ]
        payload["effective_toolsets"] = [str(item) for item in payload.get("effective_toolsets", []) if str(item).strip()]
        payload["effective_tool_names"] = [
            str(item) for item in payload.get("effective_tool_names", []) if str(item).strip()
        ]
        payload["visible_tool_count"] = max(0, int(payload.get("visible_tool_count") or 0))
        payload["updated_at"] = float(payload.get("updated_at") or 0.0)
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "ToolScopeMatrix":
        if not isinstance(data, Mapping):
            return cls()
        return cls(
            scope_mode=str(data.get("scope_mode") or "full"),
            source=str(data.get("source") or ""),
            platform=str(data.get("platform") or ""),
            requested_enabled_toolsets=[
                str(item) for item in (data.get("requested_enabled_toolsets") or []) if str(item).strip()
            ],
            requested_disabled_toolsets=[
                str(item) for item in (data.get("requested_disabled_toolsets") or []) if str(item).strip()
            ],
            effective_toolsets=[
                str(item) for item in (data.get("effective_toolsets") or []) if str(item).strip()
            ],
            effective_tool_names=[
                str(item) for item in (data.get("effective_tool_names") or []) if str(item).strip()
            ],
            visible_tool_count=int(data.get("visible_tool_count") or 0),
            notes=str(data.get("notes") or ""),
            updated_at=float(data.get("updated_at") or 0.0),
        )


def build_tool_scope_matrix(
    *,
    enabled_toolsets: Sequence[str] | None = None,
    disabled_toolsets: Sequence[str] | None = None,
    available_tool_names: Sequence[str] | None = None,
    source: str = "",
    platform: str = "",
    notes: str = "",
    updated_at: float | None = None,
) -> ToolScopeMatrix:
    """Build a compact tool-scope snapshot for persistence and UI display."""
    try:
        from toolsets import get_all_toolsets, resolve_toolset, validate_toolset
    except Exception:
        get_all_toolsets = None  # type: ignore[assignment]
        resolve_toolset = None  # type: ignore[assignment]
        validate_toolset = None  # type: ignore[assignment]

    requested_enabled = [str(item).strip() for item in (enabled_toolsets or []) if str(item).strip()]
    requested_disabled = [str(item).strip() for item in (disabled_toolsets or []) if str(item).strip()]
    disabled_set = set(requested_disabled)

    if requested_enabled:
        candidate_toolsets = list(dict.fromkeys(requested_enabled))
    else:
        candidate_toolsets = sorted(str(name) for name in (get_all_toolsets().keys() if get_all_toolsets else []))

    if validate_toolset is not None:
        effective_toolsets = [ts for ts in candidate_toolsets if validate_toolset(ts)]
    else:
        effective_toolsets = list(candidate_toolsets)
    if disabled_set:
        effective_toolsets = [ts for ts in effective_toolsets if ts not in disabled_set]

    tool_names: set[str] = {str(item).strip() for item in (available_tool_names or []) if str(item).strip()}
    if not tool_names and resolve_toolset is not None:
        for toolset_name in effective_toolsets:
            try:
                tool_names.update(resolve_toolset(toolset_name))
            except Exception:
                continue

    if requested_enabled and requested_disabled:
        scope_mode = "allowlist+denylist"
    elif requested_enabled:
        scope_mode = "allowlist"
    elif requested_disabled:
        scope_mode = "denylist"
    else:
        scope_mode = "full"

    return ToolScopeMatrix(
        scope_mode=scope_mode,
        source=str(source or ""),
        platform=str(platform or ""),
        requested_enabled_toolsets=requested_enabled,
        requested_disabled_toolsets=requested_disabled,
        effective_toolsets=sorted(dict.fromkeys(effective_toolsets)),
        effective_tool_names=sorted(tool_names),
        visible_tool_count=len(tool_names),
        notes=str(notes or ""),
        updated_at=float(updated_at if updated_at is not None else time.time()),
    )


@dataclass(slots=True)
class ChildRunState:
    subagent_id: str = ""
    session_id: str = ""
    parent_session_id: str = ""
    goal: str = ""
    role: str = "leaf"
    status: str = "running"
    retries: int = 0
    cleaned_up: bool = False
    task_index: int = -1
    started_at: float = 0.0
    updated_at: float = 0.0
    ended_at: float = 0.0
    exit_reason: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        task_index_value = payload.get("task_index")
        payload["retries"] = max(0, int(payload.get("retries") or 0))
        payload["task_index"] = int(task_index_value) if task_index_value is not None else -1
        payload["cleaned_up"] = bool(payload.get("cleaned_up"))
        payload["started_at"] = float(payload.get("started_at") or 0.0)
        payload["updated_at"] = float(payload.get("updated_at") or 0.0)
        payload["ended_at"] = float(payload.get("ended_at") or 0.0)
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "ChildRunState":
        if not isinstance(data, Mapping):
            return cls()
        task_index_value = data.get("task_index")
        return cls(
            subagent_id=str(data.get("subagent_id") or ""),
            session_id=str(data.get("session_id") or ""),
            parent_session_id=str(data.get("parent_session_id") or ""),
            goal=str(data.get("goal") or ""),
            role=str(data.get("role") or "leaf"),
            status=str(data.get("status") or "running"),
            retries=int(data.get("retries") or 0),
            cleaned_up=bool(data.get("cleaned_up") or False),
            task_index=(int(task_index_value) if task_index_value is not None else -1),
            started_at=float(data.get("started_at") or 0.0),
            updated_at=float(data.get("updated_at") or 0.0),
            ended_at=float(data.get("ended_at") or 0.0),
            exit_reason=str(data.get("exit_reason") or ""),
            error=str(data.get("error") or ""),
        )


@dataclass(slots=True)
class AuditEventState:
    """Compact durable audit event for a mission timeline."""

    category: str = "decision"
    subject: str = ""
    outcome: str = ""
    detail: str = ""
    source: str = ""
    session_id: str = ""
    tool_call_id: str = ""
    child_session_id: str = ""
    subagent_id: str = ""
    task_index: int = -1
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["category"] = str(payload.get("category") or "decision")
        payload["subject"] = str(payload.get("subject") or "")
        payload["outcome"] = str(payload.get("outcome") or "")
        payload["detail"] = str(payload.get("detail") or "")
        payload["source"] = str(payload.get("source") or "")
        payload["session_id"] = str(payload.get("session_id") or "")
        payload["tool_call_id"] = str(payload.get("tool_call_id") or "")
        payload["child_session_id"] = str(payload.get("child_session_id") or "")
        payload["subagent_id"] = str(payload.get("subagent_id") or "")
        payload["task_index"] = int(payload.get("task_index") or -1)
        payload["updated_at"] = float(payload.get("updated_at") or 0.0)
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "AuditEventState":
        if not isinstance(data, Mapping):
            return cls()
        return cls(
            category=str(data.get("category") or "decision"),
            subject=str(data.get("subject") or ""),
            outcome=str(data.get("outcome") or ""),
            detail=str(data.get("detail") or ""),
            source=str(data.get("source") or ""),
            session_id=str(data.get("session_id") or ""),
            tool_call_id=str(data.get("tool_call_id") or ""),
            child_session_id=str(data.get("child_session_id") or ""),
            subagent_id=str(data.get("subagent_id") or ""),
            task_index=int(data.get("task_index") or -1),
            updated_at=float(data.get("updated_at") or 0.0),
        )


@dataclass(slots=True)
class MissionState:
    """Canonical live mission state for a single run."""

    session_id: str = ""
    session_title: str = ""
    source: str = ""
    status: str = "active"
    goal: str = ""
    next_action: str = ""
    verified_state: str = ""
    assumed_state: str = ""
    constraints: list[str] = field(default_factory=list)
    resume_hint: str = ""
    parent_session_id: str = ""
    child_session_ids: list[str] = field(default_factory=list)
    child_runs: list[ChildRunState] = field(default_factory=list)
    audit_events: list[AuditEventState] = field(default_factory=list)
    tool_scope: ToolScopeMatrix = field(default_factory=ToolScopeMatrix)
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["constraints"] = [str(item) for item in payload.get("constraints", []) if str(item).strip()]
        payload["child_session_ids"] = [str(item) for item in payload.get("child_session_ids", []) if str(item).strip()]
        payload["child_runs"] = [
            item.to_dict() if isinstance(item, ChildRunState) else ChildRunState.from_dict(item).to_dict()
            for item in payload.get("child_runs", [])
            if item is not None
        ]
        if not payload["child_session_ids"] and payload["child_runs"]:
            payload["child_session_ids"] = [
                run.get("session_id", "")
                for run in payload["child_runs"]
                if str(run.get("session_id") or "").strip()
            ]
        payload["audit_events"] = [
            item.to_dict() if isinstance(item, AuditEventState) else AuditEventState.from_dict(item).to_dict()
            for item in payload.get("audit_events", [])
            if item is not None
        ]
        tool_scope_value = payload.get("tool_scope")
        payload["tool_scope"] = (
            tool_scope_value.to_dict()
            if isinstance(tool_scope_value, ToolScopeMatrix)
            else ToolScopeMatrix.from_dict(tool_scope_value).to_dict()
        )
        payload.setdefault("updated_at", 0.0)
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "MissionState":
        if not isinstance(data, Mapping):
            return cls()
        constraints = data.get("constraints") or []
        child_session_ids = data.get("child_session_ids") or []
        child_runs = data.get("child_runs") or []
        audit_events = data.get("audit_events") or []
        tool_scope = data.get("tool_scope") or {}
        return cls(
            session_id=str(data.get("session_id") or ""),
            session_title=str(data.get("session_title") or ""),
            source=str(data.get("source") or ""),
            status=str(data.get("status") or "active"),
            goal=str(data.get("goal") or ""),
            next_action=str(data.get("next_action") or ""),
            verified_state=str(data.get("verified_state") or ""),
            assumed_state=str(data.get("assumed_state") or ""),
            constraints=[str(item) for item in constraints if str(item).strip()] if isinstance(constraints, list) else [],
            resume_hint=str(data.get("resume_hint") or ""),
            parent_session_id=str(data.get("parent_session_id") or ""),
            child_session_ids=[str(item) for item in child_session_ids if str(item).strip()] if isinstance(child_session_ids, list) else [],
            child_runs=[ChildRunState.from_dict(item) for item in child_runs if isinstance(item, Mapping)] if isinstance(child_runs, list) else [],
            audit_events=[AuditEventState.from_dict(item) for item in audit_events if isinstance(item, Mapping)] if isinstance(audit_events, list) else [],
            tool_scope=ToolScopeMatrix.from_dict(tool_scope),
            updated_at=float(data.get("updated_at") or 0.0),
        )

    @classmethod
    def from_json(cls, raw: str | None) -> "MissionState":
        if not raw:
            return cls()
        try:
            parsed = json.loads(raw)
        except Exception:
            return cls()
        return cls.from_dict(parsed if isinstance(parsed, Mapping) else None)


def build_mission_state_from_messages(
    messages: Sequence[Mapping[str, Any]],
    *,
    session_id: str = "",
    session_title: str = "",
    source: str = "",
    status: str = "active",
    parent_session_id: str = "",
    child_session_ids: Sequence[str] | None = None,
    child_runs: Sequence[Mapping[str, Any] | ChildRunState] | None = None,
    audit_events: Sequence[Mapping[str, Any] | AuditEventState] | None = None,
    tool_scope: Mapping[str, Any] | ToolScopeMatrix | None = None,
    updated_at: float | None = None,
) -> MissionState:
    """Infer a live mission-state snapshot from conversation history."""
    latest_user = _latest_message(messages, "user")
    latest_assistant = _latest_message(messages, "assistant")
    latest_tool = _latest_message(messages, "tool")

    latest_user_text = _truncate(_coerce_text(latest_user.get("content") if latest_user else ""), 220)
    latest_assistant_text = _truncate(_coerce_text(latest_assistant.get("content") if latest_assistant else ""), 220)
    latest_tool_text = _truncate(_coerce_text(latest_tool.get("content") if latest_tool else ""), 220)
    pending_tool_calls = _tool_call_names(latest_assistant)

    goal = latest_user_text or session_title or ""
    if pending_tool_calls:
        next_action = "Execute pending tool call(s): " + ", ".join(pending_tool_calls[:5])
    else:
        next_action = latest_assistant_text or ""

    if latest_tool_text:
        verified_state = f"Last tool result: {latest_tool_text}"
    elif latest_assistant_text:
        verified_state = f"Latest assistant reply: {latest_assistant_text}"
    else:
        verified_state = ""

    if pending_tool_calls:
        assumed_state = "Waiting on tool results before updating the plan."
    elif latest_assistant_text:
        assumed_state = f"Assistant assumption: {latest_assistant_text}"
    elif latest_user_text:
        assumed_state = f"User request: {latest_user_text}"
    else:
        assumed_state = ""

    if pending_tool_calls:
        resume_hint = "Resume by executing the pending tool call(s), then reconcile the result with the goal."
    elif latest_user_text:
        resume_hint = f"Resume by answering the latest user request: {latest_user_text}"
    else:
        resume_hint = "Resume from the latest known session state."

    return MissionState(
        session_id=str(session_id or ""),
        session_title=str(session_title or ""),
        source=str(source or ""),
        status=str(status or "active"),
        goal=goal,
        next_action=next_action,
        verified_state=verified_state,
        assumed_state=assumed_state,
        constraints=[],
        resume_hint=resume_hint,
        parent_session_id=str(parent_session_id or ""),
        child_session_ids=[str(item) for item in (child_session_ids or []) if str(item).strip()],
        child_runs=[
            item if isinstance(item, ChildRunState) else ChildRunState.from_dict(item)
            for item in (child_runs or [])
            if item is not None
        ],
        audit_events=[
            item if isinstance(item, AuditEventState) else AuditEventState.from_dict(item)
            for item in (audit_events or [])
            if item is not None
        ],
        tool_scope=tool_scope if isinstance(tool_scope, ToolScopeMatrix) else ToolScopeMatrix.from_dict(tool_scope),
        updated_at=float(updated_at if updated_at is not None else time.time()),
    )


def build_audit_event(
    *,
    category: str,
    subject: str = "",
    outcome: str = "",
    detail: str = "",
    source: str = "",
    session_id: str = "",
    tool_call_id: str = "",
    child_session_id: str = "",
    subagent_id: str = "",
    task_index: int = -1,
    updated_at: float | None = None,
) -> AuditEventState:
    return AuditEventState(
        category=str(category or "decision"),
        subject=str(subject or ""),
        outcome=str(outcome or ""),
        detail=str(detail or ""),
        source=str(source or ""),
        session_id=str(session_id or ""),
        tool_call_id=str(tool_call_id or ""),
        child_session_id=str(child_session_id or ""),
        subagent_id=str(subagent_id or ""),
        task_index=int(task_index if task_index is not None else -1),
        updated_at=float(updated_at if updated_at is not None else time.time()),
    )


def append_audit_event(
    state: MissionState,
    event: Mapping[str, Any] | AuditEventState,
    *,
    max_events: int = 20,
) -> MissionState:
    event_state = event if isinstance(event, AuditEventState) else AuditEventState.from_dict(event)
    if event_state.updated_at <= 0:
        event_state.updated_at = time.time()
    state.audit_events.append(event_state)
    if max_events > 0 and len(state.audit_events) > max_events:
        state.audit_events = state.audit_events[-max_events:]
    state.updated_at = max(state.updated_at, event_state.updated_at)
    return state


def render_mission_state_dashboard(state: MissionState | Mapping[str, Any]) -> str:
    """Render a compact human-readable dashboard for the current mission."""
    if not isinstance(state, MissionState):
        state = MissionState.from_dict(state)

    lines: list[str] = ["Current mission state"]
    if state.session_title or state.session_id:
        session_bits = []
        if state.session_title:
            session_bits.append(state.session_title)
        if state.session_id:
            session_bits.append(state.session_id[:8])
        lines.append(f"  Session: {' — '.join(session_bits)}")
    if state.status:
        lines.append(f"  Status: {state.status}")
    if state.goal:
        lines.append(f"  Goal: {_truncate(state.goal, 220)}")
    if state.next_action:
        lines.append(f"  Next action: {_truncate(state.next_action, 220)}")
    if state.verified_state:
        lines.append(f"  Verified: {_truncate(state.verified_state, 220)}")
    if state.assumed_state:
        lines.append(f"  Assumed: {_truncate(state.assumed_state, 220)}")
    if state.constraints:
        lines.append(f"  Constraints: {', '.join(_truncate(item, 64) for item in state.constraints[:5])}")
    else:
        lines.append("  Constraints: none")
    if state.resume_hint:
        lines.append(f"  Resume: {_truncate(state.resume_hint, 220)}")
    lineage_bits: list[str] = []
    if state.parent_session_id:
        lineage_bits.append(f"parent={state.parent_session_id[:8]}")
    if state.child_session_ids:
        shown = ", ".join(child[:8] for child in state.child_session_ids[:5])
        extra = len(state.child_session_ids) - min(len(state.child_session_ids), 5)
        if extra > 0:
            shown += f" (+{extra} more)"
        lineage_bits.append(f"children={shown}")
    if lineage_bits:
        lines.append(f"  Lineage: {'; '.join(lineage_bits)}")
    if state.child_runs:
        entries = []
        for child in state.child_runs[:5]:
            if not isinstance(child, ChildRunState):
                child = ChildRunState.from_dict(child)
            label = child.subagent_id[:8] or child.session_id[:8] or "child"
            status = child.status or "running"
            retry_suffix = f", retries={child.retries}" if child.retries else ""
            cleanup_suffix = ", cleaned" if child.cleaned_up else ""
            entries.append(f"{label}:{status}{retry_suffix}{cleanup_suffix}")
        extra = len(state.child_runs) - min(len(state.child_runs), 5)
        if extra > 0:
            entries[-1] = entries[-1] + f" (+{extra} more)"
        lines.append(f"  Child runs: {', '.join(entries)}")
    if state.audit_events:
        recent = []
        for item in state.audit_events[-3:]:
            if not isinstance(item, AuditEventState):
                item = AuditEventState.from_dict(item)
            label = item.category or "event"
            subject = item.subject or item.child_session_id or item.tool_call_id or ""
            outcome = item.outcome or ""
            piece = ":".join(part for part in (label, subject, outcome) if part)
            if piece:
                recent.append(piece)
        if recent:
            extra = len(state.audit_events) - min(len(state.audit_events), 3)
            if extra > 0:
                recent[-1] = recent[-1] + f" (+{extra} more)"
            lines.append(f"  Audit: {len(state.audit_events)} events; recent={'; '.join(recent)}")
    if state.tool_scope:
        scope = state.tool_scope if isinstance(state.tool_scope, ToolScopeMatrix) else ToolScopeMatrix.from_dict(state.tool_scope)
        enabled = ", ".join(scope.requested_enabled_toolsets[:5]) or "all"
        disabled = ", ".join(scope.requested_disabled_toolsets[:5]) or "none"
        lines.append(
            f"  Tool scope: mode={scope.scope_mode}; enabled={enabled}; disabled={disabled}; tools={scope.visible_tool_count}"
        )
    if state.updated_at:
        lines.append(f"  Updated: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(state.updated_at))}")
    return "\n".join(lines)


__all__ = [
    "ToolScopeMatrix",
    "ChildRunState",
    "AuditEventState",
    "MissionState",
    "build_tool_scope_matrix",
    "build_mission_state_from_messages",
    "build_audit_event",
    "append_audit_event",
    "render_mission_state_dashboard",
]
