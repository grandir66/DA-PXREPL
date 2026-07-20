"""Stato persistente job replica file: catalogo stimato e checkpoint ripresa."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, Optional

from services.file_replication.path_utils import (
    is_path_ancestor,
    sanitize_path,
    synology_to_qnap_dest_path,
)
from services.size_utils import format_bytes_human, parse_transfer_size_to_bytes


def get_run_state(job) -> dict[str, Any]:
    raw = getattr(job, "run_state", None)
    return deepcopy(raw) if isinstance(raw, dict) else {}


def assign_run_state(job, state: dict[str, Any]) -> None:
    job.run_state = deepcopy(state)


def clear_resume(state: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(state)
    out.pop("resume", None)
    return out


def _max_int(*values: Any) -> int:
    nums = [int(v) for v in values if v is not None]
    return max(nums) if nums else 0


def folder_checkpoint(last_file: str, step_src_path: str) -> str:
    """Da ultimo file rclone → path cartella sorgente da cui riprendere."""
    step = sanitize_path(step_src_path)
    lf = (last_file or "").strip().replace("\\", "/")
    if not lf:
        return step
    if lf.startswith("/"):
        parts = [p for p in lf.split("/") if p]
        if len(parts) <= 1:
            return step
        return sanitize_path("/" + "/".join(parts[:-1]))
    if "/" not in lf:
        return step
    sub = lf.rsplit("/", 1)[0]
    return sanitize_path(f"{step.rstrip('/')}/{sub}")


def update_catalog_from_progress(
    state: dict[str, Any],
    progress: dict[str, Any],
    source_path: str,
) -> dict[str, Any]:
    """Aggiorna stime file/byte (massimi osservati — non devono essere exact)."""
    out = deepcopy(state)
    catalog = dict(out.get("catalog") or {})
    per_path = dict(out.get("per_path") or {})
    src = sanitize_path(source_path)

    files_seen = _max_int(
        progress.get("files_checked_total"),
        progress.get("files_checked"),
        progress.get("stat_files_total"),
        (progress.get("files_copied") or 0) + (progress.get("files_skipped") or 0),
    )
    # NON usare transferred_total_human: in copy mode è spesso solo il delta del run
    # (es. 36 GiB), non la dimensione reale della share (es. 2.5 TB).
    session_bytes = 0
    if progress.get("transferred_human"):
        session_bytes = parse_transfer_size_to_bytes(progress["transferred_human"])

    path_entry = dict(per_path.get(src) or {})
    if files_seen:
        path_entry["files_est"] = max(int(path_entry.get("files_est") or 0), files_seen)
    if session_bytes:
        path_entry["session_bytes_max"] = max(
            int(path_entry.get("session_bytes_max") or 0),
            session_bytes,
        )
    if path_entry:
        path_entry["updated_at"] = datetime.utcnow().isoformat()
        per_path[src] = path_entry

    total_files = _max_int(
        catalog.get("files_est"),
        catalog.get("source_objects"),
        files_seen,
        sum(int(p.get("source_objects") or p.get("files_est") or 0) for p in per_path.values()),
    )
    total_bytes = _max_int(
        catalog.get("bytes_est"),
        catalog.get("source_bytes"),
        sum(int(p.get("source_bytes") or 0) for p in per_path.values()),
    )
    if total_files:
        catalog["files_est"] = total_files
    if total_bytes:
        catalog["bytes_est"] = total_bytes
    if total_files or total_bytes:
        catalog["updated_at"] = datetime.utcnow().isoformat()

    out["catalog"] = catalog
    out["per_path"] = per_path
    return out


def save_pause_checkpoint(
    state: dict[str, Any],
    *,
    step_index: int,
    source_path: str,
    last_file: Optional[str],
    progress: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    out = deepcopy(state)
    resume_from = folder_checkpoint(last_file or "", source_path)
    out["resume"] = {
        "step_index": int(step_index),
        "source_path": sanitize_path(source_path),
        "resume_from_path": resume_from,
        "last_file": (last_file or "").strip() or None,
        "paused_at": datetime.utcnow().isoformat(),
    }
    if progress:
        out = update_catalog_from_progress(out, progress, source_path)
    return out


def expand_rclone_steps_by_catalog(
    plan: list[dict],
    state: dict[str, Any],
    dest_staging_path: str,
) -> tuple[list[dict], int]:
    """Spezza step rclone monolitici in un job per cartella du (1° livello).

    Le cartelle ``done`` / ``skipped`` non generano step — rclone non le riverifica.
    Ritorna ``(piano, numero_cartelle_saltate)``.
    """
    out: list[dict] = []
    skipped = 0
    per_path = (state or {}).get("per_path") or {}

    for i, step in enumerate(plan):
        if step.get("type") != "rclone_sync":
            out.append({**step, "plan_index": i})
            continue

        root = sanitize_path(step["src_path"])
        folders = list((per_path.get(root) or {}).get("folders") or [])
        if not folders:
            out.append({**step, "plan_index": i, "original_src_path": root})
            continue

        for folder in folders:
            fp = sanitize_path(folder["path"])
            status = folder.get("status") or "pending"
            if status in ("done", "skipped"):
                skipped += 1
                continue
            out.append({
                **step,
                "type": "rclone_sync",
                "src_path": fp,
                "dest_dir": synology_to_qnap_dest_path(fp, dest_staging_path),
                "original_src_path": root,
                "catalog_folder_path": fp,
                "plan_index": i,
            })

    return out, skipped


def _folder_step_should_run(
    folder_path: str,
    resume_path: str,
    catalog_root: str,
    folders: list[dict[str, Any]],
) -> bool:
    """True se lo step cartella va eseguito rispetto al checkpoint di ripresa."""
    fp = sanitize_path(folder_path)
    rp = sanitize_path(resume_path)
    resume_folder = immediate_child_under(catalog_root, rp)
    paths = [sanitize_path(f["path"]) for f in folders]
    try:
        resume_idx = paths.index(resume_folder)
        folder_idx = paths.index(fp)
    except ValueError:
        return True
    return folder_idx >= resume_idx


def apply_resume_to_sync_plan(
    plan: list[dict],
    state: dict[str, Any],
    dest_staging_path: str,
) -> tuple[list[dict], Optional[str]]:
    """Salta step completati; restringe lo step corrente alla cartella checkpoint."""
    resume = (state or {}).get("resume")
    if not resume or resume.get("step_index") is None:
        return plan, None

    step_index = int(resume["step_index"])
    resume_path = (
        sanitize_path(str(resume["resume_from_path"]))
        if resume.get("resume_from_path")
        else None
    )
    out: list[dict] = []
    note: Optional[str] = None

    for i, step in enumerate(plan):
        pi = int(step.get("plan_index", i))
        if pi < step_index:
            continue

        item = dict(step)
        item.setdefault(
            "original_src_path",
            sanitize_path(item.get("original_src_path") or item["src_path"]),
        )

        if item.get("catalog_folder_path") and resume_path and pi == step_index:
            root = item["original_src_path"]
            folders = list(((state.get("per_path") or {}).get(root) or {}).get("folders") or [])
            if not _folder_step_should_run(
                str(item["catalog_folder_path"]),
                resume_path,
                root,
                folders,
            ):
                continue

        if pi == step_index and resume_path and item.get("type") == "rclone_sync":
            fp = sanitize_path(item.get("catalog_folder_path") or item["src_path"])
            if (
                is_path_ancestor(fp, resume_path)
                or fp == resume_path
                or is_path_ancestor(resume_path, fp)
            ):
                item["src_path"] = resume_path
                item["dest_dir"] = synology_to_qnap_dest_path(resume_path, dest_staging_path)
                item["resumed_from"] = resume_path
                note = f"Ripresa da {resume_path}"

        out.append(item)

    if not out:
        return plan, None
    return out, note


def update_catalog_from_source_size(
    state: dict[str, Any],
    source_path: str,
    *,
    bytes_val: int,
    objects: int = 0,
) -> dict[str, Any]:
    """Dimensione reale path sorgente (es. da ``du`` SSH su Synology)."""
    out = deepcopy(state)
    catalog = dict(out.get("catalog") or {})
    per_path = dict(out.get("per_path") or {})
    src = sanitize_path(source_path)
    path_entry = dict(per_path.get(src) or {})
    if bytes_val > 0:
        path_entry["source_bytes"] = int(bytes_val)
    if objects > 0:
        path_entry["source_objects"] = int(objects)
    if path_entry:
        path_entry["source_sized_at"] = datetime.utcnow().isoformat()
        per_path[src] = path_entry

    source_bytes = sum(int(p.get("source_bytes") or 0) for p in per_path.values())
    source_objects = sum(int(p.get("source_objects") or 0) for p in per_path.values())
    if source_bytes:
        catalog["source_bytes"] = source_bytes
        catalog["bytes_est"] = source_bytes
    if source_objects:
        catalog["source_objects"] = source_objects
        catalog["files_est"] = max(int(catalog.get("files_est") or 0), source_objects)
    catalog["updated_at"] = datetime.utcnow().isoformat()
    out["catalog"] = catalog
    out["per_path"] = per_path
    return out


# Alias retrocompatibilità
update_catalog_from_rclone_size = update_catalog_from_source_size


def immediate_child_under(root: str, path: str) -> str:
    """Prima sottocartella di ``root`` che contiene ``path`` (o ``root`` stesso)."""
    root_s = sanitize_path(root).rstrip("/")
    path_s = sanitize_path(path).rstrip("/")
    if path_s == root_s or not path_s.startswith(root_s + "/"):
        return root_s
    rest = path_s[len(root_s) + 1 :]
    first = rest.split("/")[0]
    return f"{root_s}/{first}"


def update_catalog_from_du_folders(
    state: dict[str, Any],
    source_path: str,
    du_catalog: dict[str, Any],
) -> dict[str, Any]:
    """Catalogo per sottocartelle da ``synology_du_folder_catalog``."""
    out = deepcopy(state)
    catalog = dict(out.get("catalog") or {})
    per_path = dict(out.get("per_path") or {})
    src = sanitize_path(source_path)
    folders = []
    for item in du_catalog.get("folders") or []:
        folders.append({
            "path": sanitize_path(item["path"]),
            "name": item.get("name") or item["path"].split("/")[-1],
            "bytes": int(item.get("bytes") or 0),
            "session_bytes": 0,
            "files_copied": 0,
            "files_skipped": 0,
            "status": "pending",
        })
    total_bytes = int(du_catalog.get("total_bytes") or 0)
    path_entry = {
        "source_bytes": total_bytes,
        "folders": folders,
        "excluded_names": list(du_catalog.get("excluded_names") or []),
        "source_sized_at": datetime.utcnow().isoformat(),
    }
    per_path[src] = path_entry
    catalog["source_bytes"] = sum(
        int(p.get("source_bytes") or 0) for p in per_path.values()
    )
    catalog["bytes_est"] = catalog["source_bytes"]
    catalog["folder_count"] = sum(len(p.get("folders") or []) for p in per_path.values())
    catalog["updated_at"] = datetime.utcnow().isoformat()
    out["catalog"] = catalog
    out["per_path"] = per_path
    return out


def _folder_display_status(stored: str) -> str:
    """Stato UI = stato persistito (niente ricalcolo da last_file)."""
    if stored in ("done", "in_progress", "pending", "skipped"):
        return stored
    return "pending"


def _finalize_folder_on_leave(folder: dict[str, Any]) -> dict[str, Any]:
    """Chiude una cartella quando rclone passa ad un'altra."""
    out = dict(folder)
    copied = int(out.get("folder_files_copied") or 0)
    skipped = int(out.get("folder_files_skipped") or 0)
    if copied == 0 and skipped > 0:
        out["status"] = "skipped"
    else:
        out["status"] = "done"
    return out


def _find_folder_index(folders: list[dict], path: str) -> Optional[int]:
    target = sanitize_path(path)
    for i, f in enumerate(folders):
        if sanitize_path(f["path"]) == target:
            return i
    return None


def mark_all_folders_done(state: dict[str, Any], source_root: str) -> dict[str, Any]:
    """Segna tutte le cartelle del catalogo come completate (fine step rclone monolitico)."""
    out = deepcopy(state)
    src = sanitize_path(source_root)
    per_path = dict(out.get("per_path") or {})
    entry = dict(per_path.get(src) or {})
    folders = []
    for f in entry.get("folders") or []:
        folders.append(_finalize_folder_on_leave(dict(f)))
    if folders:
        entry["folders"] = folders
        entry.pop("current_folder_path", None)
        entry.pop("last_touch_folder_path", None)
        entry.pop("folder_high_water", None)
        per_path[src] = entry
        out["per_path"] = per_path
    return out


def resolve_work_folder(
    state: dict[str, Any],
    source_root: str,
    *,
    step_path: str,
    last_file: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Cartella di **primo livello** sotto ``source_root`` in cui sta lavorando rclone."""
    src = sanitize_path(source_root)
    per_path = (state or {}).get("per_path") or {}
    folders = list((per_path.get(src) or {}).get("folders") or [])
    if not folders:
        return None

    ref_path = sanitize_path(step_path)
    if last_file:
        lf = last_file.strip().replace("\\", "/")
        if lf.startswith("/"):
            ref_path = sanitize_path(lf)
        else:
            ref_path = sanitize_path(f"{src.rstrip('/')}/{lf}")

    work = immediate_child_under(src, ref_path)
    for folder in folders:
        if sanitize_path(folder["path"]) == work:
            return dict(folder)
    return None


def _folder_file_event(progress: dict[str, Any]) -> Optional[str]:
    """Tipo ultimo evento file (solo delta riga corrente, se presente)."""
    if progress.get("files_copied_delta"):
        return "copied"
    if progress.get("files_skipped_delta"):
        return "skipped"
    if progress.get("files_deleted_delta"):
        return "deleted"
    return None


def update_folder_work_progress(
    state: dict[str, Any],
    source_root: str,
    *,
    step_path: str,
    last_file: Optional[str],
    progress: dict[str, Any],
    file_event: Optional[str] = None,
) -> tuple[dict[str, Any], Optional[dict[str, Any]]]:
    """Aggiorna stato cartelle al passaggio file rclone (monotono, no cicli).

    - ``done`` / ``skipped`` non tornano mai ``in_progress`` (rclone riverifica file già allineati).
    - Si passa ad altra cartella → la precedente ``in_progress`` diventa ``done`` o ``skipped``.
    - ``skipped``: nessun file copiato, solo saltati (già su QNAP).
    """
    out = deepcopy(state)
    src = sanitize_path(source_root)
    per_path = dict(out.get("per_path") or {})
    entry = dict(per_path.get(src) or {})
    folders = [dict(f) for f in (entry.get("folders") or [])]
    if not folders or not last_file:
        return out, None

    if progress.get("phase") == "scanning":
        return out, None

    work = resolve_work_folder(out, src, step_path=step_path, last_file=last_file)
    if not work:
        return out, None
    work_path = sanitize_path(work["path"])
    event = file_event or _folder_file_event(progress)

    prev_touch = entry.get("last_touch_folder_path")
    if prev_touch and sanitize_path(str(prev_touch)) != work_path:
        prev_idx = _find_folder_index(folders, str(prev_touch))
        if prev_idx is not None and folders[prev_idx].get("status") == "in_progress":
            folders[prev_idx] = _finalize_folder_on_leave(folders[prev_idx])

    current: Optional[dict[str, Any]] = None
    work_idx = _find_folder_index(folders, work_path)
    if work_idx is not None:
        folder = folders[work_idx]
        stored = folder.get("status") or "pending"
        if stored not in ("done", "skipped"):
            folder["status"] = "in_progress"
            if event == "copied":
                folder["folder_files_copied"] = int(folder.get("folder_files_copied") or 0) + 1
            elif event == "skipped":
                folder["folder_files_skipped"] = int(folder.get("folder_files_skipped") or 0) + 1
            folders[work_idx] = folder
            current = folder
        else:
            folders[work_idx] = folder

    entry["last_touch_folder_path"] = work_path
    entry["folders"] = folders
    if current:
        entry["current_folder_path"] = work_path
    per_path[src] = entry
    out["per_path"] = per_path
    return out, current


def _folder_catalog_item(f: dict[str, Any]) -> dict[str, Any]:
    status = _folder_display_status(f.get("status") or "pending")
    f_bytes = int(f.get("bytes") or 0)
    item: dict[str, Any] = {
        "path": f["path"],
        "name": f.get("name"),
        "bytes": f_bytes,
        "size_human": format_bytes_human(f_bytes),
        "status": status,
    }
    skipped_n = int(f.get("folder_files_skipped") or 0)
    copied_n = int(f.get("folder_files_copied") or 0)
    if status == "skipped":
        item["status_hint"] = "già su QNAP"
        if skipped_n:
            item["files_skipped"] = skipped_n
    elif status == "done" and copied_n == 0 and skipped_n > 0:
        item["status"] = "skipped"
        item["status_hint"] = "già su QNAP"
        item["files_skipped"] = skipped_n
    elif status == "in_progress":
        if copied_n or skipped_n:
            parts = []
            if copied_n:
                parts.append(f"{copied_n} copiati")
            if skipped_n:
                parts.append(f"{skipped_n} saltati")
            item["status_hint"] = ", ".join(parts)
    return item


def folder_progress_to_fields(
    state: dict[str, Any],
    source_root: str,
    *,
    step_path: str,
    last_file: Optional[str] = None,
) -> dict[str, Any]:
    """Campi UI — legge solo stato persistito, mai last_file per gli status."""
    src = sanitize_path(source_root)
    per_path = (state or {}).get("per_path") or {}
    entry = per_path.get(src) or {}
    folders = list(entry.get("folders") or [])
    if not folders:
        return {}

    catalog_items = [_folder_catalog_item(f) for f in folders]
    active_idx = next(
        (i for i, f in enumerate(folders) if (f.get("status") or "pending") == "in_progress"),
        None,
    )
    done_count = sum(1 for it in catalog_items if it["status"] in ("done", "skipped"))
    pending_count = sum(1 for it in catalog_items if it["status"] == "pending")

    out: dict[str, Any] = {
        "current_folder_total": len(folders),
        "folders_done": done_count,
        "folders_pending": pending_count,
        "folder_catalog": catalog_items,
    }

    show_last_file = False
    folder_activity_label: str | None = None

    if active_idx is not None:
        current = folders[active_idx]
        citem = catalog_items[active_idx]
        work_path = sanitize_path(current["path"])
        name = current.get("name") or work_path.split("/")[-1]
        out.update({
            "current_folder_path": work_path,
            "current_folder_name": name,
            "current_folder_index": active_idx + 1,
            "current_folder_bytes": int(current.get("bytes") or 0),
        })
        size_h = None
        if current.get("bytes"):
            size_h = format_bytes_human(int(current["bytes"]))
            out["current_folder_size_human"] = size_h
        if citem.get("status_hint"):
            out["current_folder_session_human"] = citem["status_hint"]
        show_last_file = True
        folder_activity_label = f"In lavorazione: {name} ({active_idx + 1}/{len(folders)})"
        if size_h:
            folder_activity_label += f" (~{size_h})"
    elif last_file:
        touch = resolve_work_folder(state, src, step_path=step_path, last_file=last_file)
        if touch:
            tp = sanitize_path(touch["path"])
            touch_name = touch.get("name") or tp.split("/")[-1]
            out["last_file_folder_name"] = touch_name
            out["last_file_folder_path"] = tp
            tidx = _find_folder_index(folders, tp)
            if tidx is not None:
                stored = _folder_display_status(folders[tidx].get("status") or "pending")
                if stored in ("done", "skipped"):
                    folder_activity_label = (
                        f"Confronto residuo in {touch_name} "
                        f"(cartella già allineata — {done_count}/{len(folders)} completate)"
                    )
                else:
                    show_last_file = True
                    folder_activity_label = (
                        f"Avvio cartella {touch_name} ({tidx + 1}/{len(folders)})"
                    )
    if not folder_activity_label:
        folder_activity_label = (
            f"Confronto sorgente ↔ QNAP ({done_count}/{len(folders)} cartelle allineate)"
        )

    out["show_last_file"] = show_last_file
    out["folder_activity_label"] = folder_activity_label

    excluded = entry.get("excluded_names") or []
    if excluded:
        out["excluded_folder_names"] = excluded[:8]
    return out


def catalog_to_progress_fields(state: dict[str, Any]) -> dict[str, Any]:
    """Campi da unire al progresso live per UI."""
    catalog = (state or {}).get("catalog") or {}
    source_bytes = int(catalog.get("source_bytes") or catalog.get("bytes_est") or 0)
    source_objects = int(catalog.get("source_objects") or catalog.get("files_est") or 0)
    out: dict[str, Any] = {}
    if source_bytes:
        out["source_size_bytes"] = source_bytes
        out["source_size_human"] = format_bytes_human(source_bytes)
    if source_objects:
        out["source_files_est"] = source_objects
    return out


def has_du_catalog(state: dict[str, Any], source_paths: list[str]) -> bool:
    """True se ogni path sorgente ha un catalogo cartelle du persistito."""
    per_path = (state or {}).get("per_path") or {}
    paths = [sanitize_path(p) for p in source_paths if p]
    if not paths:
        return False
    return all((per_path.get(p) or {}).get("folders") for p in paths)


def reset_folder_run_progress(state: dict[str, Any]) -> dict[str, Any]:
    """Ripristina stato avanzamento cartelle (non i byte du) — es. «Da capo»."""
    out = deepcopy(state)
    per_path = dict(out.get("per_path") or {})
    for src, entry in list(per_path.items()):
        entry = dict(entry)
        folders = []
        for f in entry.get("folders") or []:
            item = dict(f)
            item["status"] = "pending"
            item["session_bytes"] = 0
            item["files_copied"] = 0
            item["files_skipped"] = 0
            item["folder_files_copied"] = 0
            item["folder_files_skipped"] = 0
            item.pop("bytes_baseline", None)
            folders.append(item)
        if folders:
            entry["folders"] = folders
            entry.pop("current_folder_path", None)
            entry.pop("last_touch_folder_path", None)
            entry.pop("folder_high_water", None)
            per_path[src] = entry
    out["per_path"] = per_path
    return out


def mark_folder_step_started(
    state: dict[str, Any],
    source_root: str,
    folder_path: str,
) -> dict[str, Any]:
    """Segna una cartella ``in_progress`` all'avvio del relativo step rclone."""
    out = deepcopy(state)
    src = sanitize_path(source_root)
    fp = sanitize_path(folder_path)
    per_path = dict(out.get("per_path") or {})
    entry = dict(per_path.get(src) or {})
    folders = [dict(f) for f in (entry.get("folders") or [])]
    idx = _find_folder_index(folders, fp)
    if idx is not None:
        stored = folders[idx].get("status") or "pending"
        if stored not in ("done", "skipped"):
            folders[idx]["status"] = "in_progress"
            entry["folders"] = folders
            entry["current_folder_path"] = fp
            per_path[src] = entry
            out["per_path"] = per_path
    return out


def mark_folder_step_complete(
    state: dict[str, Any],
    source_root: str,
    folder_path: str,
) -> dict[str, Any]:
    """Chiude una cartella al termine dello step rclone dedicato."""
    out = deepcopy(state)
    src = sanitize_path(source_root)
    fp = sanitize_path(folder_path)
    per_path = dict(out.get("per_path") or {})
    entry = dict(per_path.get(src) or {})
    folders = [dict(f) for f in (entry.get("folders") or [])]
    idx = _find_folder_index(folders, fp)
    if idx is not None:
        folders[idx] = _finalize_folder_on_leave(folders[idx])
        entry["folders"] = folders
        if sanitize_path(str(entry.get("current_folder_path") or "")) == fp:
            entry.pop("current_folder_path", None)
        entry.pop("last_touch_folder_path", None)
        per_path[src] = entry
        out["per_path"] = per_path
    return out


def count_aligned_folders(state: dict[str, Any], source_paths: list[str]) -> int:
    """Cartelle già ``done``/``skipped`` nel catalogo (saltate dal piano espanso)."""
    per_path = (state or {}).get("per_path") or {}
    total = 0
    for raw in source_paths or []:
        src = sanitize_path(raw)
        for folder in (per_path.get(src) or {}).get("folders") or []:
            if (folder.get("status") or "pending") in ("done", "skipped"):
                total += 1
    return total


UI_PROGRESS_KEYS = frozenset({
    "current_folder_path",
    "current_folder_name",
    "current_folder_index",
    "current_folder_total",
    "current_folder_bytes",
    "current_folder_size_human",
    "current_folder_session_human",
    "current_folder_progress_pct",
    "folder_catalog",
    "folders_done",
    "folders_pending",
    "last_file_folder_name",
    "last_file_folder_path",
    "folder_activity_label",
    "show_last_file",
    "excluded_folder_names",
    "phase_label",
    "detail_lines",
    "hint",
    "display_summary",
    "progress_percent",
    "eta_human",
    "eta_unreliable",
    "source_size_human",
    "source_size_bytes",
    "source_files_est",
    "catalog_missing",
})


def strip_ui_progress(state: dict[str, Any]) -> dict[str, Any]:
    """Rimuove campi UI derivati prima di ricomporre il progresso live."""
    return {k: v for k, v in state.items() if k not in UI_PROGRESS_KEYS}


def compose_live_progress(
    rclone: dict[str, Any],
    extra: dict[str, Any],
    *,
    status: str = "",
    message: str = "",
) -> dict[str, Any]:
    """Unisce contatori rclone e campi catalogo/cartelle senza lasciare chiavi UI stale."""
    from services.file_replication.rclone_sync import enrich_rclone_progress_view

    core = strip_ui_progress(rclone)
    out = {**core, **extra}
    if status:
        out["status"] = status
    if message:
        out["message"] = message
    if extra.get("show_last_file") is False:
        out.pop("last_file", None)
    return enrich_rclone_progress_view(out)


def catalog_summary(state: dict[str, Any]) -> dict[str, Any]:
    catalog = (state or {}).get("catalog") or {}
    resume = (state or {}).get("resume") or {}
    per_path = (state or {}).get("per_path") or {}
    folder_count = int(catalog.get("folder_count") or 0)
    if not folder_count:
        folder_count = sum(len(p.get("folders") or []) for p in per_path.values())
    du_at = catalog.get("updated_at")
    for entry in per_path.values():
        sized = entry.get("source_sized_at")
        if sized and (not du_at or sized > du_at):
            du_at = sized
    return {
        "catalog_files_est": catalog.get("files_est"),
        "catalog_bytes_est": catalog.get("bytes_est"),
        "catalog_updated_at": catalog.get("updated_at"),
        "catalog_folder_count": folder_count or None,
        "catalog_du_at": du_at,
        "catalog_has_du": bool(folder_count),
        "resume_step_index": resume.get("step_index"),
        "resume_source_path": resume.get("source_path"),
        "resume_from_path": resume.get("resume_from_path"),
        "resume_last_file": resume.get("last_file"),
        "resume_paused_at": resume.get("paused_at"),
    }
