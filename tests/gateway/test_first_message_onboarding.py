from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.config import GatewayConfig, Platform
from gateway.run import GatewayRunner
from gateway.session import SessionSource


@pytest.mark.asyncio
async def test_first_message_does_not_inject_onboarding_prompt(tmp_path, monkeypatch):
    """Regression: the first inbound message should not get a synthetic
    onboarding intro appended to the system prompt.

    The gateway used to append a note that told the model to introduce itself
    and mention /help on the user's very first message ever. That showed up in
    Discord after the last update and should stay gone.
    """
    runner = GatewayRunner(GatewayConfig(sessions_dir=tmp_path / "sessions"))

    session_entry = SimpleNamespace(
        session_key="discord:123",
        session_id="sid-1",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        was_auto_reset=False,
        is_fresh_reset=False,
    )

    session_store = MagicMock()
    session_store.get_or_create_session.return_value = session_entry
    session_store.has_any_sessions = MagicMock(side_effect=AssertionError("has_any_sessions() should not be consulted for first-turn onboarding"))
    session_store.append_to_transcript = MagicMock()
    session_store.update_session = MagicMock()
    session_store.clear_resume_pending = MagicMock()
    session_store.reset_session = MagicMock()
    session_store._save = MagicMock()
    runner.session_store = session_store

    runner._cache_session_source = MagicMock()
    runner._recover_telegram_topic_thread_id = MagicMock(return_value=None)
    runner._is_telegram_topic_lane = MagicMock(return_value=False)
    runner._set_session_env = MagicMock(return_value=[])
    runner._clear_restart_failure_count = MagicMock()
    runner._set_session_reasoning_override = MagicMock()
    runner._evict_cached_agent = MagicMock()
    runner._cleanup_agent_resources = MagicMock()
    runner._is_session_run_current = MagicMock(return_value=True)
    runner._should_send_voice_reply = MagicMock(return_value=False)
    runner._send_voice_reply = AsyncMock()
    runner._deliver_media_from_response = AsyncMock()
    runner._thread_metadata_for_source = MagicMock(return_value={})
    runner._reply_anchor_for_event = MagicMock(return_value=None)
    runner._format_session_info = MagicMock(return_value="")
    runner._sync_telegram_topic_binding = MagicMock()
    runner._session_model_overrides = {}
    runner._pending_model_notes = {}
    runner._session_db = None

    adapter = MagicMock()
    adapter.stop_typing = AsyncMock()
    adapter.send = AsyncMock()
    adapter.extract_media.return_value = ([], "ok")
    adapter.extract_images.return_value = ([], "ok")
    runner.adapters = {Platform.DISCORD: adapter}

    runner.hooks = MagicMock()
    runner.hooks.emit = AsyncMock()

    captured = {}

    async def fake_run_agent(**kwargs):
        captured.update(kwargs)
        return {
            "final_response": "ok",
            "messages": [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "ok"},
            ],
            "history_offset": 0,
            "last_prompt_tokens": 123,
            "tools": [],
            "already_sent": False,
            "failed": False,
        }

    runner._run_agent = fake_run_agent

    event = SimpleNamespace(
        text="hello",
        message_id="m-1",
        channel_prompt="",
        channel_context=None,
        media_urls=[],
        media_types=[],
        message_type=None,
        source=None,
    )
    source = SessionSource(
        platform=Platform.DISCORD,
        user_id="u-1",
        user_id_alt="",
        user_name="user",
        chat_id="c-1",
        chat_name="chat",
        chat_type="dm",
        thread_id="",
    )

    result = await runner._handle_message_with_agent(event, source, "quick", 1)

    assert result == "ok"
    assert "context_prompt" in captured
    assert "very first message ever" not in captured["context_prompt"]
    assert "/help shows available commands" not in captured["context_prompt"]
    session_store.has_any_sessions.assert_not_called()
