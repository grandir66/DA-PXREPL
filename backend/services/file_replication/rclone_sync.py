"""Sync incrementale Synology → QNAP via rclone (SMB → SMB)."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import signal
import tempfile
from collections.abc import Callable
from typing import Optional

# SMB Synology↔QNAP: modtime spesso differisce di 1–2s → senza finestra rclone ricopia tutto.
RCLONE_SMB_MODIFY_WINDOW = "2s"


def build_rclone_performance_flags(*, delete_on_dest: bool, size_only: bool) -> list[str]:
    """Flag rclone per run incrementali più veloci su share grandi (SMB).

    - ``--fast-list``: listing ricorsivo se supportato dal backend
    - ``--no-traverse``: con ``copy`` evita di riscrivere tutta la destinazione
    - ``--size-only``: opzionale, salta in base alla sola dimensione
    """
    flags = ["--fast-list"]
    if not delete_on_dest:
        flags.append("--no-traverse")
    if size_only:
        flags.append("--size-only")
    return flags

from database import FileEndpoint
from services.file_replication.endpoint_crypto import decrypt_password
from services.file_replication.exclude_presets import build_rclone_cli_exclude_patterns
from services.file_replication.path_utils import parse_synology_share_path, qnap_rclone_dest_path

logger = logging.getLogger(__name__)

def _parse_rclone_count(raw: str) -> int:
    """Converte contatori rclone (es. 3.803k, 1,234) in intero."""
    text = raw.strip().replace(",", "")
    if not text:
        return 0
    mult = 1
    suffix = text[-1].lower()
    if suffix in ("k", "m", "g", "t"):
        mult = {"k": 1_000, "m": 1_000_000, "g": 1_000_000_000, "t": 1_000_000_000_000}[suffix]
        text = text[:-1]
    try:
        return int(float(text) * mult)
    except ValueError:
        return 0


_STATS_BYTES_RE = re.compile(
    r"(?:Transferred:\s+|INFO\s+:\s+)\s*"
    r"([\d.]+\s*(?:[KMGT]i?)?B)\s*/\s*([\d.]+\s*(?:[KMGT]i?)?B|\?),?\s*(\d+|-)?%?,?\s*"
    r"([\d.]+\s*(?:[KMGT]i?)?B/s)?,?\s*(?:ETA\s+([\dmswhd-]+))?",
    re.IGNORECASE,
)
_ETA_COMPONENTS_RE = re.compile(r"^(?:(\d+)w)?(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$")
_STATS_FILES_RE = re.compile(
    r"Transferred:\s+([\d,.kKmMgGtT]+)\s*/\s*([\d,.kKmMgGtT]+),?\s*(\d+|-)?%?",
    re.IGNORECASE,
)
_CHECKS_RE = re.compile(
    r"Checks:\s+([\d,.kKmMgGtT]+)\s*/\s*([\d,.kKmMgGtT]+),?\s*(\d+|-)?%?",
    re.IGNORECASE,
)
_COPIED_RE = re.compile(
    r"INFO\s+:\s+(.+?):\s+Copied\s+\((new|replaced|unchanged)\)",
    re.IGNORECASE,
)
_SKIPPED_MTIME_RE = re.compile(
    r"INFO\s+:\s+(.+?):\s+Updated modification time in destination",
    re.IGNORECASE,
)
_DELETED_RE = re.compile(
    r"INFO\s+:\s+(.+?):\s+Deleted",
    re.IGNORECASE,
)
_NOTHING_TRANSFER_RE = re.compile(r"There was nothing to transfer", re.IGNORECASE)


def preflight_rclone() -> None:
    from shutil import which

    if not which("rclone"):
        raise RuntimeError(
            "rclone non installato sul server dapx. Installare con: apt install rclone"
        )


def _obscure_password(password: str) -> str:
    import subprocess

    proc = subprocess.run(
        ["rclone", "obscure", password],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"rclone obscure fallito: {proc.stderr.strip()}")
    return proc.stdout.strip()


def _build_rclone_config(source: FileEndpoint, dest: FileEndpoint) -> tuple[str, str, str]:
    """Ritorna path config temp, remote sorgente, remote dest."""
    spass = decrypt_password(source.password_enc or "")
    dpass = decrypt_password(dest.password_enc or "")
    if not spass or not dpass:
        raise RuntimeError("Password mancante su endpoint sorgente o destinazione")

    fd, cfg_path = tempfile.mkstemp(prefix="dapx-fr-rclone-", suffix=".conf")
    os.close(fd)
    os.chmod(cfg_path, 0o600)

    content = f"""[fr_source]
type = smb
host = {source.host}
user = {source.username}
pass = {_obscure_password(spass)}
use_signing = false
use_server_modtime = true

[fr_dest]
type = smb
host = {dest.host}
user = {dest.username}
pass = {_obscure_password(dpass)}
use_signing = false
use_server_modtime = true
"""
    with open(cfg_path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return cfg_path, "fr_source", "fr_dest"


def _remote_paths(src_path: str, dest_dir: str) -> tuple[str, str]:
    share, subpath = parse_synology_share_path(src_path)
    src_remote = f"{share}/{subpath}" if subpath else share
    dest_remote = qnap_rclone_dest_path(dest_dir.rstrip("/"))
    return src_remote, dest_remote


def parse_rclone_progress(line: str) -> Optional[dict]:
    """Estrae avanzamento da righe stats/copied di rclone."""
    if _NOTHING_TRANSFER_RE.search(line):
        return {"nothing_to_transfer": True}

    copied = _COPIED_RE.search(line)
    if copied:
        action = copied.group(2).lower()
        out: dict = {"last_file": copied.group(1).strip(), "phase": "copying"}
        if action == "unchanged":
            out["files_skipped_delta"] = 1
        elif action == "new":
            out["files_new_delta"] = 1
            out["files_copied_delta"] = 1
        else:
            out["files_replaced_delta"] = 1
            out["files_copied_delta"] = 1
        return out

    skipped = _SKIPPED_MTIME_RE.search(line)
    if skipped:
        return {
            "files_skipped_delta": 1,
            "last_file": skipped.group(1).strip(),
        }

    deleted = _DELETED_RE.search(line)
    if deleted:
        return {
            "files_deleted_delta": 1,
            "last_file": deleted.group(1).strip(),
        }

    checks_match = _CHECKS_RE.search(line)
    if checks_match:
        done = _parse_rclone_count(checks_match.group(1))
        total_raw = checks_match.group(2).strip().replace(",", "")
        pct_raw = (checks_match.group(3) or "").strip()
        out: dict = {
            "files_checked": done,
            "phase": "scanning",
        }
        if total_raw and total_raw not in ("?", "-"):
            total = _parse_rclone_count(checks_match.group(2))
            out["files_checked_total"] = total
            if pct_raw and pct_raw != "-":
                out["checks_percent"] = f"{pct_raw}%"
            elif total > 0:
                out["checks_percent"] = f"{int(done * 100 / total)}%"
        elif pct_raw and pct_raw != "-":
            out["checks_percent"] = f"{pct_raw}%"
        return out

    files_match = _STATS_FILES_RE.search(line)
    if files_match:
        done = _parse_rclone_count(files_match.group(1))
        total = _parse_rclone_count(files_match.group(2))
        pct_raw = (files_match.group(3) or "").strip()
        out = {
            "stat_files_transferred": done,
            "stat_files_total": total,
        }
        if pct_raw and pct_raw != "-":
            out["transfer_files_percent"] = f"{pct_raw}%"
        elif total > 0:
            out["transfer_files_percent"] = f"{int(done * 100 / total)}%"
        return out

    bytes_match = _STATS_BYTES_RE.search(line)
    if bytes_match:
        transferred = bytes_match.group(1).strip()
        total_raw = bytes_match.group(2).strip()
        pct_raw = (bytes_match.group(3) or "").strip()
        speed = (bytes_match.group(4) or "").strip() or None
        eta = (bytes_match.group(5) or "").strip() or None
        out = {
            "transferred_human": transferred,
            "speed": speed,
            "eta": eta,
        }
        if transferred not in ("0 B", "27 B") and not transferred.startswith("0 "):
            out["phase"] = "copying"
        if total_raw != "?":
            out["transferred_total_human"] = total_raw
            if pct_raw and pct_raw != "-":
                out["percent"] = f"{pct_raw}%"
        return out

    return None


def merge_rclone_progress(state: dict, patch: dict) -> dict:
    """Accumula patch di progresso rclone nello stato del job."""
    merged = dict(state)
    for delta_key, counter_key in (
        ("files_copied_delta", "files_copied"),
        ("files_new_delta", "files_new"),
        ("files_replaced_delta", "files_replaced"),
        ("files_skipped_delta", "files_skipped"),
        ("files_deleted_delta", "files_deleted"),
    ):
        if patch.get(delta_key):
            merged[counter_key] = int(merged.get(counter_key) or 0) + int(patch[delta_key])

    if patch.get("nothing_to_transfer"):
        merged["nothing_to_transfer"] = True

    for key, value in patch.items():
        if key.endswith("_delta") or key == "nothing_to_transfer":
            continue
        if value is not None:
            merged[key] = value

    merged["files_done"] = int(merged.get("files_copied") or 0)
    return merged


def _fmt_count(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def format_rclone_eta(raw: str | None) -> str | None:
    """Converte ETA compatta rclone (es. ``6w3d``, ``15m30s``) in testo italiano."""
    if not raw or raw.strip() == "-":
        return None
    text = raw.strip().lower()
    match = _ETA_COMPONENTS_RE.fullmatch(text)
    if not match and re.fullmatch(r"\d+w\d+", text):
        # Compat: regex precedente troncava la ``d`` finale (6w3 → 6w3d).
        w, d = re.fullmatch(r"(\d+)w(\d+)", text).groups()  # type: ignore[union-attr]
        match = _ETA_COMPONENTS_RE.fullmatch(f"{w}w{d}d")
    if not match:
        return text

    units = (
        (int(match.group(1) or 0), "settimana", "settimane"),
        (int(match.group(2) or 0), "giorno", "giorni"),
        (int(match.group(3) or 0), "ora", "ore"),
        (int(match.group(4) or 0), "minuto", "minuti"),
        (int(match.group(5) or 0), "secondo", "secondi"),
    )
    parts = [f"{n} {sing if n == 1 else plur}" for n, sing, plur in units if n]
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} e {parts[1]}"
    return ", ".join(parts[:-1]) + f" e {parts[-1]}"


def eta_to_seconds(raw: str | None) -> int | None:
    """Secondi da ETA rclone compatta."""
    if not raw or raw.strip() == "-":
        return None
    text = raw.strip().lower()
    match = _ETA_COMPONENTS_RE.fullmatch(text)
    if not match and re.fullmatch(r"\d+w\d+", text):
        w, d = re.fullmatch(r"(\d+)w(\d+)", text).groups()  # type: ignore[union-attr]
        match = _ETA_COMPONENTS_RE.fullmatch(f"{w}w{d}d")
    if not match:
        return None
    weeks = int(match.group(1) or 0)
    days = int(match.group(2) or 0)
    hours = int(match.group(3) or 0)
    minutes = int(match.group(4) or 0)
    seconds = int(match.group(5) or 0)
    return (
        weeks * 7 * 86400
        + days * 86400
        + hours * 3600
        + minutes * 60
        + seconds
    )


def _parse_percent_label(value: str | None) -> int | None:
    if not value:
        return None
    text = str(value).strip().rstrip("%")
    try:
        return int(float(text))
    except ValueError:
        return None


def should_show_rclone_eta(state: dict) -> bool:
    """True solo se l'ETA rclone ha senso mostrarlo (evita settimane fantasma)."""
    eta = (state.get("eta") or "").strip()
    if not eta or eta == "-":
        return False

    total = (state.get("transferred_total_human") or "").strip()
    if not total or total == "?":
        return False

    speed = (state.get("speed") or "").strip()
    if not speed or speed in ("0 B/s", "0 B/s,"):
        return False

    pct = _parse_percent_label(
        state.get("percent") or state.get("transfer_files_percent") or state.get("progress_percent")
    )
    if pct is None or pct < 8:
        return False

    checked = int(state.get("files_checked") or 0)
    copied = int(state.get("files_copied") or 0)
    skipped = int(state.get("files_skipped") or 0)
    # Fase confronto: molti check, pochi copiati → rclone stima come se dovesse copiare tutto.
    if checked > 500 and copied < max(checked // 30, 50) and skipped < copied * 3:
        return False

    eta_sec = eta_to_seconds(eta)
    if eta_sec is not None and eta_sec > 7 * 86400 and (pct or 0) < 25:
        return False

    return True


def _format_bytes_progress_lines(merged: dict) -> list[str]:
    """Righe UI: dimensione reale share vs byte del run corrente (metriche diverse)."""
    lines: list[str] = []
    if merged.get("source_size_human"):
        files = merged.get("source_files_est")
        files_part = f", ~{_fmt_count(int(files))} file" if files else ""
        lines.append(
            f"Dimensione sorgente (du 1° livello, senza snapshot): ~{merged['source_size_human']}{files_part}"
        )
    bytes_h = (merged.get("transferred_human") or "").strip()
    if not bytes_h:
        return lines
    total = (merged.get("transferred_total_human") or "").strip()
    pct = merged.get("percent")
    if total and total != "?":
        pct_part = f" ({pct})" if pct else ""
        lines.append(
            f"Byte in lavorazione (solo questo run): {bytes_h} / ~{total}{pct_part} "
            f"— stima rclone sui file da confrontare/copiare adesso, non il totale share"
        )
    else:
        lines.append(f"Byte letti/scritti in questo run: {bytes_h}")
    return lines


def _format_bytes_progress_line(merged: dict) -> str | None:
    lines = _format_bytes_progress_lines(merged)
    return lines[0] if lines else None


def _format_file_stats_line(merged: dict) -> str | None:
    """Contatore file da riga stats ``Transferred: N / M`` (aggiornato ~ogni 5s)."""
    done = merged.get("stat_files_transferred")
    total = merged.get("stat_files_total")
    if not done or not total:
        return None
    pct = merged.get("transfer_files_percent")
    pct_part = f" ({pct})" if pct else ""
    return f"File nel job (stats rclone): {_fmt_count(int(done))} / {_fmt_count(int(total))}{pct_part}"


def _checked_counter_stale(merged: dict, *, copied: int, skipped: int, phase: str) -> bool:
    """In copia i ``Checks:`` di rclone smettono di aggiornarsi mentre i ``Copied:`` sì."""
    if phase != "copying":
        return False
    checked = int(merged.get("files_checked") or 0)
    processed = copied + skipped
    return checked > 0 and processed > checked


def _format_files_processed_line(merged: dict) -> str | None:
    new = int(merged.get("files_new") or 0)
    replaced = int(merged.get("files_replaced") or 0)
    copied = int(merged.get("files_copied") or 0)
    skipped = int(merged.get("files_skipped") or 0)
    if new <= 0 and replaced <= 0 and copied <= 0 and skipped <= 0:
        return None
    parts: list[str] = []
    if new:
        parts.append(f"{_fmt_count(new)} nuovi")
    if replaced:
        parts.append(f"{_fmt_count(replaced)} aggiornati (modtime/dimensione)")
    if not new and not replaced and copied:
        parts.append(f"{_fmt_count(copied)} copiati")
    if skipped:
        parts.append(f"{_fmt_count(skipped)} già su QNAP (saltati)")
    return "File elaborati: " + ", ".join(parts)


def _format_folder_progress_lines(merged: dict) -> list[str]:
    lines: list[str] = []
    label = merged.get("folder_activity_label")
    if label:
        lines.append(label)
    elif merged.get("current_folder_name") or merged.get("current_folder_path"):
        name = merged.get("current_folder_name")
        path = merged.get("current_folder_path")
        idx = merged.get("current_folder_index")
        total = merged.get("current_folder_total")
        pos = f" ({idx}/{total})" if idx and total else ""
        size_h = merged.get("current_folder_size_human")
        legacy = f"Cartella corrente{pos}: {name or path}"
        if size_h:
            legacy += f" (~{size_h})"
        lines.append(legacy)
    if merged.get("current_folder_index"):
        sess = merged.get("current_folder_session_human")
        pct = merged.get("current_folder_progress_pct")
        if sess and pct is not None:
            lines.append(
                f"Avanzamento cartella: ~{sess} elaborati (~{pct}% del volume cartella)"
            )
        elif sess:
            lines.append(f"Avanzamento cartella: ~{sess} elaborati in questa fase")
    excluded = merged.get("excluded_folder_names")
    if excluded:
        lines.append(f"Escluse dal catalogo du: {', '.join(excluded[:5])}")
    return lines


def enrich_rclone_progress_view(state: dict) -> dict:
    """Aggiunge campi UI leggibili (fase, etichette, suggerimenti)."""
    merged = dict(state)
    checked = int(merged.get("files_checked") or 0)
    checked_total = merged.get("files_checked_total")
    copied = int(merged.get("files_copied") or 0)
    skipped = int(merged.get("files_skipped") or 0)
    bytes_h = (merged.get("transferred_human") or "").strip()
    has_bytes = bool(bytes_h and bytes_h not in ("0 B", "27 B") and not bytes_h.startswith("0 "))

    if merged.get("nothing_to_transfer") and copied == 0 and skipped == 0:
        phase = "done"
        phase_label = "Completato — nessun file da trasferire"
    elif merged.get("phase") == "copying" or copied > 0 or has_bytes:
        checked = int(merged.get("files_checked") or 0)
        pct_num = _parse_percent_label(merged.get("percent") or merged.get("transfer_files_percent"))
        compare_heavy = (
            checked > 500
            and copied < max(checked // 30, 50)
            and skipped < copied * 3
            and (pct_num is None or pct_num < 15)
        )
        if compare_heavy:
            phase = "scanning"
            phase_label = "Confronto sorgente ↔ QNAP"
        else:
            phase = "copying"
            phase_label = "Copia file verso QNAP"
    elif checked > 0 or merged.get("phase") == "scanning":
        phase = "scanning"
        phase_label = "Scansione sorgente Synology"
    else:
        phase = "starting"
        phase_label = "Avvio replica…"

    detail_lines: list[str] = []
    hint: str | None = None
    folder_lines = _format_folder_progress_lines(merged)
    if folder_lines:
        detail_lines.extend(folder_lines)

    if phase == "scanning":
        if checked_total and int(checked_total) > 0:
            pct = merged.get("checks_percent") or f"{int(checked * 100 / int(checked_total))}%"
            detail_lines.append(
                f"Confronto file Synology↔QNAP: {_fmt_count(checked)} / {_fmt_count(int(checked_total))} ({pct})"
            )
            merged["progress_percent"] = pct
        elif checked > 0:
            detail_lines.append(f"Confronto file in corso: {_fmt_count(checked)} esaminati")
            detail_lines.append("Totale file ancora sconosciuto (rclone sta elencando la share).")
        proc_line = _format_files_processed_line(merged)
        if proc_line:
            detail_lines.append(proc_line)
        elif copied == 0 and skipped == 0:
            hint = (
                "Su share grandi rclone prima confronta ogni file con QNAP: "
                "è normale vedere zero «copiati» per molto tempo."
            )
        bytes_lines = _format_bytes_progress_lines(merged)
        detail_lines.extend(bytes_lines)
        if merged.get("eta") and merged.get("eta") != "-" and not should_show_rclone_eta(merged):
            merged["eta_unreliable"] = True
            hint = (
                "Il tempo restante di rclone in questa fase è spesso sbagliato (es. settimane): "
                "stima il trasferimento totale prima di conoscere quanti file sono già su QNAP."
            )
    elif phase == "copying":
        proc_line = _format_files_processed_line(merged)
        if proc_line:
            detail_lines.append(proc_line)
        stat_line = _format_file_stats_line(merged)
        if stat_line:
            detail_lines.append(stat_line)
        elif _checked_counter_stale(merged, copied=copied, skipped=skipped, phase=phase):
            hint = (
                "Il contatore «confronto file» non si aggiorna in fase copia: "
                "rclone incrementa solo «copiati/saltati» file per file."
            )
        bytes_lines = _format_bytes_progress_lines(merged)
        detail_lines.extend(bytes_lines)
        if merged.get("speed") and merged.get("speed") != "0 B/s":
            detail_lines.append(f"Velocità attuale: {merged['speed']}")
        if should_show_rclone_eta(merged):
            eta_human = format_rclone_eta(merged.get("eta"))
            if eta_human:
                merged["eta_human"] = eta_human
                detail_lines.append(f"Tempo restante stimato: ~{eta_human}")
        elif merged.get("eta") and merged.get("eta") != "-":
            merged["eta_unreliable"] = True
            if not hint:
                hint = (
                    "Tempo restante non mostrato: rclone lo sovrastima finché non ha finito "
                    "il confronto con QNAP (molti file verranno saltati se già presenti)."
                )
        if not hint and bytes_lines and not merged.get("source_size_human"):
            hint = (
                "La riga «Byte in lavorazione» non è la dimensione delle share: "
                "al primo run viene calcolata con du sulla Synology."
            )
        if merged.get("transfer_files_percent"):
            merged["progress_percent"] = merged["transfer_files_percent"]
        elif merged.get("percent"):
            merged["progress_percent"] = merged["percent"]
    elif phase == "done":
        detail_lines.append("Tutti i file risultano già allineati.")

    merged["phase"] = phase
    merged["phase_label"] = phase_label
    merged["detail_lines"] = detail_lines
    if hint:
        merged["hint"] = hint
    merged["display_summary"] = phase_label
    if detail_lines:
        merged["display_summary"] += " — " + detail_lines[0]
    return merged


def summarize_rclone_output(lines: list[str]) -> dict:
    """Ricostruisce riepilogo finale da tutto l'output rclone."""
    state: dict = {}
    for line in lines:
        patch = parse_rclone_progress(line)
        if patch:
            state = merge_rclone_progress(state, patch)
    return state


def format_rclone_progress_summary(state: dict) -> str:
    """Testo riepilogo per log/messaggi UI."""
    view = enrich_rclone_progress_view(state)
    if not view.get("detail_lines") and not view.get("phase_label"):
        return ""
    parts = [view.get("phase_label", "")]
    parts.extend(view.get("detail_lines") or [])
    if view.get("nothing_to_transfer") and not int(view.get("files_copied") or 0):
        return "Nessun file da trasferire"
    return " · ".join(p for p in parts if p)


class RcloneCancelledError(Exception):
    """Sync rclone interrotto su richiesta utente."""


async def _stream_subprocess(
    proc: asyncio.subprocess.Process,
    *,
    on_line: Callable[[str], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> list[str]:
    """Legge stdout del processo; termina il process group se ``cancel_check`` è True."""
    combined: list[str] = []
    assert proc.stdout is not None
    while proc.returncode is None:
        if cancel_check and cancel_check():
            if proc.pid:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    proc.terminate()
            await asyncio.sleep(0.5)
            if proc.returncode is None and proc.pid:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    proc.kill()
            raise RcloneCancelledError("Sync interrotto dall'utente")
        try:
            line_b = await asyncio.wait_for(proc.stdout.readline(), timeout=1.0)
        except asyncio.TimeoutError:
            continue
        if not line_b:
            break
        line = line_b.decode(errors="replace")
        combined.append(line)
        if on_line:
            on_line(line)
    await proc.wait()
    return combined


async def rclone_sync_synology_to_qnap(
    source: FileEndpoint,
    dest: FileEndpoint,
    src_path: str,
    dest_dir: str,
    *,
    delete_on_dest: bool,
    filter_file: str | None = None,
    bandwidth_limit_kb: int | None = None,
    size_only: bool = False,
    on_line: Callable[[str], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    process_registry: list[asyncio.subprocess.Process] | None = None,
    pid_file: str | None = None,
) -> tuple[list[str], list[str]]:
    """Sync incrementale; con delete_on_dest rimuove su QNAP ciò che non è più in sorgente."""
    cfg_path, src_name, dest_name = _build_rclone_config(source, dest)
    src_remote, dest_remote = _remote_paths(src_path, dest_dir)
    cmd = [
        "rclone",
        "sync" if delete_on_dest else "copy",
        f"{src_name}:{src_remote}",
        f"{dest_name}:{dest_remote}",
        "--create-empty-src-dirs",
        "--modify-window",
        RCLONE_SMB_MODIFY_WINDOW,
        *build_rclone_performance_flags(delete_on_dest=delete_on_dest, size_only=size_only),
        "--stats",
        "5s",
        "-v",
    ]
    if delete_on_dest:
        cmd.append("--delete-after")
    for exclude_pat in build_rclone_cli_exclude_patterns():
        cmd.extend(["--exclude", exclude_pat])
    if filter_file and os.path.isfile(filter_file):
        cmd.extend(["--filter-from", filter_file])
        cmd.append("--ignore-case")
    if bandwidth_limit_kb:
        cmd.extend(["--bwlimit", f"{bandwidth_limit_kb}K"])

    env = os.environ.copy()
    env["RCLONE_CONFIG"] = cfg_path
    logger.info(
        "rclone %s %s:%s -> %s:%s (delete=%s size_only=%s)",
        cmd[1],
        src_name,
        src_remote,
        dest_name,
        dest_remote,
        delete_on_dest,
        size_only,
    )

    try:
        mkdir_proc = await asyncio.create_subprocess_exec(
            "rclone",
            "mkdir",
            f"{dest_name}:{dest_remote}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
            start_new_session=True,
        )
        if process_registry is not None:
            process_registry.append(mkdir_proc)
        mkdir_out, _ = await mkdir_proc.communicate()
        if mkdir_out:
            combined_mkdir = mkdir_out.decode(errors="replace")
            if on_line:
                on_line(combined_mkdir)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
            start_new_session=True,
        )
        if process_registry is not None:
            process_registry.append(proc)
        if pid_file and proc.pid:
            with open(pid_file, "w", encoding="utf-8") as fh:
                fh.write(str(proc.pid))

        try:
            combined = await _stream_subprocess(
                proc,
                on_line=on_line,
                cancel_check=cancel_check,
            )
        except RcloneCancelledError:
            raise
        code = proc.returncode
        if code != 0:
            tail = "".join(combined)[-2000:]
            if code in (-15, -2, 130, 143):
                raise RuntimeError(
                    "Sync interrotto (processo terminato). "
                    "I file già copiati restano su QNAP. "
                    "Rilancia il job: rclone trasferirà solo i file mancanti."
                ) from None
            raise RuntimeError(f"rclone exit {code}: {tail}")
        return combined, []
    finally:
        if pid_file and os.path.exists(pid_file):
            try:
                os.unlink(pid_file)
            except OSError:
                pass
        try:
            os.unlink(cfg_path)
        except OSError:
            pass
