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


def _format_bytes_human(n: int | None) -> str | None:
    if n is None or n < 0:
        return None
    value = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TiB"


def folder_progress_fields(
    state: dict,
    current_folder_path: str | None = None,
    *,
    step_percent: int | None = None,
    step_eta_seconds: int | None = None,
    activity: str | None = None,
) -> dict:
    """Campi UI: lista cartelle, indici, % complessivo ed ETA da catalogo du.

    ``activity``: ``ensure`` | ``root_loose`` | ``catalog`` | None (cartella o idle).
    """
    catalog = state.get("catalog") or {}
    if not catalog:
        return {}

    items: list[dict] = []
    done_bytes = 0
    current_folder_bytes = 0
    current_idx = None
    for root, cat in catalog.items():
        done = set((state.get("done") or {}).get(root) or [])
        for folder in cat.get("folders") or []:
            path = folder.get("path") or ""
            nbytes = int(folder.get("bytes") or 0)
            if activity == "catalog":
                status = "catalogued"
            elif path == current_folder_path:
                status = "in_progress"
                current_folder_bytes = nbytes
                current_idx = len(items) + 1
            elif path in done:
                status = "done"
                done_bytes += nbytes
            else:
                status = "pending"
            items.append({
                "path": path,
                "name": folder.get("name") or path.rsplit("/", 1)[-1],
                "bytes": nbytes,
                "size_human": _format_bytes_human(nbytes),
                "status": status,
                "root": root,
            })

    if not items:
        return {}

    roots = list(catalog.keys())
    done_count = sum(1 for it in items if it["status"] == "done")
    pending_count = sum(1 for it in items if it["status"] == "pending")
    total_bytes = sum(int(c.get("total_bytes") or 0) for c in catalog.values())
    out: dict = {
        "folder_catalog": items,
        "folders_done": done_count,
        "folders_pending": pending_count,
        "current_folder_total": len(items),
        "catalog_view_mode": "catalog" if activity == "catalog" else "sync",
        "catalog_roots": roots,
        "catalog_parent_path": roots[0] if len(roots) == 1 else None,
    }
    if activity == "ensure":
        out["folder_activity_label"] = "Preparazione path destinazione…"
    elif activity == "root_loose":
        out["folder_activity_label"] = "File sciolti a root (+ cartelle nuove)"
    elif activity == "catalog":
        parent = roots[0] if len(roots) == 1 else "sorgente"
        out["folder_activity_label"] = (
            f"Catalogo du sotto {parent}: {len(items)} cartelle di 1° livello"
        )
        out["folders_done"] = 0
        out["folders_pending"] = 0
    elif current_folder_path:
        name = current_folder_path.rsplit("/", 1)[-1]
        parent = current_folder_path.rsplit("/", 1)[0] if "/" in current_folder_path else ""
        out["current_folder_path"] = current_folder_path
        out["current_folder_name"] = name
        out["current_folder_parent"] = parent or None
        if current_idx is not None:
            out["current_folder_index"] = current_idx
        if current_folder_bytes:
            out["current_folder_size_human"] = _format_bytes_human(current_folder_bytes)
        size_bit = (
            f" (~{_format_bytes_human(current_folder_bytes)})"
            if current_folder_bytes
            else ""
        )
        idx_bit = f" ({current_idx}/{len(items)})" if current_idx is not None else ""
        # Path completo reale (non solo il leaf): es. /FTP_BACKUP/DITTE
        out["folder_activity_label"] = (
            f"In lavorazione: {current_folder_path}{idx_bit}{size_bit}"
        )

    if activity != "catalog" and total_bytes > 0:
        current_contrib = 0.0
        if current_folder_bytes and step_percent is not None:
            current_contrib = current_folder_bytes * max(0, min(100, int(step_percent))) / 100.0
        overall_done = done_bytes + current_contrib
        overall_pct = min(99, int(100 * overall_done / total_bytes)) if overall_done < total_bytes else 100
        out["percent"] = f"{overall_pct}%"
        out["progress_percent"] = out["percent"]
        out["transferred_total_human"] = _format_bytes_human(total_bytes)
        out["catalog_bytes_est"] = total_bytes

        remaining = max(0.0, total_bytes - overall_done)
        if step_eta_seconds and current_folder_bytes and step_percent is not None:
            step_remaining = current_folder_bytes * (100 - max(0, min(100, int(step_percent)))) / 100.0
            if step_remaining > 0 and step_eta_seconds > 0:
                rate = step_remaining / float(step_eta_seconds)
                if rate > 0:
                    out["eta_seconds_overall"] = int(remaining / rate)
    elif activity == "catalog" and total_bytes > 0:
        out["catalog_bytes_est"] = total_bytes
        out["transferred_total_human"] = _format_bytes_human(total_bytes)
    return out


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
