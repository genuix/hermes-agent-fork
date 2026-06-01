"""Tests for CLI /snapshot restore/prune confirmation flows."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch


def _bound(fn, instance):
    return fn.__get__(instance, type(instance))


def _make_self(prompt_response):
    from cli import HermesCLI

    self_ = SimpleNamespace(
        _prompt_text_input_modal=lambda **kwargs: prompt_response,
    )
    self_._normalize_slash_confirm_choice = _bound(
        HermesCLI._normalize_slash_confirm_choice, self_
    )
    return self_


def test_snapshot_restore_prompts_with_preview_and_restores_on_confirm():
    from cli import HermesCLI

    snapshots = [
        {
            "id": "20260401-alpha",
            "label": "alpha",
            "file_count": 3,
            "total_size": 2048,
            "files": {
                "config.yaml": 42,
                "state.db": 1024,
                "logs/agent.log": 984,
            },
        },
        {
            "id": "20260331-older",
            "label": "older",
            "file_count": 1,
            "total_size": 100,
            "files": {"config.yaml": 100},
        },
    ]
    prompt_calls = []

    def _prompt_text_input_modal(**kwargs):
        prompt_calls.append(kwargs)
        return "1"

    self_ = SimpleNamespace(_prompt_text_input_modal=_prompt_text_input_modal)
    self_._normalize_slash_confirm_choice = _bound(
        HermesCLI._normalize_slash_confirm_choice, self_
    )

    with patch("hermes_cli.backup.list_quick_snapshots", return_value=snapshots), patch(
        "hermes_cli.backup.restore_quick_snapshot", return_value=True
    ) as restore_mock, patch("builtins.print") as print_mock:
        _bound(HermesCLI._handle_snapshot_command, self_)("/snapshot restore 1")

    restore_mock.assert_called_once_with("20260401-alpha")
    assert prompt_calls, "restore flow should prompt before mutating state"
    detail = prompt_calls[0]["detail"]
    assert "Snapshot label: alpha" in detail
    assert "Files in snapshot: 3" in detail
    assert "Preview files:" in detail
    assert "config.yaml" in detail
    assert "state.db" in detail
    assert "Restart recommended for state.db changes to take effect." in detail
    assert any(
        "Restored state from: 20260401-alpha" in str(call.args[0])
        for call in print_mock.call_args_list
        if call.args
    )


def test_snapshot_restore_cancel_aborts_without_restoring():
    from cli import HermesCLI

    snapshots = [
        {
            "id": "20260401-alpha",
            "label": "alpha",
            "file_count": 3,
            "total_size": 2048,
            "files": {"config.yaml": 42},
        }
    ]
    prompt_calls = []

    def _prompt_text_input_modal(**kwargs):
        prompt_calls.append(kwargs)
        return "2"

    self_ = SimpleNamespace(_prompt_text_input_modal=_prompt_text_input_modal)
    self_._normalize_slash_confirm_choice = _bound(
        HermesCLI._normalize_slash_confirm_choice, self_
    )

    with patch("hermes_cli.backup.list_quick_snapshots", return_value=snapshots), patch(
        "hermes_cli.backup.restore_quick_snapshot"
    ) as restore_mock, patch("builtins.print") as print_mock:
        _bound(HermesCLI._handle_snapshot_command, self_)("/snapshot restore 20260401-alpha")

    restore_mock.assert_not_called()
    assert prompt_calls, "restore flow should still prompt even on cancel"
    assert any(
        "Snapshot restore cancelled." in str(call.args[0])
        for call in print_mock.call_args_list
        if call.args
    )


def test_snapshot_prune_prompts_with_preview_and_prunes_on_confirm():
    from cli import HermesCLI

    snapshots = [
        {"id": "20260403-newest", "label": "newest", "file_count": 1, "total_size": 10, "files": {"a": 1}},
        {"id": "20260402-middle", "label": "middle", "file_count": 1, "total_size": 10, "files": {"b": 1}},
        {"id": "20260401-oldest", "label": "oldest", "file_count": 1, "total_size": 10, "files": {"c": 1}},
        {"id": "20260331-ancient", "label": "ancient", "file_count": 1, "total_size": 10, "files": {"d": 1}},
    ]
    prompt_calls = []

    def _prompt_text_input_modal(**kwargs):
        prompt_calls.append(kwargs)
        return "1"

    self_ = SimpleNamespace(_prompt_text_input_modal=_prompt_text_input_modal)
    self_._normalize_slash_confirm_choice = _bound(
        HermesCLI._normalize_slash_confirm_choice, self_
    )

    with patch("hermes_cli.backup.list_quick_snapshots", return_value=snapshots), patch(
        "hermes_cli.backup.prune_quick_snapshots", return_value=2
    ) as prune_mock, patch("builtins.print") as print_mock:
        _bound(HermesCLI._handle_snapshot_command, self_)("/snapshot prune 2")

    prune_mock.assert_called_once_with(keep=2)
    assert prompt_calls, "prune flow should prompt before deleting snapshots"
    detail = prompt_calls[0]["detail"]
    assert "delete 2 old snapshot(s)" in detail
    assert "keep the newest 2" in detail
    assert "20260401-oldest" in detail
    assert "20260331-ancient" in detail
    assert any(
        "Pruned 2 old snapshot(s) (keeping 2)." in str(call.args[0])
        for call in print_mock.call_args_list
        if call.args
    )
