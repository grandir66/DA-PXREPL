"""Temperature parsing and validation for lm-sensors host readings."""

import re
from typing import Any, Dict, List, Optional

TEMP_INPUT_KEY_RE = re.compile(r"^temp\d+_input$", re.IGNORECASE)
MIN_TEMP_C = -40.0
MAX_TEMP_C = 125.0
MILLIDEGREE_MIN = 200.0
MILLIDEGREE_MAX = 200_000.0


def is_temperature_input_key(key: str) -> bool:
    return bool(TEMP_INPUT_KEY_RE.match(key))


def normalize_temperature_celsius(raw: Any) -> Optional[float]:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value != value:
        return None
    if MILLIDEGREE_MIN < value <= MILLIDEGREE_MAX:
        value = value / 1000.0
    if not (MIN_TEMP_C <= value <= MAX_TEMP_C):
        return None
    return round(value, 1)


def resolve_highest_temperature_c(temp_data: Optional[Dict[str, Any]]) -> Optional[float]:
    if not temp_data or not isinstance(temp_data, dict):
        return None

    candidates: List[float] = []
    for reading in temp_data.get("readings") or []:
        if not isinstance(reading, dict):
            continue
        normalized = normalize_temperature_celsius(reading.get("temperature_c"))
        if normalized is not None:
            candidates.append(normalized)

    for key in ("highest_c", "highest"):
        normalized = normalize_temperature_celsius(temp_data.get(key))
        if normalized is not None:
            candidates.append(normalized)

    if not candidates:
        return None
    return max(candidates)
