"""Tests for agent.runtime_state mission-state helpers."""
from __future__ import annotations

from agent.runtime_state import (
    AuditEventState,
    ChildRunState,
    MissionState,
    ToolScopeMatrix,
    append_audit_event,
    build_audit_event,
    build_mission_state_from_messages,
    build_tool_scope_matrix,
    render_mission_state_dashboard,
)


def _user(text):
    return {"role": "user", "content": text}


def _assistant(text=None, tool_calls=None):
    msg = {"role": "assistant", "content": text}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return msg


def _tool(text="ok"):
    return {"role": "tool", "content": text}


def _tool_call(name, args):
    return {
        "id": f"call_{name}",
        "type": "function",
        "function": {"name": name, "arguments": args},
    }


def test_mission_state_roundtrip_json():
    state = MissionState(
        session_id="sess-1",
        session_title="Refactor core runtime",
        source="cli",
        goal="extend the disk",
        next_action="check the host",
        verified_state="Space freed on host",
        assumed_state="Disk still near full",
        constraints=["least privilege"],
        resume_hint="resume from the last verified step",
        parent_session_id="parent-1",
        child_session_ids=["child-1", "child-2"],
        child_runs=[
            ChildRunState(
                subagent_id="sa-1",
                session_id="child-1",
                parent_session_id="parent-1",
                goal="check storage",
                role="leaf",
                status="completed",
                retries=1,
                cleaned_up=True,
                task_index=0,
                started_at=11.0,
                updated_at=12.0,
                ended_at=12.0,
                exit_reason="completed",
            )
        ],
        tool_scope=ToolScopeMatrix(
            scope_mode="allowlist",
            source="cli",
            platform="cli",
            requested_enabled_toolsets=["web", "terminal"],
            requested_disabled_toolsets=["memory"],
            effective_toolsets=["web", "terminal"],
            effective_tool_names=["terminal", "web_search"],
            visible_tool_count=2,
            notes="test scope",
            updated_at=121.0,
        ),
        updated_at=123.45,
    )

    restored = MissionState.from_json(state.to_json())
    assert restored == state


def test_mission_state_audit_event_roundtrip_and_rollup():
    state = MissionState(session_id="sess-audit")
    event = build_audit_event(
        category="decision",
        subject="terminal",
        outcome="allow",
        detail="pre-tool check passed",
        source="cli",
        session_id="sess-audit",
        tool_call_id="call-terminal",
        task_index=2,
        updated_at=5.0,
    )

    append_audit_event(state, event, max_events=2)
    append_audit_event(
        state,
        AuditEventState(category="tool_call", subject="terminal", outcome="success", updated_at=6.0),
        max_events=2,
    )
    append_audit_event(
        state,
        {"category": "chain", "subject": "delegate_task", "outcome": "spawn", "updated_at": 7.0},
        max_events=2,
    )

    assert [item.category for item in state.audit_events] == ["tool_call", "chain"]
    assert state.audit_events[-1].subject == "delegate_task"
    assert state.updated_at == 7.0
    restored = MissionState.from_json(state.to_json())
    assert [item.category for item in restored.audit_events] == ["tool_call", "chain"]
    assert restored.audit_events[-1].outcome == "spawn"


def test_build_tool_scope_matrix_summarizes_request_and_effective_tools():
    matrix = build_tool_scope_matrix(
        enabled_toolsets=["web", "terminal"],
        disabled_toolsets=["memory"],
        available_tool_names=["terminal", "web_search"],
        source="cli",
        platform="cli",
        notes="demo",
        updated_at=7.0,
    )

    assert matrix.scope_mode == "allowlist+denylist"
    assert matrix.requested_enabled_toolsets == ["web", "terminal"]
    assert matrix.requested_disabled_toolsets == ["memory"]
    assert matrix.effective_tool_names == ["terminal", "web_search"]
    assert matrix.visible_tool_count == 2
    assert matrix.updated_at == 7.0


def test_build_mission_state_from_messages_uses_latest_activity():
    messages = [
        _user("please extend the disk on Hermes00"),
        _assistant(
            tool_calls=[
                _tool_call("terminal", {"command": "df -h"}),
                _tool_call("read_file", {"path": "/etc/fstab"}),
            ]
        ),
        _tool("Filesystem is 92% used after cleanup."),
    ]

    state = build_mission_state_from_messages(
        messages,
        session_id="sess-2",
        session_title="Extend the disk",
        source="discord",
        parent_session_id="parent-9",
        child_session_ids=["child-a"],
        updated_at=42.0,
    )

    assert state.session_id == "sess-2"
    assert state.goal == "please extend the disk on Hermes00"
    assert state.next_action.startswith("Execute pending tool call(s):")
    assert "terminal" in state.next_action
    assert "Filesystem is 92% used" in state.verified_state
    assert "Waiting on tool results" in state.assumed_state
    assert "pending tool call" in state.resume_hint.lower()
    assert state.parent_session_id == "parent-9"
    assert state.child_session_ids == ["child-a"]
    assert state.updated_at == 42.0


def test_render_mission_state_dashboard_shows_lineage_and_resume_hint():
    state = MissionState(
        session_id="sess-3",
        session_title="Disk expansion",
        status="active",
        goal="add space to Hermes00",
        next_action="verify storage backing",
        verified_state="Space is available",
        assumed_state="Host still needs a restart",
        constraints=["no downtime"],
        resume_hint="resume by verifying the storage layer",
        parent_session_id="parent-2",
        child_session_ids=["child-1", "child-2"],
        child_runs=[ChildRunState(subagent_id="sa-1", session_id="child-1", status="running")],
        tool_scope=ToolScopeMatrix(
            scope_mode="denylist",
            source="discord",
            platform="discord",
            requested_disabled_toolsets=["terminal"],
            effective_toolsets=["web", "file"],
            effective_tool_names=["read_file", "web_search"],
            visible_tool_count=2,
        ),
        updated_at=99.0,
    )

    out = render_mission_state_dashboard(state)
    assert "Current mission state" in out
    assert "Disk expansion" in out
    assert "Goal: add space to Hermes00" in out
    assert "Lineage: parent=parent-2" in out
    assert "Child runs:" in out
    assert "Tool scope: mode=denylist" in out
    assert "resume by verifying the storage layer" in out
