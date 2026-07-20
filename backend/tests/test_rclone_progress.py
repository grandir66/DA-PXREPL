"""Test parsing progresso rclone."""

from services.file_replication.rclone_sync import (
    enrich_rclone_progress_view,
    format_rclone_eta,
    format_rclone_progress_summary,
    merge_rclone_progress,
    parse_rclone_progress,
    should_show_rclone_eta,
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
    assert prog["stat_files_transferred"] == 3803
    assert prog["stat_files_total"] == 3803
    assert prog["transfer_files_percent"] == "100%"


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
    assert prog["files_new_delta"] == 1
    assert "13K0062CP" in prog["last_file"]


def test_parse_copied_replaced():
    line = "2026/07/17 17:29:32 INFO  : doc.pdf: Copied (replaced)"
    prog = parse_rclone_progress(line)
    assert prog is not None
    assert prog["files_copied_delta"] == 1
    assert prog["files_replaced_delta"] == 1
    assert "files_new_delta" not in prog


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
    assert "copiati" in text.lower() or "Copia" in text


def test_scanning_phase_does_not_mark_checks_as_skipped():
    state = enrich_rclone_progress_view(
        merge_rclone_progress({}, {"files_checked": 50000, "files_checked_total": 100000, "phase": "scanning"})
    )
    assert state["files_skipped"] == 0
    assert state["phase"] == "scanning"
    assert "Scansione" in state["phase_label"]
    assert state.get("hint")


def test_enrich_copying_phase():
    view = enrich_rclone_progress_view({
        "files_copied": 12,
        "files_new": 8,
        "files_replaced": 4,
        "files_skipped": 400,
        "transferred_human": "1.2 GiB",
        "speed": "15 MiB/s",
        "phase": "copying",
    })
    assert view["phase"] == "copying"
    assert any("nuovi" in line.lower() or "aggiornati" in line.lower() for line in view["detail_lines"])


def test_parse_eta_with_weeks_and_days():
    line = "Transferred:   	  1.2 GiB / 120 GiB, 1%, 512 KiB/s, ETA 6w3d"
    prog = parse_rclone_progress(line)
    assert prog is not None
    assert prog["eta"] == "6w3d"
    assert format_rclone_eta(prog["eta"]) == "6 settimane e 3 giorni"


def test_format_eta_minutes_seconds():
    assert format_rclone_eta("15m30s") == "15 minuti e 30 secondi"


def test_enrich_eta_human_readable():
    view = enrich_rclone_progress_view({
        "phase": "copying",
        "transferred_human": "10 GiB",
        "transferred_total_human": "120 GiB",
        "percent": "49%",
        "speed": "15 MiB/s",
        "files_copied": 5000,
        "files_checked": 8000,
        "eta": "15m30s",
    })
    assert view["eta_human"] == "15 minuti e 30 secondi"
    assert any("15 minuti" in line for line in view["detail_lines"])


def test_hide_unreliable_eta_during_compare():
    state = {
        "phase": "copying",
        "transferred_human": "1.2 GiB",
        "transferred_total_human": "120 GiB",
        "percent": "1%",
        "speed": "512 KiB/s",
        "files_checked": 50000,
        "files_copied": 12,
        "files_skipped": 0,
        "eta": "6w3d",
    }
    assert should_show_rclone_eta(state) is False
    view = enrich_rclone_progress_view(state)
    assert not any("Tempo restante" in line for line in view["detail_lines"])
    assert view.get("eta_unreliable") is True
    assert "Confronto" in view["phase_label"] or view["phase"] == "scanning"


def test_bytes_progress_labels():
    view = enrich_rclone_progress_view({
        "phase": "copying",
        "source_size_human": "2.3 TB",
        "transferred_human": "4.362 GiB",
        "transferred_total_human": "36.628 GiB",
        "percent": "12%",
        "files_copied": 100,
    })
    assert any("du Synology" in line for line in view["detail_lines"])
    assert any("solo questo run" in line for line in view["detail_lines"])


def test_enrich_folder_progress_lines():
    view = enrich_rclone_progress_view({
        "phase": "copying",
        "source_size_human": "2.3 TB",
        "folder_activity_label": "In lavorazione: Alpha (3/12)",
        "current_folder_index": 3,
        "current_folder_total": 12,
        "current_folder_session_human": "4.2 GB",
        "current_folder_progress_pct": 5,
        "excluded_folder_names": ["#snapshot"],
        "files_copied": 10,
    })
    assert any("In lavorazione: Alpha" in line for line in view["detail_lines"])
    assert any("Avanzamento cartella" in line for line in view["detail_lines"])


def test_copy_phase_hides_stale_checked():
    view = enrich_rclone_progress_view({
        "phase": "copying",
        "files_checked": 5000,
        "files_copied": 8000,
        "files_skipped": 200,
        "transferred_human": "1 GiB",
        "percent": "20%",
    })
    assert not any("controllati" in line.lower() for line in view["detail_lines"])
    assert any("File elaborati:" in line for line in view["detail_lines"])
    assert view.get("hint")
