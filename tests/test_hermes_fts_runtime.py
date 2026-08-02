import hermes_fts_runtime
from hermes_state import SessionDB


def test_postgres_fts_is_disabled_without_explicit_config(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    assert hermes_fts_runtime.enabled() is False
    assert hermes_fts_runtime.build_post_commit_hook() is None


def test_session_db_default_remains_safe_when_integration_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    db = SessionDB(db_path=tmp_path / "state.db")
    try:
        assert db._post_commit_hook is None
        db.create_session("s-disabled", source="cli")
        assert db.append_message("s-disabled", role="user", content="safe") == 1
    finally:
        db.close()
