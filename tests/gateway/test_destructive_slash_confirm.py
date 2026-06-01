"""Tests for the gateway's destructive-slash-confirm wrapper.

When ``approvals.destructive_slash_confirm`` is True (default), /new,
/reset, and /undo route through the slash-confirm primitive — native
yes/no buttons on Telegram/Discord/Slack, text fallback elsewhere.
When False (after "Always Approve"), the destructive action runs
immediately.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platforms.base import MessageEvent
from gateway.session import SessionEntry, SessionSource, build_session_key


def _make_source() -> SessionSource:
    return SessionSource(
        platform=Platform.TELEGRAM,
        user_id="u1",
        chat_id="c1",
        user_name="tester",
        chat_type="dm",
    )


def _make_event(text: str) -> MessageEvent:
    return MessageEvent(text=text, source=_make_source(), message_id="m1")


def _make_runner():
    """Mirror tests/gateway/test_unknown_command.py::_make_runner."""
    from gateway.run import GatewayRunner

    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig(
        platforms={Platform.TELEGRAM: PlatformConfig(enabled=True, token="***")}
    )
    adapter = MagicMock()
    adapter.send = AsyncMock()
    # No send_slash_confirm override -> button render returns None,
    # _request_slash_confirm falls back to text path.
    adapter.send_slash_confirm = AsyncMock(return_value=None)
    runner.adapters = {Platform.TELEGRAM: adapter}

    session_entry = SessionEntry(
        session_key=build_session_key(_make_source()),
        session_id="sess-1",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        platform=Platform.TELEGRAM,
        chat_type="dm",
    )
    runner.session_store = MagicMock()
    runner.session_store.get_or_create_session.return_value = session_entry
    runner.session_store.load_transcript.return_value = []
    runner.session_store.append_to_transcript = MagicMock()
    runner.session_store.rewrite_transcript = MagicMock()

    runner._running_agents = {}
    runner._pending_messages = {}
    import itertools as _it
    runner._slash_confirm_counter = _it.count(1)
    runner.hooks = SimpleNamespace(
        emit=AsyncMock(),
        emit_collect=AsyncMock(return_value=[]),
        loaded_hooks=False,
    )
    runner._thread_metadata_for_source = lambda *a, **kw: None
    runner._reply_anchor_for_event = lambda _e: None
    return runner


@pytest.mark.asyncio
async def test_gate_off_runs_execute_immediately(monkeypatch):
    """When approvals.destructive_slash_confirm is False, the destructive
    action runs immediately without prompting."""
    runner = _make_runner()
    runner._read_user_config = lambda: {"approvals": {"destructive_slash_confirm": False}}
    runner._session_key_for_source = lambda src: build_session_key(src)

    sentinel = "✨ Session reset!"
    execute = AsyncMock(return_value=sentinel)

    result = await runner._maybe_confirm_destructive_slash(
        event=_make_event("/new"),
        command="new",
        title="/new",
        detail="Discards history.",
        execute=execute,
    )

    execute.assert_awaited_once()
    assert result == sentinel


@pytest.mark.asyncio
async def test_gate_on_text_fallback_returns_prompt_without_executing(monkeypatch):
    """When the gate is on and the adapter has no button UI, the user gets
    a text prompt back and the destructive action is NOT yet run."""
    runner = _make_runner()
    runner._read_user_config = lambda: {"approvals": {"destructive_slash_confirm": True}}
    runner._session_key_for_source = lambda src: build_session_key(src)

    execute = AsyncMock(return_value="should not run yet")

    result = await runner._maybe_confirm_destructive_slash(
        event=_make_event("/new"),
        command="new",
        title="/new",
        detail="Discards history.",
        execute=execute,
    )

    execute.assert_not_awaited()
    assert isinstance(result, str)
    assert "Confirm /new" in result
    assert "Approve Once" in result
    assert "Cancel" in result


@pytest.mark.asyncio
async def test_gate_on_pending_confirm_registered(monkeypatch):
    """When the gate is on, a pending slash-confirm entry is registered for
    the session — the user's /approve reply will resolve it."""
    from tools import slash_confirm as _slash_confirm_mod
    runner = _make_runner()
    runner._read_user_config = lambda: {"approvals": {"destructive_slash_confirm": True}}
    session_key = build_session_key(_make_source())
    runner._session_key_for_source = lambda src: session_key
    _slash_confirm_mod.clear(session_key)

    execute = AsyncMock(return_value="reset done")

    await runner._maybe_confirm_destructive_slash(
        event=_make_event("/new"),
        command="new",
        title="/new",
        detail="Discards history.",
        execute=execute,
    )

    pending = _slash_confirm_mod.get_pending(session_key)
    assert pending is not None
    assert pending["command"] == "new"
    _slash_confirm_mod.clear(session_key)


@pytest.mark.asyncio
async def test_resolve_once_runs_execute_and_returns_result():
    """Resolving the pending confirm with 'once' runs the destructive
    action and returns its output."""
    from tools import slash_confirm as _slash_confirm_mod
    runner = _make_runner()
    runner._read_user_config = lambda: {"approvals": {"destructive_slash_confirm": True}}
    session_key = build_session_key(_make_source())
    runner._session_key_for_source = lambda src: session_key
    _slash_confirm_mod.clear(session_key)

    execute = AsyncMock(return_value="✨ fresh session")

    await runner._maybe_confirm_destructive_slash(
        event=_make_event("/new"),
        command="new",
        title="/new",
        detail="Discards history.",
        execute=execute,
    )

    pending = _slash_confirm_mod.get_pending(session_key)
    assert pending is not None

    resolved = await _slash_confirm_mod.resolve(
        session_key, pending["confirm_id"], "once",
    )

    execute.assert_awaited_once()
    assert resolved == "✨ fresh session"
    # Pending should be cleared after resolve.
    assert _slash_confirm_mod.get_pending(session_key) is None


@pytest.mark.asyncio
async def test_resolve_cancel_does_not_run_execute():
    """Resolving with 'cancel' must NOT run the destructive action."""
    from tools import slash_confirm as _slash_confirm_mod
    runner = _make_runner()
    runner._read_user_config = lambda: {"approvals": {"destructive_slash_confirm": True}}
    session_key = build_session_key(_make_source())
    runner._session_key_for_source = lambda src: session_key
    _slash_confirm_mod.clear(session_key)

    execute = AsyncMock(side_effect=AssertionError("execute must NOT run on cancel"))

    await runner._maybe_confirm_destructive_slash(
        event=_make_event("/new"),
        command="new",
        title="/new",
        detail="Discards history.",
        execute=execute,
    )

    pending = _slash_confirm_mod.get_pending(session_key)
    assert pending is not None

    resolved = await _slash_confirm_mod.resolve(
        session_key, pending["confirm_id"], "cancel",
    )

    execute.assert_not_awaited()
    assert resolved is not None
    assert "cancelled" in resolved.lower()


@pytest.mark.asyncio
async def test_resolve_always_persists_opt_out_and_runs_execute(monkeypatch):
    """Resolving with 'always' must (a) flip the config gate to False,
    (b) run execute, and (c) include a one-time opt-out note in the reply."""
    from tools import slash_confirm as _slash_confirm_mod
    runner = _make_runner()
    runner._read_user_config = lambda: {"approvals": {"destructive_slash_confirm": True}}
    session_key = build_session_key(_make_source())
    runner._session_key_for_source = lambda src: session_key
    _slash_confirm_mod.clear(session_key)

    saved: dict = {}

    def _fake_save(path, value):
        saved[path] = value
        return True

    import cli as cli_mod
    monkeypatch.setattr(cli_mod, "save_config_value", _fake_save)

    execute = AsyncMock(return_value="✨ fresh")

    await runner._maybe_confirm_destructive_slash(
        event=_make_event("/new"),
        command="new",
        title="/new",
        detail="Discards history.",
        execute=execute,
    )

    pending = _slash_confirm_mod.get_pending(session_key)
    assert pending is not None
    resolved = await _slash_confirm_mod.resolve(
        session_key, pending["confirm_id"], "always",
    )

    execute.assert_awaited_once()
    assert saved.get("approvals.destructive_slash_confirm") is False
    assert resolved is not None
    assert "✨ fresh" in resolved


@pytest.mark.asyncio
async def test_rollback_command_resolve_once_runs_restore_and_returns_result(monkeypatch):
    """Resolving the /rollback confirm with 'once' must run restore and return
    the reversible-restore message rather than leaving the checkpoint untouched."""
    from tools import slash_confirm as _slash_confirm_mod

    runner = _make_runner()
    runner._read_user_config = lambda: {"approvals": {"destructive_slash_confirm": True}}
    session_key = build_session_key(_make_source())
    runner._session_key_for_source = lambda source: session_key
    _slash_confirm_mod.clear(session_key)

    temp_home = Path("/tmp/rollback-home")
    temp_home.mkdir(parents=True, exist_ok=True)
    (temp_home / "config.yaml").write_text(
        "checkpoints:\n  enabled: true\n  max_snapshots: 10\n", encoding="utf-8"
    )
    monkeypatch.setattr("gateway.run._hermes_home", temp_home)

    created_managers = []

    class FakeCheckpointManager:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.diff_calls = []
            self.restore_calls = []
            self.list_calls = []
            created_managers.append(self)

        def list_checkpoints(self, cwd):
            self.list_calls.append(cwd)
            return [{"hash": "abc12345", "short_hash": "abc12345", "reason": "before patch"}]

        def diff(self, cwd, target_hash):
            self.diff_calls.append((cwd, target_hash))
            return {"success": True, "stat": " 1 file changed", "diff": "diff --git a/a b/a\n"}

        def restore(self, cwd, target_hash):
            self.restore_calls.append((cwd, target_hash))
            return {"success": True, "restored_to": target_hash[:8], "reason": "before patch"}

    monkeypatch.setattr("tools.checkpoint_manager.CheckpointManager", FakeCheckpointManager)
    monkeypatch.setattr("tools.checkpoint_manager.format_checkpoint_list", lambda *_args, **_kwargs: "LIST")
    monkeypatch.setenv("TERMINAL_CWD", "/tmp/rollback-work")

    await runner._handle_rollback_command(_make_event("/rollback abc12345"))
    pending = _slash_confirm_mod.get_pending(session_key)
    assert pending is not None

    resolved = await _slash_confirm_mod.resolve(
        session_key, pending["confirm_id"], "once"
    )

    assert created_managers, "rollback should create a checkpoint manager"
    mgr = created_managers[0]
    assert mgr.diff_calls == [("/tmp/rollback-work", "abc12345")]
    assert mgr.restore_calls == [("/tmp/rollback-work", "abc12345")]
    assert resolved is not None
    assert "Restored to checkpoint abc12345" in resolved
    assert "pre-rollback snapshot" in resolved
