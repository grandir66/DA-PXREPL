"""Test stato persistente replica file (catalogo + checkpoint pausa)."""

from services.file_replication.file_replication_state import (
    apply_resume_to_sync_plan,
    catalog_summary,
    clear_resume,
    compose_live_progress,
    expand_rclone_steps_by_catalog,
    folder_checkpoint,
    folder_progress_to_fields,
    has_du_catalog,
    mark_all_folders_done,
    mark_folder_step_complete,
    mark_folder_step_started,
    save_pause_checkpoint,
    update_catalog_from_du_folders,
    update_catalog_from_progress,
    update_folder_work_progress,
)


def test_folder_checkpoint_from_last_file():
    assert folder_checkpoint("/Comune/foo/bar.txt", "/Comune") == "/Comune/foo"
    assert folder_checkpoint("sub/file.dat", "/Duerre") == "/Duerre/sub"


def test_update_catalog_keeps_maxima():
    state = {}
    state = update_catalog_from_progress(
        state,
        {"files_checked_total": 100, "transferred_human": "1.5 GiB"},
        "/Comune",
    )
    state = update_catalog_from_progress(
        state,
        {"files_checked_total": 80, "transferred_human": "500 MiB"},
        "/Comune",
    )
    assert state["catalog"]["files_est"] == 100
    assert state["per_path"]["/Comune"]["files_est"] == 100


def test_save_pause_checkpoint():
    state = save_pause_checkpoint(
        {},
        step_index=1,
        source_path="/Comune",
        last_file="/Comune/Alpha/file.txt",
        progress={"files_checked_total": 42},
    )
    assert state["resume"]["step_index"] == 1
    assert state["resume"]["resume_from_path"] == "/Comune/Alpha"
    assert state["catalog"]["files_est"] == 42


def test_apply_resume_skips_completed_steps():
    plan = [
        {"type": "rclone_sync", "src_path": "/Comune", "dest_dir": "/share/DATI/Comune"},
        {"type": "rclone_sync", "src_path": "/Duerre", "dest_dir": "/share/DATI/Duerre"},
    ]
    state = {
        "resume": {
            "step_index": 1,
            "source_path": "/Duerre",
            "resume_from_path": "/Duerre/2024",
        }
    }
    out, note = apply_resume_to_sync_plan(plan, state, "/share/DATI")
    assert len(out) == 1
    assert out[0]["src_path"] == "/Duerre/2024"
    assert out[0]["plan_index"] == 1
    assert note == "Ripresa da /Duerre/2024"


def test_clear_resume_preserves_catalog():
    state = save_pause_checkpoint(
        {},
        step_index=0,
        source_path="/Comune",
        last_file="/Comune/x/y",
        progress={"files_checked_total": 10},
    )
    cleared = clear_resume(state)
    assert "resume" not in cleared
    assert cleared["catalog"]["files_est"] == 10


def test_catalog_summary():
    state = save_pause_checkpoint(
        {},
        step_index=0,
        source_path="/Comune",
        last_file="/Comune/a/b.txt",
        progress={"files_checked_total": 5, "transferred_human": "10 MiB"},
    )
    summary = catalog_summary(state)
    assert summary["catalog_files_est"] == 5
    assert summary["resume_from_path"] == "/Comune/a"
    assert summary["resume_source_path"] == "/Comune"


def test_has_du_catalog():
    state = update_catalog_from_du_folders(
        {},
        "/Comune",
        {"total_bytes": 100, "folders": [{"path": "/Comune/A", "name": "A", "bytes": 100}]},
    )
    assert has_du_catalog(state, ["/Comune"])
    assert not has_du_catalog(state, ["/Comune", "/Duerre"])


def test_folder_progress_marks_done_and_current():
    state = update_catalog_from_du_folders(
        {},
        "/Comune",
        {
            "total_bytes": 300,
            "folders": [
                {"path": "/Comune/A", "name": "A", "bytes": 100},
                {"path": "/Comune/B", "name": "B", "bytes": 100},
                {"path": "/Comune/C", "name": "C", "bytes": 100},
            ],
        },
    )
    state, _ = update_folder_work_progress(
        state,
        "/Comune",
        step_path="/Comune",
        last_file="A/sub/file.txt",
        progress={"phase": "copying"},
        file_event="copied",
    )
    state, _ = update_folder_work_progress(
        state,
        "/Comune",
        step_path="/Comune",
        last_file="B/sub/file2.txt",
        progress={"phase": "copying"},
        file_event="copied",
    )
    fields = folder_progress_to_fields(state, "/Comune", step_path="/Comune")
    assert fields["current_folder_name"] == "B"
    assert fields["current_folder_index"] == 2
    assert fields["folders_done"] == 1
    assert fields["folders_pending"] == 1
    statuses = [f["status"] for f in fields["folder_catalog"]]
    assert statuses == ["done", "in_progress", "pending"]


def test_folder_alternate_skip_does_not_cycle():
    """Cartelle già su QNAP: alternanza last_file non riapre cartelle chiuse."""
    state = update_catalog_from_du_folders(
        {},
        "/share",
        {
            "total_bytes": 200,
            "folders": [
                {"path": "/share/Cartelle_scambio", "name": "Cartelle_scambio", "bytes": 100},
                {"path": "/share/Installazione", "name": "Installazione", "bytes": 100},
            ],
        },
    )
    events = [
        ("Cartelle_scambio/f1", "skipped"),
        ("Installazione/f2", "skipped"),
        ("Cartelle_scambio/f3", "skipped"),
        ("Installazione/f4", "skipped"),
        ("Cartelle_scambio/f5", "skipped"),
    ]
    for rel, ev in events:
        state, _ = update_folder_work_progress(
            state,
            "/share",
            step_path="/share",
            last_file=rel,
            progress={"phase": "copying"},
            file_event=ev,
        )
    fields = folder_progress_to_fields(state, "/share", step_path="/share")
    statuses = [f["status"] for f in fields["folder_catalog"]]
    assert statuses.count("in_progress") <= 1
    assert statuses.count("done") + statuses.count("skipped") >= 1
    # dopo alternanza, almeno una chiusa come skipped (solo saltati)
    assert any(f["status"] == "skipped" for f in fields["folder_catalog"])
    # rientrando in Cartelle_scambio non torna in_progress
    state, _ = update_folder_work_progress(
        state,
        "/share",
        step_path="/share",
        last_file="Cartelle_scambio/f6",
        progress={"phase": "copying"},
        file_event="skipped",
    )
    fields2 = folder_progress_to_fields(state, "/share", step_path="/share")
    cs = next(f for f in fields2["folder_catalog"] if f["name"] == "Cartelle_scambio")
    assert cs["status"] in ("done", "skipped")
    assert cs["status"] != "in_progress"


def test_mark_all_folders_done():
    state = update_catalog_from_du_folders(
        {},
        "/Comune",
        {
            "total_bytes": 100,
            "folders": [{"path": "/Comune/A", "name": "A", "bytes": 100}],
        },
    )
    state, _ = update_folder_work_progress(
        state,
        "/Comune",
        step_path="/Comune",
        last_file="A/x",
        progress={"phase": "copying"},
        file_event="copied",
    )
    state = mark_all_folders_done(state, "/Comune")
    fields = folder_progress_to_fields(state, "/Comune", step_path="/Comune")
    assert fields["folders_done"] == 1
    assert fields["folder_catalog"][0]["status"] == "done"


def test_show_last_file_suppressed_when_folder_done():
    state = update_catalog_from_du_folders(
        {},
        "/share",
        {
            "total_bytes": 200,
            "folders": [
                {"path": "/share/DoneFolder", "name": "DoneFolder", "bytes": 100},
                {"path": "/share/Next", "name": "Next", "bytes": 100},
            ],
        },
    )
    state, _ = update_folder_work_progress(
        state,
        "/share",
        step_path="/share",
        last_file="DoneFolder/a.txt",
        progress={"phase": "copying", "files_copied_delta": 1},
        file_event="copied",
    )
    state = mark_all_folders_done(state, "/share")
    fields = folder_progress_to_fields(
        state,
        "/share",
        step_path="/share",
        last_file="DoneFolder/b.txt",
    )
    assert fields["show_last_file"] is False
    assert "Confronto residuo" in fields["folder_activity_label"]
    assert "current_folder_name" not in fields


def test_compose_live_progress_strips_stale_folder_fields():
    merged = compose_live_progress(
        {
            "files_copied": 100,
            "current_folder_name": "Stale",
            "current_folder_index": 2,
            "last_file": "Stale/x.txt",
        },
        {
            "folder_activity_label": "Confronto residuo in Stale (cartella già allineata — 2/5 completate)",
            "show_last_file": False,
            "folder_catalog": [],
        },
        status="running",
    )
    assert "current_folder_name" not in merged
    assert merged.get("last_file") is None
    assert any("Confronto residuo" in line for line in merged["detail_lines"])


def test_expand_rclone_skips_aligned_folders():
    state = update_catalog_from_du_folders(
        {},
        "/Comune",
        {
            "total_bytes": 300,
            "folders": [
                {"path": "/Comune/Cartelle_scambio", "name": "Cartelle_scambio", "bytes": 100, "status": "done"},
                {"path": "/Comune/Installazione", "name": "Installazione", "bytes": 100, "status": "skipped"},
                {"path": "/Comune/Nuova", "name": "Nuova", "bytes": 100, "status": "pending"},
            ],
        },
    )
    plan = [
        {"type": "rclone_sync", "src_path": "/Comune", "dest_dir": "/share/DATI/Comune/"},
    ]
    expanded, skipped = expand_rclone_steps_by_catalog(plan, state, "/share/DATI")
    assert skipped == 2
    assert len(expanded) == 1
    assert expanded[0]["src_path"] == "/Comune/Nuova"
    assert expanded[0]["catalog_folder_path"] == "/Comune/Nuova"


def test_mark_folder_step_lifecycle():
    state = update_catalog_from_du_folders(
        {},
        "/Comune",
        {
            "total_bytes": 100,
            "folders": [{"path": "/Comune/Alpha", "name": "Alpha", "bytes": 100}],
        },
    )
    state = mark_folder_step_started(state, "/Comune", "/Comune/Alpha")
    fields = folder_progress_to_fields(state, "/Comune", step_path="/Comune/Alpha")
    assert fields["current_folder_name"] == "Alpha"
    state = mark_folder_step_complete(state, "/Comune", "/Comune/Alpha")
    fields2 = folder_progress_to_fields(state, "/Comune", step_path="/Comune/Alpha")
    assert fields2["folder_catalog"][0]["status"] == "done"
