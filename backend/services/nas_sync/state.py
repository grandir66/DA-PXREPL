"""run_state del job v2: catalogo du, checkpoint per-cartella, pausa.

Struttura:
{
  "catalog": {"<root>": {"folders": [{"path","name","bytes"}...],
                          "total_bytes": int, "total_files": int|None,
                          "updated_at": iso}},
  "done": {"<root>": ["<folder_path>", ...]},
  "pause": {"source_path", "folder_path", "last_file"} | assente
}
"""

from __future__ import annotations

import copy

from sqlalchemy.orm.attributes import flag_modified


def get_run_state(job) -> dict:
    return copy.deepcopy(job.run_state or {})


def assign_run_state(job, state: dict) -> None:
    job.run_state = state
    flag_modified(job, "run_state")


def set_du_catalog(
    state: dict,
    root: str,
    folders: list[dict],
    total_bytes: int,
    total_files: int | None,
    at_iso: str,
) -> dict:
    s = copy.deepcopy(state)
    s.setdefault("catalog", {})[root] = {
        "folders": folders,
        "total_bytes": total_bytes,
        "total_files": total_files,
        "updated_at": at_iso,
    }
    return s


def catalog_summary(state: dict) -> dict:
    catalog = state.get("catalog") or {}
    if not catalog:
        return {
            "catalog_bytes_est": None,
            "catalog_files_est": None,
            "catalog_updated_at": None,
            "catalog_folder_count": None,
            "catalog_has_du": False,
        }
    total_bytes = sum(int(c.get("total_bytes") or 0) for c in catalog.values())
    files = [c.get("total_files") for c in catalog.values() if c.get("total_files")]
    folder_count = sum(len(c.get("folders") or []) for c in catalog.values())
    updated = max((c.get("updated_at") or "" for c in catalog.values()), default=None)
    return {
        "catalog_bytes_est": total_bytes,
        "catalog_files_est": sum(files) if files else None,
        "catalog_updated_at": updated or None,
        "catalog_folder_count": folder_count,
        "catalog_has_du": True,
    }


def pending_folders(state: dict, root: str) -> list[dict]:
    catalog = (state.get("catalog") or {}).get(root) or {}
    done = set((state.get("done") or {}).get(root) or [])
    return [f for f in (catalog.get("folders") or []) if f.get("path") not in done]


def mark_folder_done(state: dict, root: str, folder_path: str) -> dict:
    s = copy.deepcopy(state)
    done = s.setdefault("done", {}).setdefault(root, [])
    if folder_path not in done:
        done.append(folder_path)
    return s


def reset_run_progress(state: dict) -> dict:
    s = copy.deepcopy(state)
    s.pop("done", None)
    s.pop("pause", None)
    return s


def save_pause(state: dict, source_path: str, folder_path: str | None, last_file: str | None) -> dict:
    s = copy.deepcopy(state)
    s["pause"] = {
        "source_path": source_path,
        "folder_path": folder_path,
        "last_file": last_file,
    }
    return s


def get_pause(state: dict) -> dict | None:
    return state.get("pause") or None


def clear_pause(state: dict) -> dict:
    s = copy.deepcopy(state)
    s.pop("pause", None)
    return s
