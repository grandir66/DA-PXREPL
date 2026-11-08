"""Pool di connessioni esaurito a DTS (8 novembre 2026, 15:00).

Dodici gruppi di replica lanciati insieme: ogni `execute_sync_job_task` apre
una sessione SQLAlchemy e la tiene per tutto il trasferimento syncoid, il pool
(5 + 10) si è esaurito. Cinque gruppi sono morti in background senza lasciare
una riga nel registro, il «/run» del backup config ha dato 500 e la
registrazione post-sync della VM 117 è saltata.

1. Le repliche contemporanee hanno un tetto: le altre aspettano in coda PRIMA
   di aprire la sessione.
2. Un avvio in background che muore lo dice nel log.
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import patch

import pytest

import services.sync_job_execution as sje


@pytest.mark.asyncio
async def test_repliche_contemporanee_hanno_un_tetto():
    stato = {"in_volo": 0, "max": 0}

    async def finto(job_id, triggered_by_user_id=None, tentativo=1, replica_completa=False):
        stato["in_volo"] += 1
        stato["max"] = max(stato["max"], stato["in_volo"])
        await asyncio.sleep(0.02)
        stato["in_volo"] -= 1
        return False

    with patch.object(sje.execute_sync_job_task, "__wrapped__", finto):
        risultati = await asyncio.gather(*(sje.execute_sync_job_task(i) for i in range(12)))

    assert risultati == [False] * 12
    assert stato["max"] <= sje.MAX_REPLICHE_CONTEMPORANEE, f"{stato['max']} repliche insieme"
    assert stato["max"] == sje.MAX_REPLICHE_CONTEMPORANEE, "la coda non deve serializzare tutto"


@pytest.mark.asyncio
async def test_gruppo_in_background_che_muore_lo_dice_nel_log(caplog):
    import services.vm_group_sync_service as vg

    async def esplode(*a, **kw):
        raise RuntimeError("QueuePool limit of size 5 overflow 10 reached")

    with patch.object(vg, "execute_vm_group_sync_task", esplode), \
         patch.object(vg.scheduler_service, "mark_done") as fatto, \
         caplog.at_level(logging.ERROR):
        await vg.run_vm_group_background("gruppo-x", "vm_group_gruppo-x")

    fatto.assert_called_once_with("vm_group_gruppo-x")
    assert any("gruppo-x" in r.getMessage() and r.levelno >= logging.ERROR for r in caplog.records)
