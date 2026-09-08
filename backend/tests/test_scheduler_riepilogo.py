"""Il riepilogo giornaliero non si perde per un SMTP giù cinque minuti.

Dall'8 settembre 2026 i job non mandano più posta per conto loro: il riepilogo
è l'unico messaggio che arriva quando tutto va come deve. Perderlo vuol dire
non sapere niente per 24 ore — e prima si perdeva facilmente, perché lo
scheduler segnava la giornata come «fatta» appena aveva PROVATO a mandarlo.

`send_daily_summary` restituisce `sent: True` non appena decide di provarci;
se poi il canale email fallisce lo dice solo dentro `channels`. Leggere il
primo e non i secondi è il difetto che questi test tengono chiuso.
"""

import asyncio

import pytest

from services.scheduler import (
    _MAX_TENTATIVI_RIEPILOGO,
    SchedulerService,
    _riepilogo_consegnato,
)


@pytest.mark.parametrize(
    "risultato,atteso",
    [
        ({"sent": True, "channels": {"email": {"success": True}}}, True),
        # Il caso del difetto: `sent` è True, ma nessuno l'ha preso.
        ({"sent": True, "channels": {"email": {"success": False}}}, False),
        ({"sent": True, "channels": {"email": {"success": False},
                                     "telegram": {"success": True}}}, True),
        # Niente da mandare: ritentare non cambierebbe nulla.
        ({"sent": False, "reason": "no_jobs_configured"}, None),
        ({"sent": False, "reason": "not_configured"}, None),
        ({"sent": True, "channels": {}}, None),
    ],
)
def test_si_capisce_se_e_arrivato_a_qualcuno(risultato, atteso):
    assert _riepilogo_consegnato(risultato) is atteso


def _scheduler(monkeypatch, risultati):
    """Uno scheduler fermo all'ora del riepilogo, con esiti d'invio pilotati."""
    s = SchedulerService()
    s._daily_summary_enabled = True
    s._daily_summary_hour = 8
    monkeypatch.setattr(s, "_load_daily_summary_config", lambda: None)

    from services import scheduler as modulo
    from datetime import datetime

    class _Orologio(datetime):
        @classmethod
        def utcnow(cls):
            return datetime(2026, 9, 8, 8, 0, 0)

    monkeypatch.setattr(modulo, "datetime", _Orologio)

    chiamate = []

    async def finto():
        chiamate.append(1)
        return risultati[min(len(chiamate) - 1, len(risultati) - 1)]

    monkeypatch.setattr(modulo.notification_service, "send_daily_summary", finto)
    s.chiamate = chiamate
    return s


def test_un_invio_riuscito_chiude_la_giornata(monkeypatch):
    s = _scheduler(monkeypatch, [{"sent": True, "channels": {"email": {"success": True}}}])
    asyncio.run(s._check_daily_summary())
    assert len(s.chiamate) == 1
    assert s._last_daily_summary is not None

    asyncio.run(s._check_daily_summary())
    assert len(s.chiamate) == 1, "inviato due volte nello stesso giorno"


def test_un_invio_fallito_non_brucia_la_giornata(monkeypatch):
    """Il difetto: bastava un SMTP giù per non ricevere niente fino a domani."""
    s = _scheduler(monkeypatch, [{"sent": True, "channels": {"email": {"success": False}}}])
    asyncio.run(s._check_daily_summary())
    assert s._last_daily_summary is None, "giornata chiusa senza aver consegnato niente"
    assert s._tentativi_riepilogo == 1


def test_lo_smtp_che_torna_su_fa_arrivare_il_riepilogo(monkeypatch):
    s = _scheduler(monkeypatch, [
        {"sent": True, "channels": {"email": {"success": False}}},
        {"sent": True, "channels": {"email": {"success": False}}},
        {"sent": True, "channels": {"email": {"success": True}}},
    ])
    for _ in range(3):
        asyncio.run(s._check_daily_summary())
    assert len(s.chiamate) == 3
    assert s._last_daily_summary is not None
    assert s._tentativi_riepilogo == 0


def test_non_si_martella_un_canale_morto_per_un_ora(monkeypatch):
    """Dopo N tentativi ci si arrende, ma lasciando un ERROR nel log."""
    s = _scheduler(monkeypatch, [{"sent": True, "channels": {"email": {"success": False}}}])
    for _ in range(_MAX_TENTATIVI_RIEPILOGO + 5):
        asyncio.run(s._check_daily_summary())
    assert len(s.chiamate) == _MAX_TENTATIVI_RIEPILOGO
    assert s._last_daily_summary is not None


def test_niente_da_mandare_non_e_un_fallimento(monkeypatch):
    """Nessun job configurato: la giornata si chiude, senza ritentare."""
    s = _scheduler(monkeypatch, [{"sent": False, "reason": "no_jobs_configured"}])
    asyncio.run(s._check_daily_summary())
    asyncio.run(s._check_daily_summary())
    assert len(s.chiamate) == 1
    assert s._last_daily_summary is not None


def test_uneccezione_vale_come_fallimento(monkeypatch):
    """Se l'invio esplode, si ritenta: non si perde la giornata in silenzio."""
    s = SchedulerService()
    s._daily_summary_enabled = True
    s._daily_summary_hour = 8
    monkeypatch.setattr(s, "_load_daily_summary_config", lambda: None)

    from datetime import datetime

    from services import scheduler as modulo

    class _Orologio(datetime):
        @classmethod
        def utcnow(cls):
            return datetime(2026, 9, 8, 8, 0, 0)

    monkeypatch.setattr(modulo, "datetime", _Orologio)

    async def esplode():
        raise RuntimeError("smtp irraggiungibile")

    monkeypatch.setattr(modulo.notification_service, "send_daily_summary", esplode)
    asyncio.run(s._check_daily_summary())
    assert s._last_daily_summary is None
    assert s._tentativi_riepilogo == 1
