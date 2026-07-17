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

# Pattern ricorsivi aggiuntivi per rclone (--exclude-from).
RCLONE_RECURSIVE_EXCLUDES: tuple[str, ...] = (
    "**/#snapshot/**",
    "**/#Snapshot/**",
    "**/#snapshots/**",
    "**/@Snapshot/**",
    "**/@snapshots/**",
    "**/@eaDir/**",
    "**/#recycle/**",
    "**/#Recycle/**",
    "**/@Recycle/**",
    "**/.@__thumb/**",
    "**/System Volume Information/**",
    "**/$RECYCLE.BIN/**",
)


def _merge_presets(presets: list[str] | None) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for preset in (*MANDATORY_EXCLUDE_PRESETS, *(presets or [])):
        if preset not in seen:
            seen.add(preset)
            merged.append(preset)
    return merged


def build_exclude_lines(presets: list[str], custom: list[str]) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for preset in _merge_presets(presets):
        for pat in PRESETS.get(preset, []):
            if pat not in seen:
                seen.add(pat)
                lines.append(pat)
    for pat in RCLONE_RECURSIVE_EXCLUDES:
        if pat not in seen:
            seen.add(pat)
            lines.append(pat)
    for pat in custom or []:
        p = (pat or "").strip()
        if p and p not in seen:
            seen.add(p)
            lines.append(p)
    return lines


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
