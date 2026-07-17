"""Utilità path per browse e sync replica file."""

import fnmatch

from services.file_replication.exclude_presets import browse_exclude_patterns


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
    """Da /Comune/AArchivio o /volume1/Comune/AArchivio → ('Comune', 'AArchivio')."""
    p = sanitize_path(path).strip("/")
    parts = [x for x in p.split("/") if x]
    if not parts:
        raise ValueError("path sorgente Synology non valido")
    if parts[0].startswith("volume") and len(parts) >= 2:
        return parts[1], "/".join(parts[2:])
    return parts[0], "/".join(parts[1:])


def synology_ssh_path(path: str, volume: str = "volume1") -> str:
    """Path assoluto SSH su Synology: /volume1/Comune/AArchivio."""
    share, subpath = parse_synology_share_path(path)
    vol = (volume or "volume1").strip("/") or "volume1"
    base = f"/{vol}/{share}"
    if subpath:
        return f"{base}/{subpath}"
    return base


def normalize_qnap_dest_share(path: str) -> str:
    """Normalizza e limita il path destinazione alla sola share QNAP (/share/DATI)."""
    return qnap_share_root(path)


def qnap_share_root(staging_path: str) -> str:
    """Root share QNAP da path staging UI (/share/DATI o /share/DATI/Comune → /share/DATI)."""
    p = normalize_qnap_staging_path(staging_path).rstrip("/")
    parts = [x for x in p.split("/") if x]
    if len(parts) >= 2 and parts[0] == "share":
        return f"/share/{parts[1]}"
    return p or "/share/DATI"


def synology_to_qnap_dest_path(src_path: str, dest_staging_path: str) -> str:
    """Replica struttura Synology sotto la share QNAP.

    /Comune/AArchivio + staging /share/DATI[/Comune] → /share/DATI/Comune/AArchivio/
    /Duerre              + staging /share/DATI       → /share/DATI/Duerre/
    """
    share, subpath = parse_synology_share_path(src_path)
    root = qnap_share_root(dest_staging_path).rstrip("/")
    dest = f"{root}/{share}"
    if subpath:
        dest = f"{dest}/{subpath}"
    return dest.rstrip("/") + "/"


def qnap_rclone_dest_path(dest_dir: str) -> str:
    """Path destinazione rclone SMB su QNAP.

    In UI il path è /share/DATI/Comune → rclone SMB usa DATI/Comune (nome share + sottopath).
    Non usare strip('/') generico: su SFTP relativo finiva fuori dalla share visibile in File Station.
    """
    p = normalize_qnap_staging_path(dest_dir).strip("/")
    parts = [x for x in p.split("/") if x]
    if parts and parts[0] == "share":
        parts = parts[1:]
    if not parts:
        raise ValueError("path destinazione QNAP non valido")
    return "/".join(parts)


def is_path_ancestor(ancestor: str, descendant: str) -> bool:
    """True se ancestor è uguale o antenato di descendant."""
    a = sanitize_path(ancestor).rstrip("/")
    d = sanitize_path(descendant).rstrip("/")
    if a == d:
        return True
    return d.startswith(f"{a}/")


def compact_source_paths(paths: list[str]) -> list[str]:
    """Rimuove path ridondanti (figli se il padre è già incluso)."""
    normalized = sorted({sanitize_path(p) for p in paths if p}, key=len)
    result: list[str] = []
    for path in normalized:
        if any(is_path_ancestor(existing, path) for existing in result):
            continue
        result = [existing for existing in result if not is_path_ancestor(path, existing)]
        result.append(path)
    return sorted(result)


def normalize_qnap_staging_path(path: str) -> str:
    """File Station QNAP: /DATI/foo → staging canonico /share/DATI/foo."""
    p = sanitize_path(path)
    if p == "/share":
        return p
    if p.startswith("/share/"):
        return p
    return f"/share{p}"


def is_excluded_name(name: str, presets: list[str]) -> bool:
    patterns = browse_exclude_patterns(presets)
    return any(fnmatch.fnmatch(name, pat) for pat in patterns)
