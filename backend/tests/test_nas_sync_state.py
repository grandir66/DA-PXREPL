"""Test run_state nas_sync."""

from services.nas_sync.state import (
    catalog_summary,
    clear_pause,
    folder_progress_fields,
    get_pause,
    mark_folder_done,
    pending_folders,
    reset_run_progress,
    save_pause,
    set_du_catalog,
)

FOLDERS = [
    {"path": "/SHARE/a", "name": "a", "bytes": 100},
    {"path": "/SHARE/b", "name": "b", "bytes": 200},
]


def test_catalog_roundtrip_and_summary():
    state = set_du_catalog({}, "/SHARE", FOLDERS, 300, 42, "2026-07-20T10:00:00")
    summary = catalog_summary(state)
    assert summary["catalog_bytes_est"] == 300
    assert summary["catalog_files_est"] == 42
    assert summary["catalog_folder_count"] == 2
    assert summary["catalog_has_du"] is True
    assert summary["catalog_updated_at"] == "2026-07-20T10:00:00"


def test_summary_empty_state():
    summary = catalog_summary({})
    assert summary["catalog_has_du"] is False
    assert summary["catalog_bytes_est"] is None


def test_pending_and_mark_done():
    state = set_du_catalog({}, "/SHARE", FOLDERS, 300, None, "t")
    assert [f["path"] for f in pending_folders(state, "/SHARE")] == ["/SHARE/a", "/SHARE/b"]
    state = mark_folder_done(state, "/SHARE", "/SHARE/a")
    assert [f["path"] for f in pending_folders(state, "/SHARE")] == ["/SHARE/b"]


def test_reset_keeps_catalog_clears_done():
    state = set_du_catalog({}, "/SHARE", FOLDERS, 300, None, "t")
    state = mark_folder_done(state, "/SHARE", "/SHARE/a")
    state = reset_run_progress(state)
    assert len(pending_folders(state, "/SHARE")) == 2
    assert catalog_summary(state)["catalog_has_du"] is True


def test_pause_roundtrip():
    state = save_pause({}, "/SHARE", "/SHARE/b", "b/file.txt")
    pause = get_pause(state)
    assert pause == {"source_path": "/SHARE", "folder_path": "/SHARE/b", "last_file": "b/file.txt"}
    state = clear_pause(state)
    assert get_pause(state) is None


def test_folder_progress_fields_overall_percent_and_eta():
    state = set_du_catalog({}, "/SHARE", FOLDERS, 300, None, "t")
    state = mark_folder_done(state, "/SHARE", "/SHARE/a")
    fields = folder_progress_fields(
        state,
        "/SHARE/b",
        step_percent=50,
        step_eta_seconds=100,
    )
    assert fields["folders_done"] == 1
    assert fields["folders_pending"] == 0
    assert fields["current_folder_name"] == "b"
    assert fields["percent"] == "66%"  # (100 + 100) / 300
    assert fields["eta_seconds_overall"] == 100  # remaining 100 B at 1 B/s (step: 100 B / 100 s)
    assert len(fields["folder_catalog"]) == 2
    assert fields["folder_catalog"][0]["status"] == "done"
    assert fields["folder_catalog"][1]["status"] == "in_progress"
