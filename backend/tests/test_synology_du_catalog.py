"""Test catalogo du Synology per sottocartelle."""

from services.file_replication.file_replication_state import (
    resolve_work_folder,
    update_catalog_from_du_folders,
)
from services.file_replication.synology_du import is_excluded_folder_name


def test_is_excluded_folder_name():
    assert is_excluded_folder_name("#snapshot", [])
    assert is_excluded_folder_name("@eaDir", [])
    assert not is_excluded_folder_name("Alpha", [])
    assert is_excluded_folder_name("#Snapshot", [])


def test_update_catalog_from_du_folders():
    state = update_catalog_from_du_folders(
        {},
        "/Comune",
        {
            "folders": [
                {"path": "/Comune/A", "name": "A", "bytes": 1000},
                {"path": "/Comune/B", "name": "B", "bytes": 2000},
            ],
            "total_bytes": 3000,
            "excluded_names": ["#snapshot"],
        },
    )
    assert state["catalog"]["source_bytes"] == 3000
    assert len(state["per_path"]["/Comune"]["folders"]) == 2


def test_resolve_work_folder_from_last_file():
    state = update_catalog_from_du_folders(
        {},
        "/Comune",
        {
            "folders": [
                {"path": "/Comune/Alpha", "name": "Alpha", "bytes": 100},
                {"path": "/Comune/Beta", "name": "Beta", "bytes": 200},
            ],
            "total_bytes": 300,
            "excluded_names": [],
        },
    )
    work = resolve_work_folder(
        state,
        "/Comune",
        step_path="/Comune",
        last_file="Alpha/sub/file.txt",
    )
    assert work is not None
    assert work["name"] == "Alpha"
