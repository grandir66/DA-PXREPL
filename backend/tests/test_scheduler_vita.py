"""Vita dello scheduler (3.24.0): tetto per check, battito, «stale» nel health.

dts-repl, 21/09/2026 15:52:04: il loop si e' bloccato dentro
`update_host_details` (SSH a un nodo durante una tempesta L2) e per nove ore
non ha fatto niente — niente corse, niente cache, niente errori — mentre
`/api/health` diceva `scheduler: running`. Qui: un check che dorme oltre il
suo tetto viene abbandonato e il giro prosegue; due scadenze di fila danno
un warning (uno al giorno); il battito avanza; un battito vecchio rende il
health `degraded`.
"""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from database import SystemConfig


def _scheduler():
    from services.scheduler import SchedulerService
    return SchedulerService()


@pytest.mark.asyncio
async def test_un_check_che_non_finisce_viene_abbandonato_e_il_giro_prosegue(db):
    sched = _scheduler()
    eseguiti = []

    async def bloccato():
        await asyncio.sleep(10)

    async def veloce():
        eseguiti.append("veloce")

    sched._check_bloccato = bloccato
    sched._check_veloce = veloce
    with patch("services.scheduler.SessionLocal", return_value=db):
        ok1 = await sched._esegui_check("bloccato", "_check_bloccato", 0.05)
        ok2 = await sched._esegui_check("veloce", "_check_veloce", 5)
        sched._battito()
    assert ok1 is False and ok2 is True
    assert eseguiti == ["veloce"]
    assert sched._scadenze["bloccato"] == 1 and sched._scadenze["veloce"] == 0
    assert sched.last_tick is not None
    cfg = db.query(SystemConfig).filter(SystemConfig.key == "scheduler_last_tick").first()
    assert cfg and cfg.value.startswith(sched.last_tick.isoformat()[:16])


@pytest.mark.asyncio
async def test_due_scadenze_di_fila_un_avviso_solo(db):
    sched = _scheduler()

    async def bloccato():
        await asyncio.sleep(10)

    sched._check_bloccato = bloccato
    invio = AsyncMock(return_value={"sent": True})
    with patch("services.scheduler.notification_service.send_job_notification", invio):
        for _ in range(4):
            await sched._esegui_check("bloccato", "_check_bloccato", 0.02)
    invio.assert_awaited_once()
    kw = invio.await_args.kwargs
    assert kw["status"] == "warning" and "bloccato" in kw["job_name"]
    assert sched._scadenze["bloccato"] == 4


@pytest.mark.asyncio
async def test_il_check_che_torna_azzera_il_conteggio(db):
    sched = _scheduler()
    stato = {"lento": True}

    async def check():
        if stato["lento"]:
            await asyncio.sleep(10)

    sched._check_x = check
    await sched._esegui_check("x", "_check_x", 0.02)
    assert sched._scadenze["x"] == 1
    stato["lento"] = False
    await sched._esegui_check("x", "_check_x", 1)
    assert sched._scadenze["x"] == 0


@pytest.mark.asyncio
async def test_un_errore_in_un_check_non_ferma_il_giro():
    sched = _scheduler()

    async def rotto():
        raise RuntimeError("boom")

    sched._check_rotto = rotto
    assert await sched._esegui_check("rotto", "_check_rotto", 5) is False


def test_i_check_del_loop_sono_tutti_metodi_veri_con_un_tetto():
    """La lista CHECKS e' il loop: ogni voce deve esistere e avere un tetto sensato."""
    sched = _scheduler()
    nomi = [n for n, _, _ in sched.CHECKS]
    assert len(nomi) == len(set(nomi)) >= 9
    for nome, metodo, tetto in sched.CHECKS:
        assert callable(getattr(sched, metodo)), metodo
        assert 60 <= tetto <= 900, (nome, tetto)


def test_health_stale_quando_il_battito_e_vecchio(client):
    from main import scheduler

    scheduler.last_tick = datetime.utcnow() - timedelta(minutes=20)
    try:
        r = client.get("/api/health")
        assert r.status_code == 503
        body = r.json()
        assert body["status"] == "degraded"
        assert body["checks"]["scheduler"].startswith("stale (")
        assert body["scheduler_last_tick"]
    finally:
        scheduler.last_tick = None


def test_health_running_con_battito_fresco(client):
    from main import scheduler

    scheduler.last_tick = datetime.utcnow() - timedelta(minutes=2)
    try:
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["checks"]["scheduler"] == "running"
    finally:
        scheduler.last_tick = None
