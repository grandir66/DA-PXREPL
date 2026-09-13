"""Backup config host con `schedule = 'daily'`: non partivano MAI.

DTS, 2026-09-13: tre job «Backup Config» (uno per nodo PVE) con la parola
`daily` al posto di un cron. Lo scheduler la scartava a ogni avvio
(«Cron non valido 'daily': job non schedulato») e i backup risalivano a
luglio e agosto. Nessuno lo vedeva: un job che non parte non fallisce.
"""

from __future__ import annotations

import pytest
from croniter import croniter

from update_db_schema import cron_da_parola


@pytest.mark.parametrize("parola,indice,atteso", [
    ("daily", 0, "0 1 * * *"),
    ("daily", 1, "10 1 * * *"),     # scaglionati di dieci minuti per non partire insieme
    ("DAILY ", 2, "20 1 * * *"),
    ("weekly", 0, "0 1 * * 0"),
    ("hourly", 0, "0 * * * *"),
])
def test_le_parole_legacy_diventano_cron_validi(parola, indice, atteso):
    cron = cron_da_parola(parola, indice)
    assert cron == atteso
    assert croniter.is_valid(cron)


@pytest.mark.parametrize("valore", ["0 1 * * *", "", None, "boh"])
def test_un_cron_vero_o_un_valore_ignoto_non_si_toccano(valore):
    assert cron_da_parola(valore, 0) is None


def test_la_migrazione_converte_solo_le_parole(tmp_path, monkeypatch):
    import sqlite3
    db = tmp_path / "t.db"
    c = sqlite3.connect(db)
    c.execute("create table host_backup_jobs (id integer primary key, name text, schedule text, schedule_config text)")
    c.executemany("insert into host_backup_jobs values (?,?,?,?)", [
        (1, "a", "daily", None), (2, "b", "daily", None), (3, "c", "30 4 * * *", None), (4, "d", None, None),
    ])
    c.commit(); c.close()

    from update_db_schema import migra_schedule_legacy
    from sqlalchemy import create_engine
    eng = create_engine(f"sqlite:///{db}")
    with eng.connect() as conn:
        n = migra_schedule_legacy(conn)
        conn.commit()
    assert n == 2
    c = sqlite3.connect(db)
    righe = dict(c.execute("select id, schedule from host_backup_jobs"))
    assert righe == {1: "0 1 * * *", 2: "10 1 * * *", 3: "30 4 * * *", 4: None}


def test_il_router_rifiuta_una_pianificazione_che_non_e_cron():
    from pydantic import ValidationError
    from routers.host_backup import HostBackupJobCreate, HostBackupJobUpdate
    with pytest.raises(ValidationError):
        HostBackupJobCreate(name="x", node_id=1, schedule="daily")
    with pytest.raises(ValidationError):
        HostBackupJobUpdate(schedule="ogni giorno")
    assert HostBackupJobCreate(name="x", node_id=1, schedule="0 1 * * *").schedule == "0 1 * * *"
    assert HostBackupJobUpdate(schedule="").schedule is None
