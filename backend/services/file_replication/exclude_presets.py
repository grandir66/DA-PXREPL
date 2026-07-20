"""Preset esclusioni rsync/rclone per replica file."""

from __future__ import annotations

# Sempre applicati al sync (non disabilitabili dal job).
MANDATORY_EXCLUDE_PRESETS: tuple[str, ...] = ("nas_snapshots", "system_files")

PRESETS: dict[str, list[str]] = {
    "nas_snapshots": [
        "#snapshot",
        "#Snapshot",
        "#snapshots",
        "@Snapshot",
        "@snapshots",
        ".snapshot",
        "@eaDir",
        "#recycle",
        "#Recycle",
        ".Trash-*",
        "@SynologyApplicationService",
        "@ActiveBackup",
        "@Recently-Snapshot",
        ".@__thumb",
        "@Recycle",
        ".Qsync",
        ".qsync",
    ],
    "system_files": [
        ".DS_Store",
        "Thumbs.db",
        "desktop.ini",
        "*.tmp",
        "*.swp",
        "~$*",
        "*.lnk",
        "System Volume Information",
        "$RECYCLE.BIN",
        ".SynologyWorkingDirectory",
        "@tmp",
        "@SynoEAStream",
    ],
    "windows_vss": [
        "~$*",
        "*.wbk",
    ],
}


def _merge_presets(presets: list[str] | None) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for preset in (*MANDATORY_EXCLUDE_PRESETS, *(presets or [])):
        if preset not in seen:
            seen.add(preset)
            merged.append(preset)
    return merged


def _collect_preset_patterns(presets: list[str], custom: list[str]) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for preset in _merge_presets(presets):
        for pat in PRESETS.get(preset, []):
            if pat not in seen:
                seen.add(pat)
                lines.append(pat)
    for pat in custom or []:
        p = (pat or "").strip()
        if p and p not in seen:
            seen.add(p)
            lines.append(p)
    return lines


def build_exclude_lines(presets: list[str], custom: list[str]) -> list[str]:
    """Pattern per rsync/tar (--exclude-from). Accetta nomi che iniziano con #."""
    return _collect_preset_patterns(presets, custom)


def build_rsync_exclude_lines(presets: list[str], custom: list[str]) -> list[str]:
    return build_exclude_lines(presets, custom)


def _expand_rclone_pattern(pat: str) -> list[str]:
    """Espande un pattern in forme valide per rclone ``--filter-from``.

    In rclone le righe del filter file che iniziano con # o ; sono commenti.
    Inoltre rclone 1.60 (Debian) non applica correttamente regole tipo
    ``**/#snapshot/**``: usare ``*#snapshot*/**`` per escludere la cartella
    a qualsiasi profondità.
    """
    p = (pat or "").strip()
    if not p:
        return []

    if p.startswith("**/"):
        out = [p]
        if p.endswith("/**"):
            out.append(p[:-3] + "/")
        return out

    if "/" in p:
        return [p, f"{p}/**"]

    if any(ch in p for ch in ("*", "?", "[")):
        return [p]

    if p[0] in "#@." or " " in p:
        return [f"*{p}*/**"]

    return [f"{p}/**", f"*{p}*/**"]


def build_rclone_filter_lines(presets: list[str], custom: list[str]) -> list[str]:
    """Regole per rclone ``--filter-from`` (prefisso ``- `` = exclude).

    Non include mai righe che rclone interpreta come commento (#… / ;…).
    """
    patterns: list[str] = []
    seen: set[str] = set()
    for pat in _collect_preset_patterns(presets, custom):
        for expanded in _expand_rclone_pattern(pat):
            if expanded not in seen:
                seen.add(expanded)
                patterns.append(expanded)

    patterns.sort(key=lambda x: (-len(x), x))
    return [f"- {pat}" for pat in patterns]


def build_rclone_cli_exclude_patterns(presets: list[str] | None = None) -> list[str]:
    """Pattern ``--exclude`` rclone (affidabili anche con nomi ``#snapshot``).

    Complemento a ``--filter-from``: rclone 1.60 ignora i filtri ``**/#…/**``.
    """
    patterns: list[str] = []
    seen: set[str] = set()
    for pat in _collect_preset_patterns(list(presets or []), []):
        p = (pat or "").strip()
        if not p or any(ch in p for ch in ("*", "?", "[")) or "/" in p:
            continue
        for expanded in _expand_rclone_pattern(p):
            if expanded not in seen:
                seen.add(expanded)
                patterns.append(expanded)
    return patterns


def browse_exclude_patterns(presets: list[str] | None) -> list[str]:
    """Pattern per browse UI (solo nomi cartella/file, no glob ricorsivi)."""
    patterns: list[str] = []
    seen: set[str] = set()
    for preset in _merge_presets(presets):
        for pat in PRESETS.get(preset, []):
            if "/" in pat:
                continue
            if pat not in seen:
                seen.add(pat)
                patterns.append(pat)
    return patterns
