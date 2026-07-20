"""Test engine rclone v2 (JSON log)."""

import json

from database import FileEndpoint, FileEndpointType
from services.nas_sync.engine_rclone import build_rclone_cmd, parse_rclone_json_line


def test_cmd_copy_mode_flags():
    cmd = build_rclone_cmd(
        "nas2_source:Share/docs", "nas2_dest:DATI/docs",
        delete_on_dest=False, size_only=False, bandwidth_limit_kb=None, filter_file=None,
    )
    assert cmd[0] == "rclone"
    assert cmd[1] == "copy"
    assert "--no-traverse" in cmd
    assert "--use-json-log" in cmd
    assert "--delete-after" not in cmd


def test_cmd_sync_mode_with_delete_and_bwlimit():
    cmd = build_rclone_cmd(
        "nas2_source:Share", "nas2_dest:DATI",
        delete_on_dest=True, size_only=True, bandwidth_limit_kb=2048, filter_file="/tmp/f.txt",
    )
    assert cmd[1] == "sync"
    assert "--delete-after" in cmd
    assert "--size-only" in cmd
    assert "--bwlimit" in cmd and "2048K" in cmd
    assert "--filter-from" in cmd and "/tmp/f.txt" in cmd


def test_parse_copied_new():
    line = json.dumps({"level": "info", "msg": "Copied (new)", "object": "docs/a.txt"})
    ev = parse_rclone_json_line(line)
    assert ev.files_new == 1
    assert ev.last_file == "docs/a.txt"


def test_parse_copied_replaced():
    line = json.dumps({"level": "info", "msg": "Copied (replaced existing)", "object": "b.txt"})
    ev = parse_rclone_json_line(line)
    assert ev.files_replaced == 1


def test_parse_unchanged_skipped():
    line = json.dumps({"level": "info", "msg": "Unchanged skipping", "object": "c.txt"})
    ev = parse_rclone_json_line(line)
    assert ev.files_skipped == 1


def test_parse_deleted():
    line = json.dumps({"level": "info", "msg": "Deleted", "object": "old.txt"})
    ev = parse_rclone_json_line(line)
    assert ev.files_deleted == 1


def test_parse_stats_block():
    line = json.dumps({
        "level": "info", "msg": "...",
        "stats": {"bytes": 1048576, "totalBytes": 4194304, "speed": 2097152.0,
                  "eta": 90, "transfers": 3, "totalTransfers": 12},
    })
    ev = parse_rclone_json_line(line)
    assert ev.bytes_done == 1048576
    assert ev.bytes_total == 4194304
    assert ev.percent == 25
    assert ev.eta_seconds == 90
    assert ev.speed == "2.0 MiB/s"


def test_parse_non_json_returns_none():
    assert parse_rclone_json_line("not json at all") is None
