"""Test preset esclusioni."""

import pytest

from services.file_replication.exclude_presets import build_exclude_lines
from services.file_replication.path_utils import is_excluded_name, sanitize_path


def test_build_exclude_lines_merges_presets_and_custom():
    lines = build_exclude_lines(["nas_snapshots", "system_files"], ["*.bak"])
    assert "@Snapshot" in lines
    assert ".DS_Store" in lines
    assert "*.bak" in lines


def test_sanitize_path_rejects_traversal():
    with pytest.raises(ValueError):
        sanitize_path("/docs/../etc/passwd")


def test_is_excluded_name_snapshot():
    assert is_excluded_name("@Snapshot", ["nas_snapshots"]) is True
    assert is_excluded_name("documenti", ["nas_snapshots"]) is False
