"""Allarme «replica in ritardo» leggibile per i job che NON girano ogni giorno.

DTS, 2026-09-13: la mail diceva «VM-109: 1 slot saltati, ritardo 189.6h,
ultima run 2026-09-05T17:02:59, prossima 2026-09-14T17:00:00» — orari UTC in
ISO, nessuna cadenza, nessun disco. Per un job che gira lunedì, giovedì e
sabato, «189 ore» non dice se è un ritardo o la normalità. E con il ri-allarme
ogni 6 ore un settimanale in ritardo mandava 28 mail prima del suo slot.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.replication_health_service import (
    OVERDUE_ALERT_COOLDOWN_HOURS,
    build_schedule_groups,
    descrivi_gruppo_in_ritardo,
    enrich_job_schedule_info,
)


def _job(id, disk, schedule, last_run, name="VM-109"):
    j = MagicMock()
    j.id = id; j.name = f"{name} {disk}"; j.sync_method = "syncoid"; j.vm_id = 109
    j.vm_name = name; j.vm_group_id = "g109"; j.disk_name = disk
    j.schedule = schedule; j.last_run = last_run; j.last_status = "success"; j.is_active = True
    return j


# now: domenica 13/09/2026 14:50 UTC (16:50 locali). Slot lun/gio/sab 19:00 locali.
NOW = datetime(2026, 9, 13, 14, 50)
CRON = "0 19 * * 1,4,6"


def _gruppo():
    jobs = [
        enrich_job_schedule_info(_job(15, "scsi1", CRON, datetime(2026, 9, 12, 17, 1)), now=NOW),
        enrich_job_schedule_info(_job(16, "scsi2", CRON, datetime(2026, 9, 5, 17, 2)), now=NOW),
        enrich_job_schedule_info(_job(17, "scsi3", CRON, datetime(2026, 9, 5, 17, 3)), now=NOW),
    ]
    (g,) = build_schedule_groups(jobs)
    return g


def test_il_gruppo_porta_slot_atteso_e_dischi_fermi():
    g = _gruppo()
    assert g["overdue"] is True
    assert g["overdue_disks"] == ["scsi2", "scsi3"]
    # slot atteso = sabato 12/09 19:00 locali = 17:00 UTC
    assert g["expected_slot"] == "2026-09-12T17:00:00"


def test_la_descrizione_e_in_ora_locale_con_cadenza_e_dischi():
    testo = descrivi_gruppo_in_ritardo(_gruppo())
    assert "VM-109" in testo
    assert "lunedì, giovedì e sabato alle 19:00" in testo
    assert "sab 12/09 19:00" in testo          # slot atteso, ora locale
    assert "lun 14/09 19:00" in testo          # prossimo slot
    assert "scsi2, scsi3" in testo
    assert "sab 05/09 19:02 (7 giorni fa)" in testo   # dei dischi FERMI, non di scsi1
    assert "T17:00" not in testo               # niente ISO UTC


def test_cooldown_di_un_giorno():
    assert OVERDUE_ALERT_COOLDOWN_HOURS == 24


def _scheduler_con(report, ultimo_alert: datetime | None, chiavi_precedenti: str | None):
    from services.scheduler import SchedulerService
    sched = SchedulerService()
    db = MagicMock()
    righe = {}
    if ultimo_alert is not None:
        righe["replication_overdue_last_alert"] = MagicMock(value=ultimo_alert.isoformat())
    if chiavi_precedenti is not None:
        righe["replication_overdue_last_alert_keys"] = MagicMock(value=chiavi_precedenti)

    def first_per_chiave():
        # l'ordine delle query nel codice: prima last_alert, poi keys
        return [righe.get("replication_overdue_last_alert"), righe.get("replication_overdue_last_alert_keys")]
    db.query.return_value.filter.return_value.first.side_effect = first_per_chiave()
    db.query.return_value.filter.return_value.all.return_value = []
    return sched, db


@pytest.mark.asyncio
async def test_dentro_il_cooldown_non_rimanda_gli_stessi_gruppi():
    report = {"overdue_group_count": 1, "overdue_groups": [{"key": "group:g109"}]}
    sched, db = _scheduler_con(report, datetime.utcnow() - timedelta(hours=2), "group:g109")
    invio = AsyncMock(return_value={"sent": True, "channels": {}})
    with patch("services.scheduler.SessionLocal", return_value=db), \
         patch("services.replication_health_service.build_replication_health_report", return_value=report), \
         patch("services.scheduler.notification_service.send_replication_overdue_alert", invio):
        await sched._check_replication_overdue()
    invio.assert_not_awaited()


@pytest.mark.asyncio
async def test_dentro_il_cooldown_un_gruppo_nuovo_fa_rimandare():
    report = {"overdue_group_count": 2, "overdue_groups": [{"key": "group:g109"}, {"key": "group:g101"}]}
    sched, db = _scheduler_con(report, datetime.utcnow() - timedelta(hours=2), "group:g109")
    invio = AsyncMock(return_value={"sent": True, "channels": {}})
    with patch("services.scheduler.SessionLocal", return_value=db), \
         patch("services.replication_health_service.build_replication_health_report", return_value=report), \
         patch("services.scheduler.notification_service.send_replication_overdue_alert", invio):
        await sched._check_replication_overdue()
    invio.assert_awaited_once()
