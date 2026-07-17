"""Test parsing progresso rclone."""

from services.file_replication.rclone_sync import (
    format_rclone_progress_summary,
    merge_rclone_progress,
    parse_rclone_progress,
    summarize_rclone_output,
)


def test_parse_stats_bytes_with_total():
    line = "Transferred:   	  22.443 GiB / 45.123 GiB, 49%, 12.345 MiB/s, ETA 15m30s"
    prog = parse_rclone_progress(line)
    assert prog is not None
    assert prog["transferred_human"] == "22.443 GiB"
    assert prog["transferred_total_human"] == "45.123 GiB"
    assert prog["percent"] == "49%"
    assert prog["speed"] == "12.345 MiB/s"
    assert prog["eta"] == "15m30s"


def test_parse_stats_one_line_bytes():
    line = "2026/07/17 18:43:15 INFO  :          27 B / 27 B, 100%, 0 B/s, ETA -"
    prog = parse_rclone_progress(line)
    assert prog is not None
    assert prog["transferred_human"] == "27 B"
    assert prog["transferred_total_human"] == "27 B"
    assert prog["percent"] == "100%"


def test_parse_stats_bytes_without_known_total():
    line = "Transferred:   	  512 MiB / ?, 0%, 0 B/s, ETA -"
    prog = parse_rclone_progress(line)
    assert prog is not None
    assert prog["transferred_human"] == "512 MiB"
    assert "transferred_total_human" not in prog
    assert "percent" not in prog


def test_parse_stats_files_with_k_suffix():
    line = "Transferred:            3.803k / 3.803k, 100%"
    prog = parse_rclone_progress(line)
    assert prog is not None
    assert prog["files_copied"] == 3803
    assert prog["files_total"] == 3803
    assert prog["percent"] == "100%"


def test_parse_checks():
    line = "Checks:                 5 / 5, 100%"
    prog = parse_rclone_progress(line)
    assert prog is not None
    assert prog["files_checked"] == 5
    assert prog["files_checked_total"] == 5


def test_parse_copied_file():
    line = "2026/07/17 17:29:32 INFO  : 13K0062CP.01 requirements.xlsx: Copied (new)"
    prog = parse_rclone_progress(line)
    assert prog is not None
    assert prog["files_copied_delta"] == 1
    assert "13K0062CP" in prog["last_file"]


def test_parse_skipped_mtime():
    line = "2026/07/17 18:43:15 INFO  : file1.txt: Updated modification time in destination"
    prog = parse_rclone_progress(line)
    assert prog is not None
    assert prog["files_skipped_delta"] == 1


def test_parse_nothing_to_transfer():
    line = "2026/07/17 18:43:07 INFO  : There was nothing to transfer"
    prog = parse_rclone_progress(line)
    assert prog is not None
    assert prog["nothing_to_transfer"] is True


def test_merge_progress_accumulates_files():
    state = {"files_copied": 10, "transferred_human": "1 GiB"}
    merged = merge_rclone_progress(state, {"files_copied_delta": 1, "last_file": "a.txt"})
    assert merged["files_copied"] == 11
    assert merged["files_done"] == 11
    assert merged["transferred_human"] == "1 GiB"


def test_summarize_mixed_output():
    lines = [
        "INFO  : file1.txt: Updated modification time in destination\n",
        "INFO  : file3.txt: Copied (new)\n",
        "Transferred:   	          2 B / 2 B, 100%, 0 B/s, ETA -\n",
        "Checks:                 5 / 5, 100%\n",
    ]
    summary = summarize_rclone_output(lines)
    assert summary["files_copied"] == 1
    assert summary["files_skipped"] == 1
    assert summary["files_checked_total"] == 5
    text = format_rclone_progress_summary(summary)
    assert "1 copiati" in text
    assert "1 saltati" in text
