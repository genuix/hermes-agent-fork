"""Tests for the Git author → GitHub handle map in scripts/release.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_release_module():
    spec = importlib.util.spec_from_file_location(
        "_release_under_test",
        Path(__file__).resolve().parents[2] / "scripts" / "release.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_root_hermes00_email_maps_to_genuix():
    module = _load_release_module()

    assert module.AUTHOR_MAP["root@hermes00.genuix.local"] == "genuix"
    assert module.resolve_author("root", "root@hermes00.genuix.local") == "@genuix"
