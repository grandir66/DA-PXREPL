"""Test chiavi scheduler in-memory per SyncJob / VM group."""

from datetime import datetime, timezone

from zoneinfo import ZoneInfo

from services.scheduler import SchedulerService, compute_initial_next_run


def test_compute_initial_next_run_weekly_no_stale():
    """Al riavvio non si spara la settimana arretrata: si va al prossimo slot.

    Il valore atteso NON è scritto a mano. Il contratto (dichiarato in
    `services/cron_tz.py`) è: il cron si legge in ORA LOCALE, il valore
    restituito è UTC naive. Un `datetime(2026, 7, 20, 2, 0)` scritto qui
    dentro sarebbe vero solo d'estate a Roma: questo test lo era, ed è
    rimasto rosso dalla 3.20.10 in poi — quando il cron è passato all'ora
    locale — senza che nessuno lo leggesse, perché diceva «2:00» e sembrava
    giusto. Adesso l'attesa si costruisce dal fuso, quindi resta vera in
    inverno, e con `DAPX_SCHEDULER_TZ` impostato a qualcos'altro.
    """
    from services import scheduler as modulo

    lunedi_locale = datetime(2026, 7, 20, 2, 0, 0, tzinfo=modulo._SCHEDULER_TZ)
    atteso = lunedi_locale.astimezone(timezone.utc).replace(tzinfo=None)

    now = datetime(2026, 7, 16, 10, 0, 0)
    nxt = compute_initial_next_run("0 2 * * 1", datetime(2026, 6, 30, 3, 0, 0), now)
    assert nxt == atteso


def test_il_cron_si_legge_in_ora_locale_non_in_utc():
    """La regressione da cui nasce il fuso: gli slot calcolati in UTC.

    Sfasavano di N ore e facevano gridare «replica in ritardo» a job
    regolarmente eseguiti (3.20.15). Con Europe/Rome d'estate lo scarto è di
    due ore, e questo test lo pretende esplicitamente invece di darlo per
    scontato in un numero.
    """
    roma = ZoneInfo("Europe/Rome")
    from services import scheduler as modulo

    if modulo._SCHEDULER_TZ.key != "Europe/Rome":
        import pytest

        pytest.skip("DAPX_SCHEDULER_TZ non è Europe/Rome in questo ambiente")

    now = datetime(2026, 7, 16, 10, 0, 0)
    nxt = compute_initial_next_run("0 2 * * 1", datetime(2026, 6, 30, 3, 0, 0), now)
    in_locale = nxt.replace(tzinfo=timezone.utc).astimezone(roma)
    assert (in_locale.hour, in_locale.minute) == (2, 0)
    assert nxt.hour == 0, "d'estate le 02:00 di Roma sono mezzanotte UTC"


def test_update_vm_group_schedule_uses_vmgroup_key():
    svc = SchedulerService()
    svc.update_vm_group_schedule("abc123", "0 2 * * *")
    assert "vmgroup_abc123" in svc._jobs
    assert "abc123" not in svc._jobs


def test_update_job_schedule_routes_to_vmgroup_when_set():
    svc = SchedulerService()
    svc.update_job_schedule(99, "0 3 * * *", vm_group_id="grp1")
    assert "vmgroup_grp1" in svc._jobs
    assert "sync_99" not in svc._jobs


def test_remove_vm_group_schedule():
    svc = SchedulerService()
    svc.update_vm_group_schedule("grp1", "0 2 * * *")
    svc.remove_vm_group_schedule("grp1")
    assert "vmgroup_grp1" not in svc._jobs
