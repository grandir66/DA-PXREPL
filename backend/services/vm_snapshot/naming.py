"""Naming snapshot del modulo: auto{label}_{YYYYMMDD}_{HHMMSS} — funzioni pure.

Prefisso deliberatamente distinto da `autosnap_*` (Sanoid): label senza underscore
rende il parsing non ambiguo e la retention tocca SOLO i nomi che matchano
integralmente questa regex con il label del job.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

LABEL_RE = re.compile(r"^[a-z][a-z0-9]{1,15}$")
SNAP_NAME_RE = re.compile(r"^auto([a-z][a-z0-9]{1,15})_(\d{8})_(\d{6})$")


def validate_label(label: str) -> None:
    """Solleva ValueError se il label non rispetta ^[a-z][a-z0-9]{1,15}$."""
    if not LABEL_RE.fullmatch(label or ""):
        raise ValueError(
            "Label non valido: minuscolo, inizia con lettera, solo lettere/cifre, 2-16 caratteri"
        )


def build_snapshot_name(label: str, dt: datetime) -> str:
    validate_label(label)
    return f"auto{label}_{dt:%Y%m%d}_{dt:%H%M%S}"


def parse_snapshot_name(name: str) -> Optional[tuple[str, datetime]]:
    """(label, timestamp) se il nome appartiene al modulo, altrimenti None."""
    match = SNAP_NAME_RE.fullmatch(name or "")
    if not match:
        return None
    try:
        ts = datetime.strptime(match.group(2) + match.group(3), "%Y%m%d%H%M%S")
    except ValueError:
        return None
    return match.group(1), ts


def build_description(job_id: int, job_name: str, label: str) -> str:
    """Descrizione visibile nella UI Proxmox: traccia la proprietà dello snapshot."""
    return f"dapx-vm-snapshot job={job_id} '{job_name}' label={label}"
