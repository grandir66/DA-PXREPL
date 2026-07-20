"""Modello eventi comune ai due engine e costruzione vista progresso per la UI."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SyncEvent:
    phase: str | None = None
    last_file: str | None = None
    files_new: int = 0
    files_replaced: int = 0
    files_skipped: int = 0
    files_deleted: int = 0
    bytes_done: int | None = None
    bytes_total: int | None = None
    percent: int | None = None
    speed: str | None = None
    eta_seconds: int | None = None
    raw_line: str = ""


def human_bytes(n: int | None) -> str:
    if not n:
        return "0 B"
    value = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TiB"


def _fmt_count(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def eta_human(seconds: int | None) -> str | None:
    if not seconds or seconds <= 0:
        return None
    units = (
        (seconds // 86400, "giorno", "giorni"),
        ((seconds % 86400) // 3600, "ora", "ore"),
        ((seconds % 3600) // 60, "minuto", "minuti"),
        (seconds % 60, "secondo", "secondi"),
    )
    parts = [f"{n} {sing if n == 1 else plur}" for n, sing, plur in units if n]
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + f" e {parts[-1]}"


def apply_event(progress: dict, ev: SyncEvent) -> dict:
    """Accumula un evento nel dict di progresso (ritorna un nuovo dict)."""
    p = dict(progress)
    for attr in ("files_new", "files_replaced", "files_skipped", "files_deleted"):
        delta = getattr(ev, attr)
        if delta:
            p[attr] = int(p.get(attr) or 0) + delta
    p["files_copied"] = int(p.get("files_new") or 0) + int(p.get("files_replaced") or 0)
    p["files_done"] = p["files_copied"]
    if ev.phase:
        p["phase"] = ev.phase
    if ev.last_file:
        p["last_file"] = ev.last_file
    for attr in ("bytes_done", "bytes_total", "percent", "speed", "eta_seconds"):
        value = getattr(ev, attr)
        if value is not None:
            p[attr] = value
    return p


_PHASE_LABELS = {
    "starting": "Avvio replica…",
    "scanning": "Scansione sorgente",
    "copying": "Copia file verso destinazione",
    "done": "Completato",
}


def build_view(progress: dict) -> dict:
    """Campi leggibili per la UI (stessi nomi consumati da fileReplProgress.ts)."""
    view = dict(progress)
    phase = view.get("phase") or "starting"
    view["phase"] = phase
    view["phase_label"] = _PHASE_LABELS.get(phase, phase)

    detail_lines: list[str] = []
    new = int(view.get("files_new") or 0)
    replaced = int(view.get("files_replaced") or 0)
    skipped = int(view.get("files_skipped") or 0)
    deleted = int(view.get("files_deleted") or 0)
    if new or replaced or skipped or deleted:
        parts = []
        if new:
            parts.append(f"{_fmt_count(new)} nuovi")
        if replaced:
            parts.append(f"{_fmt_count(replaced)} aggiornati")
        if skipped:
            parts.append(f"{_fmt_count(skipped)} già allineati (saltati)")
        if deleted:
            parts.append(f"{_fmt_count(deleted)} eliminati su destinazione")
        detail_lines.append("File elaborati: " + ", ".join(parts))

    bytes_done = view.get("bytes_done")
    if bytes_done:
        view["transferred_human"] = human_bytes(int(bytes_done))
        total = view.get("bytes_total")
        if total:
            detail_lines.append(
                f"Trasferiti: {human_bytes(int(bytes_done))} / {human_bytes(int(total))}"
            )
        else:
            detail_lines.append(f"Trasferiti: {human_bytes(int(bytes_done))}")

    if view.get("percent") is not None:
        pct = view["percent"]
        view["progress_percent"] = f"{int(pct)}%" if isinstance(pct, int) else str(pct)
        if isinstance(pct, int):
            view["percent"] = view["progress_percent"]
    if view.get("speed"):
        detail_lines.append(f"Velocità attuale: {view['speed']}")
    eta = eta_human(view.get("eta_seconds"))
    if eta:
        view["eta_human"] = eta
        view["eta"] = eta
        detail_lines.append(f"Tempo restante stimato: ~{eta}")
    elif view.get("eta_human"):
        view["eta"] = view["eta_human"]
    if view.get("last_file") and phase == "copying":
        detail_lines.append(f"Ultimo file: {view['last_file']}")

    view["detail_lines"] = detail_lines
    view["display_summary"] = view["phase_label"] + (f" — {detail_lines[0]}" if detail_lines else "")
    return view
