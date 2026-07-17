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


def normalize_synology_ssh_path(path: str, volume: str = "volume1") -> str:
    """File Station usa /Share/...; rsync via SSH richiede /volume1/Share/..."""
    p = sanitize_path(path)
    if p.startswith("/volume"):
        return p
    vol = (volume or "volume1").strip("/") or "volume1"
    return f"/{vol}{p}"


def parse_synology_share_path(path: str) -> tuple[str, str]:
    """Da /DATI/archivio o /volume1/DATI/archivio → ('DATI', 'archivio')."""
    p = sanitize_path(path).strip("/")
    parts = [x for x in p.split("/") if x]
    if not parts:
        raise ValueError("path sorgente Synology non valido")
    if parts[0].startswith("volume") and len(parts) >= 2:
        return parts[1], "/".join(parts[2:])
    return parts[0], "/".join(parts[1:])


def is_excluded_name(name: str, presets: list[str]) -> bool:
    patterns: list[str] = []
    for preset in presets or []:
        patterns.extend(PRESETS.get(preset, []))
    return any(fnmatch.fnmatch(name, pat) for pat in patterns)
