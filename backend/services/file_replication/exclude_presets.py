"""Preset esclusioni rsync per replica file."""

PRESETS: dict[str, list[str]] = {
    "nas_snapshots": [
        "@Snapshot",
        "@snapshots",
        "#snapshot",
        ".snapshot",
        "@eaDir",
        "#recycle",
        ".Trash-*",
        "@SynologyApplicationService",
        "@ActiveBackup",
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
    ],
    "windows_vss": [
        "~$*",
        "*.wbk",
    ],
}


def build_exclude_lines(presets: list[str], custom: list[str]) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for preset in presets or []:
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
