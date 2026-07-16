"""Utility per parsing e formattazione dimensioni trasferimento."""

from __future__ import annotations

import re
from typing import Optional

_SIZE_RE = re.compile(
    r"^([\d.]+)\s*([KMGTPE])?I?B?$",
    re.IGNORECASE,
)

_UNITS = {
    "": 1,
    "K": 1024,
    "M": 1024**2,
    "G": 1024**3,
    "T": 1024**4,
    "P": 1024**5,
    "E": 1024**6,
}


def parse_transfer_size_to_bytes(value: Optional[str]) -> int:
    """Converte stringhe tipo '1.5G', '128 MiB', '10.5GB' in byte."""
    if not value:
        return 0
    text = str(value).strip().replace(" ", "")
    if not text:
        return 0

    match = _SIZE_RE.match(text)
    if not match:
        return 0

    try:
        amount = float(match.group(1))
    except ValueError:
        return 0

    unit = (match.group(2) or "").upper()
    multiplier = _UNITS.get(unit, 0)
    if not multiplier:
        return 0

    return int(amount * multiplier)


def format_bytes_human(num_bytes: int) -> str:
    """Formatta byte in stringa leggibile (base 1024)."""
    if num_bytes <= 0:
        return "0 B"

    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    size = float(num_bytes)
    unit_idx = 0
    while size >= 1024 and unit_idx < len(units) - 1:
        size /= 1024
        unit_idx += 1

    if unit_idx == 0:
        return f"{int(size)} {units[unit_idx]}"
    return f"{size:.1f} {units[unit_idx]}"


def sum_transferred_values(values: list[Optional[str]]) -> str:
    total = sum(parse_transfer_size_to_bytes(v) for v in values)
    return format_bytes_human(total)
