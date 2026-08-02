"""Optional PostgreSQL FTS integration for the Hermes runtime candidate.

This module is intentionally lazy and disabled by default. It is a bridge to the
standalone migration project, not a second implementation of its storage layer.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


def _config() -> dict[str, Any]:
    try:
        import yaml
        from hermes_constants import get_hermes_home

        path = Path(get_hermes_home()) / "config.yaml"
        if not path.exists():
            return {}
        data = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        logger.debug("Unable to read Hermes config for PostgreSQL FTS", exc_info=True)
        return {}


def enabled() -> bool:
    """Return the explicit config gate; absent/malformed values mean disabled."""
    value = ((_config().get("memory") or {}).get("postgres_fts") or {}).get("enabled")
    return value is True


def build_post_commit_hook() -> Callable[[dict[str, Any]], None] | None:
    """Build a fail-open hook only when config and optional dependencies exist."""
    if not enabled():
        return None
    dsn = os.environ.get("HERMES_FTS_DATABASE_URL", "").strip()
    if not dsn:
        logger.warning("memory.postgres_fts.enabled is true but HERMES_FTS_DATABASE_URL is missing")
        return None
    try:
        import psycopg
        from hermes_fts.live_projection import FailOpenProjector, ProjectionJournal
        from hermes_fts.models import MessageRecord, SessionRecord
        from hermes_fts.postgres_store import PostgresStore
    except Exception:
        logger.warning("PostgreSQL FTS enabled but migration package is unavailable", exc_info=True)
        return None

    try:
        connection = psycopg.connect(dsn)
        store = PostgresStore(connection)
        from hermes_constants import get_hermes_home
        journal = ProjectionJournal(Path(get_hermes_home()) / "postgres-fts-projection.jsonl")
        projector = FailOpenProjector(store, journal)
    except Exception:
        logger.warning("PostgreSQL FTS enabled but connection failed; keeping runtime fail-open", exc_info=True)
        return None

    def hook(event: dict[str, Any]) -> None:
        try:
            if event.get("object_type") == "session":
                started = event.get("started_at") or time.time()
                record = SessionRecord(
                    session_id=str(event["session_id"]),
                    source=str(event.get("source") or "unknown"),
                    user_id=event.get("user_id"),
                    profile_name=event.get("profile_name"),
                    title=event.get("title"),
                    model=event.get("model"),
                    parent_session_id=event.get("parent_session_id"),
                    session_key=event.get("session_key"),
                    chat_id=event.get("chat_id"),
                    chat_type=event.get("chat_type"),
                    thread_id=event.get("thread_id"),
                    started_at=datetime.fromtimestamp(float(started), tz=timezone.utc),
                    ended_at=None,
                    archived=False,
                    pinned=False,
                    message_count=0,
                )
                projector.project_sessions([record], committed_at=time.time())
                return

            content = event.get("content")
            if not isinstance(content, (str, type(None))):
                content = json.dumps(content, ensure_ascii=False, default=str)
            timestamp = event.get("timestamp") or time.time()
            record = MessageRecord(
                message_id=int(event["message_id"]),
                session_id=str(event["session_id"]),
                role=str(event.get("role") or "unknown"),
                tool_name=event.get("tool_name"),
                content=content,
                message_timestamp=datetime.fromtimestamp(float(timestamp), tz=timezone.utc),
                active=bool(event.get("active", True)),
                compacted=bool(event.get("compacted", False)),
                observed=bool(event.get("observed", False)),
                searchable_content=content or "",
                source_hash=str(event.get("source_hash") or f"runtime-{event['message_id']}"),
            )
            projector.project_messages([record], committed_at=time.time())
        except Exception:
            logger.debug("PostgreSQL FTS post-commit event failed", exc_info=True)

    return hook
