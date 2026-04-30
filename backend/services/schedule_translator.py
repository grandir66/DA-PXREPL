"""
Schedule Translator
-------------------
Round-trip tra una struttura JSON "human-readable" e una cron string POSIX
a 5 campi (minute hour dom month dow). Il backend continua a salvare la
cron string in `<job>.schedule` (consumata da croniter nello scheduler);
in più persiste la struttura ricca in `<job>.schedule_config` per
ricostruire la UI senza dover re-parsare il cron.

JSON schema (ScheduleConfig):

    {
        "kind": "manual" | "hourly" | "daily" | "weekly" | "monthly"
              | "every_n_hours" | "every_n_days" | "advanced",
        "time":          "HH:MM",     # daily / weekly / monthly / every_n_days
        "minute":        0..59,       # hourly / every_n_hours
        "weekdays":      ["mon", ...] # weekly
        "day_of_month":  1..31,       # monthly
        "hours":         1..23,       # every_n_hours
        "days":          1..30,       # every_n_days
        "cron":          "...",       # advanced
    }

`manual` = nessuna pianificazione (cron None).
`advanced` = passthrough del cron raw (per i casi non rappresentabili).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from croniter import croniter
from pydantic import BaseModel, Field, field_validator


WEEKDAY_NAMES = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]
WEEKDAY_TO_CRON = {name: i for i, name in enumerate(WEEKDAY_NAMES)}
CRON_TO_WEEKDAY = {i: name for i, name in enumerate(WEEKDAY_NAMES)}

WEEKDAY_LABELS_IT = {
    "sun": "domenica",
    "mon": "lunedì",
    "tue": "martedì",
    "wed": "mercoledì",
    "thu": "giovedì",
    "fri": "venerdì",
    "sat": "sabato",
}


class ScheduleConfig(BaseModel):
    """Modello validato della struttura JSON di pianificazione."""

    kind: str = Field(..., pattern=r"^(manual|hourly|daily|weekly|monthly|every_n_hours|every_n_days|advanced)$")
    time: Optional[str] = Field(default=None, pattern=r"^([01]?\d|2[0-3]):[0-5]\d$")
    minute: Optional[int] = Field(default=None, ge=0, le=59)
    weekdays: Optional[List[str]] = None
    day_of_month: Optional[int] = Field(default=None, ge=1, le=31)
    hours: Optional[int] = Field(default=None, ge=1, le=23)
    days: Optional[int] = Field(default=None, ge=1, le=30)
    cron: Optional[str] = None

    @field_validator("weekdays")
    @classmethod
    def _check_weekdays(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return v
        bad = [d for d in v if d.lower() not in WEEKDAY_TO_CRON]
        if bad:
            raise ValueError(f"weekday non validi: {bad}")
        return [d.lower() for d in v]


def to_cron(config: Dict[str, Any] | ScheduleConfig) -> Optional[str]:
    """Converte un ScheduleConfig nella cron string equivalente.

    Ritorna None per `manual` (nessuna pianificazione). Solleva
    ValueError se la combinazione di campi è incompleta o inconsistente.
    """
    if isinstance(config, dict):
        cfg = ScheduleConfig(**config)
    else:
        cfg = config

    kind = cfg.kind

    if kind == "manual":
        return None

    if kind == "advanced":
        if not cfg.cron or not cfg.cron.strip():
            raise ValueError("kind=advanced richiede 'cron'")
        cron = cfg.cron.strip()
        if not croniter.is_valid(cron):
            raise ValueError(f"cron non valido: {cron!r}")
        return cron

    if kind == "hourly":
        m = cfg.minute if cfg.minute is not None else 0
        return f"{m} * * * *"

    if kind == "every_n_hours":
        if not cfg.hours:
            raise ValueError("kind=every_n_hours richiede 'hours'")
        m = cfg.minute if cfg.minute is not None else 0
        return f"{m} */{cfg.hours} * * *"

    # I rimanenti tipi richiedono `time = "HH:MM"`
    if not cfg.time:
        raise ValueError(f"kind={kind} richiede 'time' nel formato HH:MM")
    hh, mm = cfg.time.split(":")
    h, m = int(hh), int(mm)

    if kind == "daily":
        return f"{m} {h} * * *"

    if kind == "every_n_days":
        if not cfg.days:
            raise ValueError("kind=every_n_days richiede 'days'")
        return f"{m} {h} */{cfg.days} * *"

    if kind == "weekly":
        if not cfg.weekdays:
            raise ValueError("kind=weekly richiede almeno un weekday")
        nums = sorted({WEEKDAY_TO_CRON[d] for d in cfg.weekdays})
        return f"{m} {h} * * {','.join(str(n) for n in nums)}"

    if kind == "monthly":
        if not cfg.day_of_month:
            raise ValueError("kind=monthly richiede 'day_of_month'")
        return f"{m} {h} {cfg.day_of_month} * *"

    raise ValueError(f"kind sconosciuto: {kind}")


_INT_RE = re.compile(r"^\d+$")
_STEP_RE = re.compile(r"^\*/(\d+)$")
_LIST_RE = re.compile(r"^\d+(,\d+)+$")


def from_cron(cron: Optional[str]) -> Dict[str, Any]:
    """Best-effort: ricostruisce un ScheduleConfig dal cron raw.

    Se il pattern non rientra nei tipi noti, ricade su `advanced` con il
    cron originale — la UI può comunque mostrarlo nel campo libero.
    """
    if not cron or not cron.strip():
        return {"kind": "manual"}

    cron = cron.strip()
    parts = cron.split()
    if len(parts) != 5:
        return {"kind": "advanced", "cron": cron}

    minute, hour, dom, month, dow = parts

    if month != "*":
        return {"kind": "advanced", "cron": cron}

    # hourly: M * * * *
    if _INT_RE.match(minute) and hour == "*" and dom == "*" and dow == "*":
        return {"kind": "hourly", "minute": int(minute)}

    # every_n_hours: M */N * * *
    step = _STEP_RE.match(hour)
    if _INT_RE.match(minute) and step and dom == "*" and dow == "*":
        return {
            "kind": "every_n_hours",
            "minute": int(minute),
            "hours": int(step.group(1)),
        }

    # daily: MM HH * * *
    if _INT_RE.match(minute) and _INT_RE.match(hour) and dom == "*" and dow == "*":
        return {
            "kind": "daily",
            "time": f"{int(hour):02d}:{int(minute):02d}",
        }

    # every_n_days: MM HH */N * *
    step_d = _STEP_RE.match(dom)
    if _INT_RE.match(minute) and _INT_RE.match(hour) and step_d and dow == "*":
        return {
            "kind": "every_n_days",
            "time": f"{int(hour):02d}:{int(minute):02d}",
            "days": int(step_d.group(1)),
        }

    # weekly: MM HH * * 1,3,5  (o singolo)
    if _INT_RE.match(minute) and _INT_RE.match(hour) and dom == "*":
        if _INT_RE.match(dow) or _LIST_RE.match(dow):
            nums = sorted({int(x) for x in dow.split(",")})
            if all(0 <= n <= 6 for n in nums):
                return {
                    "kind": "weekly",
                    "time": f"{int(hour):02d}:{int(minute):02d}",
                    "weekdays": [CRON_TO_WEEKDAY[n] for n in nums],
                }

    # monthly: MM HH D * *
    if (
        _INT_RE.match(minute)
        and _INT_RE.match(hour)
        and _INT_RE.match(dom)
        and dow == "*"
    ):
        return {
            "kind": "monthly",
            "time": f"{int(hour):02d}:{int(minute):02d}",
            "day_of_month": int(dom),
        }

    return {"kind": "advanced", "cron": cron}


def humanize(config: Dict[str, Any] | ScheduleConfig, locale: str = "it") -> str:
    """Etichetta breve, leggibile, per la UI (italiano di default)."""
    if isinstance(config, dict):
        try:
            cfg = ScheduleConfig(**config)
        except Exception:
            return config.get("cron", "—")
    else:
        cfg = config

    if cfg.kind == "manual":
        return "Manuale (nessuna pianificazione)"

    if cfg.kind == "hourly":
        return f"Ogni ora al minuto :{(cfg.minute or 0):02d}"

    if cfg.kind == "every_n_hours":
        return f"Ogni {cfg.hours} ore al minuto :{(cfg.minute or 0):02d}"

    if cfg.kind == "daily":
        return f"Ogni giorno alle {cfg.time}"

    if cfg.kind == "every_n_days":
        return f"Ogni {cfg.days} giorni alle {cfg.time}"

    if cfg.kind == "weekly" and cfg.weekdays:
        labels = [WEEKDAY_LABELS_IT.get(d, d) for d in cfg.weekdays]
        if len(labels) == 7:
            days_str = "tutti i giorni"
        elif len(labels) == 1:
            days_str = labels[0]
        else:
            days_str = ", ".join(labels[:-1]) + f" e {labels[-1]}"
        return f"Ogni {days_str} alle {cfg.time}"

    if cfg.kind == "monthly":
        return f"Il giorno {cfg.day_of_month} di ogni mese alle {cfg.time}"

    if cfg.kind == "advanced":
        return f"Avanzato: {cfg.cron}"

    return "—"


def validate(config: Dict[str, Any] | ScheduleConfig) -> Tuple[bool, Optional[str]]:
    """True/False + messaggio. Non solleva: comodo per le UI."""
    try:
        to_cron(config)
        return True, None
    except Exception as e:
        return False, str(e)
