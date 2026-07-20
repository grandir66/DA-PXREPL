"""Test flag performance rclone replica file."""

from services.file_replication.rclone_sync import (
    RCLONE_SMB_MODIFY_WINDOW,
    build_rclone_performance_flags,
)


def test_performance_flags_copy_mode():
    flags = build_rclone_performance_flags(delete_on_dest=False, size_only=False)
    assert "--fast-list" in flags
    assert "--no-traverse" in flags
    assert "--size-only" not in flags


def test_performance_flags_sync_mode():
    flags = build_rclone_performance_flags(delete_on_dest=True, size_only=False)
    assert "--fast-list" in flags
    assert "--no-traverse" not in flags


def test_performance_flags_size_only():
    flags = build_rclone_performance_flags(delete_on_dest=False, size_only=True)
    assert "--size-only" in flags
    assert "--no-traverse" in flags


def test_modify_window_constant():
    assert RCLONE_SMB_MODIFY_WINDOW == "2s"
