"""Test eventi e vista progresso nas_sync."""

from services.nas_sync.events import SyncEvent, apply_event, build_view, human_bytes


def test_apply_event_accumulates_counters():
    p: dict = {}
    p = apply_event(p, SyncEvent(phase="copying", last_file="a.txt", files_new=1))
    p = apply_event(p, SyncEvent(phase="copying", last_file="b.txt", files_replaced=1))
    p = apply_event(p, SyncEvent(phase="copying", files_skipped=2))
    assert p["files_new"] == 1
    assert p["files_replaced"] == 1
    assert p["files_copied"] == 2
    assert p["files_done"] == 2
    assert p["files_skipped"] == 2
    assert p["last_file"] == "b.txt"


def test_apply_event_updates_bytes_and_speed():
    p = apply_event({}, SyncEvent(phase="copying", bytes_done=1048576, bytes_total=4194304,
                                  percent=25, speed="2.00MB/s", eta_seconds=90))
    assert p["bytes_done"] == 1048576
    assert p["percent"] == 25
    assert p["speed"] == "2.00MB/s"
    assert p["eta_seconds"] == 90


def test_build_view_copying_labels():
    p = {"phase": "copying", "files_new": 3, "files_replaced": 1, "files_copied": 4,
         "files_skipped": 10, "files_deleted": 0, "files_done": 4,
         "bytes_done": 1048576, "bytes_total": 4194304, "percent": 25,
         "speed": "2.00MB/s", "eta_seconds": 90, "last_file": "x.txt"}
    view = build_view(p)
    assert view["phase_label"] == "Copia file verso destinazione"
    assert any("3 nuovi" in line for line in view["detail_lines"])
    assert view["progress_percent"] == "25%"
    assert view["eta_human"] == "1 minuto e 30 secondi"
    assert view["transferred_human"] == "1.0 MiB"


def test_build_view_scanning():
    view = build_view({"phase": "scanning"})
    assert view["phase_label"] == "Scansione sorgente"


def test_human_bytes():
    assert human_bytes(0) == "0 B"
    assert human_bytes(1536) == "1.5 KiB"
    assert human_bytes(1073741824) == "1.0 GiB"
