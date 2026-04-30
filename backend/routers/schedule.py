"""
Schedule API
------------
Endpoint di supporto per la UI: round-trip ScheduleConfig <-> cron e
preview delle prossime esecuzioni. Stateless — non tocca il DB.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from croniter import croniter
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from routers.auth import get_current_user, User  # type: ignore
from fastapi import Depends
from services.schedule_translator import (
    ScheduleConfig,
    from_cron,
    humanize,
    to_cron,
    validate,
)


router = APIRouter()


class TranslateRequest(BaseModel):
    config: Optional[Dict[str, Any]] = None
    cron: Optional[str] = None


class TranslateResponse(BaseModel):
    config: Dict[str, Any]
    cron: Optional[str]
    human: str
    valid: bool
    error: Optional[str] = None
    next_runs: List[str] = []


@router.post("/translate", response_model=TranslateResponse)
async def translate(
    body: TranslateRequest,
    user: User = Depends(get_current_user),
) -> TranslateResponse:
    """Round-trip ScheduleConfig <-> cron string.

    Accetta uno *o* l'altro:
      - `config`: struttura JSON → ritorna cron + human + next_runs
      - `cron`:   cron raw         → ritorna config + human + next_runs

    `next_runs` contiene fino a 5 prossime esecuzioni in ISO UTC.
    """
    if body.config is None and not body.cron:
        raise HTTPException(status_code=400, detail="Fornire 'config' o 'cron'")

    cron_out: Optional[str] = None
    config_out: Dict[str, Any]
    err: Optional[str] = None

    if body.config is not None:
        try:
            config_out = ScheduleConfig(**body.config).model_dump(exclude_none=True)
        except Exception as e:
            return TranslateResponse(
                config=body.config,
                cron=None,
                human="—",
                valid=False,
                error=f"config non valida: {e}",
            )
        ok, e = validate(config_out)
        if not ok:
            return TranslateResponse(
                config=config_out,
                cron=None,
                human=humanize(config_out),
                valid=False,
                error=e,
            )
        cron_out = to_cron(config_out)
    else:
        cron_out = (body.cron or "").strip() or None
        if cron_out and not croniter.is_valid(cron_out):
            return TranslateResponse(
                config={"kind": "advanced", "cron": cron_out},
                cron=cron_out,
                human=f"Avanzato: {cron_out}",
                valid=False,
                error="cron non valido",
            )
        config_out = from_cron(cron_out)

    next_runs: List[str] = []
    if cron_out:
        try:
            it = croniter(cron_out, datetime.utcnow())
            for _ in range(5):
                next_runs.append(it.get_next(datetime).isoformat() + "Z")
        except Exception as e:  # pragma: no cover - cron invalido già filtrato
            err = f"errore preview: {e}"

    return TranslateResponse(
        config=config_out,
        cron=cron_out,
        human=humanize(config_out),
        valid=True,
        error=err,
        next_runs=next_runs,
    )
