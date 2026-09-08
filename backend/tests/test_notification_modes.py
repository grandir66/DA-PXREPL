"""Le notifiche devono fare quel che l'interfaccia promette.

Il 2026-09-08 l'etichetta del menu diceva «Riepilogo giornaliero» e il codice
mandava invece una mail SUBITO per ogni job — al massimo una al giorno per i
successi, ma comunque una per job — mentre il riepilogo partiva lo stesso.
Con l'impostazione predefinita arrivavano quindi entrambe le cose.

Questi test tengono ferme le quattro modalità. Se qualcuno rimette la mail
immediata sotto `daily`, il cancello si accorge del ritorno del difetto.
"""

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from services.notification_service import NotificationService


class _ConfigFinta:
    """Tutti i canali accesi e tutti gli stati notificabili.

    Se qualcosa non parte in queste condizioni, è la modalità del job ad
    averlo deciso — non un interruttore globale spento.
    """

    smtp_enabled = True
    webhook_enabled = False
    telegram_enabled = False
    smtp_host = "smtp.test"
    smtp_port = 25
    smtp_user = None
    smtp_password = None
    smtp_from = "dapx@test"
    smtp_to = "a@test"
    smtp_subject_prefix = "[DAPX]"
    smtp_tls = False
    notify_on_success = True
    notify_on_failure = True
    notify_on_warning = True


@pytest.fixture
def servizio(monkeypatch):
    s = NotificationService()
    monkeypatch.setattr(s, "_load_config", lambda: _ConfigFinta())
    monkeypatch.setattr(s, "_configure_email_service", lambda config: None)
    inviate = []

    from services import notification_service as modulo

    monkeypatch.setattr(
        modulo.email_service,
        "send_job_notification",
        lambda **kw: (inviate.append(kw), (True, "ok"))[1],
    )
    s.inviate = inviate
    return s


def _notifica(servizio, **kw):
    base = dict(
        job_name="repl-test", status="success", source="a", destination="b",
        job_id=1, job_type="sync",
    )
    base.update(kw)
    return asyncio.run(servizio.send_job_notification(**base))


@pytest.mark.parametrize("stato", ["success", "failed", "warning"])
def test_daily_non_manda_mai_una_mail_immediata(servizio, stato):
    """Il cuore della faccenda: «solo nel riepilogo» vuol dire SOLO.

    Vale anche per i fallimenti — deciso dall'utente il 2026-09-08: chi vuole
    l'avviso al volo su un guasto imposta il job su «failure».
    """
    esito = _notifica(servizio, notify_mode="daily", status=stato)
    assert esito["sent"] is False
    assert esito["reason"] == "notify_mode_daily"
    assert servizio.inviate == []


@pytest.mark.parametrize("stato", ["success", "failed", "warning"])
def test_never_non_manda_niente(servizio, stato):
    esito = _notifica(servizio, notify_mode="never", status=stato)
    assert esito["sent"] is False
    assert servizio.inviate == []


def test_always_manda_a_ogni_esecuzione(servizio):
    for _ in range(3):
        _notifica(servizio, notify_mode="always")
    assert len(servizio.inviate) == 3


def test_failure_manda_solo_i_guasti(servizio):
    _notifica(servizio, notify_mode="failure", status="success")
    assert servizio.inviate == []
    _notifica(servizio, notify_mode="failure", status="failed")
    assert len(servizio.inviate) == 1


def test_always_non_e_piu_limitato_a_una_al_giorno(servizio):
    """Il vecchio contatore per job è sparito insieme alla mail per job.

    Restava un attributo che non contava più niente: un depistaggio per chi
    legge, e un test che passava per il motivo sbagliato.
    """
    assert not hasattr(servizio, "_daily_job_notifications")
    for _ in range(5):
        _notifica(servizio, notify_mode="always", job_id=7)
    assert len(servizio.inviate) == 5


def test_lallarme_replica_in_ritardo_resta_immediato(servizio, monkeypatch):
    """Un allarme non è un rapporto: quello continua a partire subito.

    È l'unica notifica che scavalca il riepilogo, e deve restare tale — dice
    che una replica NON è avvenuta, cosa che il riepilogo di domattina
    direbbe troppo tardi.
    """
    esito = asyncio.run(
        servizio.send_replication_overdue_alert(
            [{"vm_name": "DA-DC01", "vm_id": 301, "missed_slots": 3,
              "last_run": "05/09 02:00", "hours_since_last_run": 76.5}]
        )
    )
    assert esito.get("sent") is True
    assert len(servizio.inviate) == 1
