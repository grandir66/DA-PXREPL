"""Report testuale esecuzione job replica file."""

from __future__ import annotations

from database import FileEndpoint, FileReplicationJob
from services.size_utils import format_bytes_human


def build_file_replication_report(
    *,
    job: FileReplicationJob,
    source: FileEndpoint,
    dest: FileEndpoint,
    duration_sec: int,
    progress: dict | None,
    total_bytes: int = 0,
) -> str:
    """Riepilogo sync per log, UI ed email."""
    progress = progress or {}
    summary = progress.get("summary") or ""
    lines: list[str] = [
        f"Job: {job.name}",
        f"Sorgente: {source.name} ({source.host})",
        f"Destinazione: {dest.name} ({dest.host}) → {job.dest_staging_path}",
        f"Durata: {duration_sec}s",
    ]

    paths = job.source_paths or []
    if paths:
        lines.append("Cartelle replicate:")
        for p in paths:
            lines.append(f"  • {p}")

    if summary:
        lines.append(f"Risultato: {summary}")
    else:
        copied = int(progress.get("files_copied") or progress.get("files_done") or 0)
        skipped = int(progress.get("files_skipped") or 0)
        if copied or skipped:
            parts = []
            if copied:
                parts.append(f"{copied} copiati")
            if skipped:
                parts.append(f"{skipped} saltati")
            lines.append(f"Risultato: {' · '.join(parts)}")

    transferred = progress.get("transferred_human")
    if transferred:
        lines.append(f"Dati trasferiti: {transferred}")
    elif total_bytes > 0:
        lines.append(f"Dati trasferiti: {format_bytes_human(total_bytes)}")

    if job.delete_on_dest:
        lines.append("Mirror: eliminazione file obsoleti su destinazione attiva")

    return "\n".join(lines)


def report_transferred_human(progress: dict | None, total_bytes: int = 0) -> str:
    progress = progress or {}
    if progress.get("transferred_human"):
        return str(progress["transferred_human"])
    if total_bytes > 0:
        return format_bytes_human(total_bytes)
    return "0 B"
