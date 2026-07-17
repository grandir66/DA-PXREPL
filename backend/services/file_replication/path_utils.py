"""Utilità path per browse e sync replica file."""

import fnmatch

from services.file_replication.exclude_presets import PRESETS


def sanitize_path(path: str) -> str:
    p = (path or "").strip().replace("\\", "/")
    if not p:
        return "/"
    if ".." in p.split("/"):
        raise ValueError("path traversal non consentito")
    if not p.startswith("/"):
        p = "/" + p
    return p.rstrip("/") or "/"


def is_excluded_name(name: str, presets: list[str]) -> bool:
    patterns: list[str] = []
    for preset in presets or []:
        patterns.extend(PRESETS.get(preset, []))
    return any(fnmatch.fnmatch(name, pat) for pat in patterns)
