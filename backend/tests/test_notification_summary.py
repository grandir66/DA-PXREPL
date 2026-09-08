"""Il riepilogo deve far vedere subito quello che non va.

Il difetto da cui nasce (2026-09-08): era una tabella a sei colonne, e per
sapere se stanotte era andato storto qualcosa bisognava leggerla tutta —
«GUARDA QUANTO È LUNGO E COME È DIFFICILE LEGGERE LE COSE FONDAMENTALI».

Il guaio peggiore però non era la forma: un job **pianificato che non era
partito affatto** compariva verde, perché la sua ultima esecuzione — di tre
giorni prima — era andata bene. In un impianto di backup è il guasto più
grave possibile, e non produce nessun errore da leggere.
"""

import pytest

from services import mail_layout as ml
from services import notification_summary as r


def job(**kw):
    base = dict(
        name="job", type="sync", schedule="0 2 * * *", runs_24h=1, success_24h=1,
        failed_24h=0, duration_24h=60, last_status="success", last_run="08/09 02:00",
        notifica="daily", in_ritardo=False, esito_finale="success", tentativi_max=1,
    )
    base.update(kw)
    return base


def riepilogo(jobs, **kw):
    base = dict(impianto="Prova", total_runs=0, successful=0, failed=0, total_duration=0)
    base.update(kw)
    base["jobs"] = jobs
    return base


# --- il guasto silenzioso -------------------------------------------------

def test_un_job_pianificato_e_fermo_non_e_verde():
    """Ultima corsa riuscita, ma in 24 ore non è partito: è un guasto."""
    fermo = job(runs_24h=0, success_24h=0, in_ritardo=True, last_status="success", last_run="05/09 02:00")
    assert r._stato(fermo) == "fermo"
    assert ml.STATI["fermo"][1] == ml.AMBRA


def test_un_job_manuale_mai_partito_non_e_un_allarme():
    """Nessuno si aspetta che parta da solo: non deve gridare."""
    manuale = job(schedule="Manuale", runs_24h=0, success_24h=0, in_ritardo=False, last_status="never_run")
    assert r._stato(manuale) == "never_run"


def test_un_fallimento_vince_su_un_successo_successivo():
    """Male alle 2 e bene alle 6 resta da guardare: la replica di stanotte non c'è."""
    misto = job(runs_24h=4, success_24h=3, failed_24h=1, last_status="success")
    assert r._stato(misto) == "failed"


# --- ordine e colore: si trova il problema scorrendo il margine ------------

def test_i_guasti_vengono_per_primi():
    sezioni, _ = r.raggruppa([
        job(name="c-ok"),
        job(name="a-fermo", runs_24h=0, in_ritardo=True, last_run="05/09"),
        job(name="b-rotto", failed_24h=1),
    ])
    ordine = [j["name"] for j in sezioni[0]["jobs"]]
    assert ordine == ["b-rotto", "a-fermo", "c-ok"]


@pytest.mark.parametrize(
    "jobs,colore",
    [
        ([job(failed_24h=1)], ml.ROSSO),
        ([job(runs_24h=0, in_ritardo=True, last_run="05/09")], ml.AMBRA),
        ([job()], ml.VERDE),
        ([job(schedule="Manuale", runs_24h=0, in_ritardo=False, last_status="never_run")], ml.MUTED),
    ],
)
def test_il_colore_della_barra_dice_dove_guardare(jobs, colore):
    sezioni, _ = r.raggruppa(jobs)
    assert r._colore_sezione(sezioni[0]) == colore


# --- raggruppamento per tipologia -----------------------------------------

def test_le_tipologie_senza_job_non_compaiono():
    """Una sezione vuota occupa spazio e non dice niente."""
    sezioni, _ = r.raggruppa([job(type="sync"), job(type="backup")])
    assert [s["tipologia"].sigla for s in sezioni] == ["REPL-VM", "BACKUP"]


def test_una_tipologia_sconosciuta_non_sparisce():
    """Un `type` nuovo finisce sotto ALTRO, visibile: meglio brutto che assente."""
    sezioni, _ = r.raggruppa([job(type="tipo_inventato")])
    assert [s["tipologia"].sigla for s in sezioni] == ["ALTRO"]


def test_tutte_le_tipologie_del_prodotto_hanno_una_sigla():
    """Se qualcuno aggiunge un modulo e scorda la sigla, il riepilogo lo dice."""
    tipi_noti = {t.chiave for t in r.TIPOLOGIE}
    assert tipi_noti == {
        "sync", "vm_snapshot", "file_replication", "nas_sync",
        "backup", "recovery", "host_backup", "migration",
    }


# --- i silenziati restano silenziosi, non invisibili -----------------------

def test_never_esce_dal_riepilogo_ma_il_nome_resta():
    sezioni, esclusi = r.raggruppa([job(name="rumoroso"), job(name="zitto", notifica="never")])
    assert [j["name"] for j in sezioni[0]["jobs"]] == ["rumoroso"]
    assert esclusi == ["zitto"]
    html = r.render_html(riepilogo([job(name="zitto", notifica="never")]), impianto="Prova")
    assert "1 job escluso dalle notifiche" in html
    assert "zitto" in html


# --- forma: niente colonne, e il testo semplice dice le stesse cose --------

def test_le_attivita_non_sono_colonne():
    """La regressione da temere: il ritorno della tabella a sei colonne."""
    html = r.render_html(riepilogo([job(name="uno"), job(name="due")]), impianto="Prova")
    assert "<th" not in html


def test_i_kpi_a_zero_non_occupano_spazio():
    pulito = r.render_html(
        riepilogo([job()], total_runs=4, successful=4, failed=0, total_duration=120),
        impianto="Prova",
    )
    assert "FALLITE" not in pulito.upper()
    rotto = r.render_html(
        riepilogo([job(failed_24h=1)], total_runs=4, successful=3, failed=1, total_duration=120),
        impianto="Prova",
    )
    assert "Fallite" in rotto


def test_loggetto_della_mail_risponde_senza_aprirla():
    assert "2 su 24" in r.oggetto_mail(
        riepilogo([], total_runs=24, failed=2), impianto="DAPX"
    )
    assert "tutto regolare" in r.oggetto_mail(
        riepilogo([], total_runs=24, failed=0), impianto="DAPX"
    )
    assert "nessuna esecuzione" in r.oggetto_mail(
        riepilogo([], total_runs=0, failed=0), impianto="DAPX"
    )


def test_il_testo_semplice_dice_le_stesse_cose():
    dati = riepilogo(
        [job(name="rotto", vm_name="DA-DC01", vm_id=301, failed_24h=1,
             last_error="dataset is busy")],
        total_runs=4, successful=3, failed=1, total_duration=252,
    )
    testo = r.render_testo(dati, impianto="DAPX")
    html = r.render_html(dati, impianto="DAPX")
    for pezzo in ("DA-DC01 (301)", "dataset is busy"):
        assert pezzo in testo, pezzo
        assert pezzo in html, pezzo
    assert "Fallito" in testo


def test_telegram_mostra_solo_cio_che_non_va():
    msg = r.render_telegram(
        riepilogo([job(name="bene"), job(name="male", failed_24h=1)],
                  total_runs=2, successful=1, failed=1),
        impianto="DAPX",
    )
    assert "male" in msg
    assert "bene" not in msg


# --- niente dati, niente schianti -----------------------------------------

def test_un_riepilogo_vuoto_non_rompe():
    html = r.render_html(riepilogo([]), impianto="DAPX")
    assert "Nessuna attività" in html
    assert "None" not in html


def test_un_job_senza_campi_non_rompe():
    html = r.render_html(riepilogo([{"type": "sync"}]), impianto="DAPX")
    assert "senza nome" in html
    assert "None" not in html


@pytest.mark.parametrize(
    "secondi,atteso",
    [(0, ""), (None, ""), (45, "45s"), (1654, "27m 34s"), (11520, "3h 12m")],
)
def test_le_durate_si_leggono(secondi, atteso):
    assert r.durata_breve(secondi) == atteso


# --- «tutto regolare» si dice solo quando è vero ---------------------------
#
# Trovato sul primo riepilogo generato dai dati veri dell'impianto
# (2026-09-08): l'oggetto diceva «✅ 8 esecuzioni, tutto regolare» mentre
# dentro c'erano SEI repliche pianificate ferme, una da sei giorni. I conti
# guardavano solo le esecuzioni fallite — e un job che non parte non produce
# esecuzioni, quindi non ne produce nemmeno di fallite.

def test_i_job_fermi_contano_nelloggetto():
    fermo = job(runs_24h=0, success_24h=0, in_ritardo=True, last_run="02/09 03:03")
    oggetto = r.oggetto_mail(
        riepilogo([fermo], total_runs=8, successful=8, failed=0), impianto="DAPX"
    )
    assert "tutto regolare" not in oggetto
    assert "non è partito" in oggetto
    assert oggetto.startswith("⚠️")


def test_con_dei_fallimenti_i_fermi_si_aggiungono_non_si_sostituiscono():
    oggetto = r.oggetto_mail(
        riepilogo([job(failed_24h=1), job(runs_24h=0, in_ritardo=True, last_run="02/09")],
                  total_runs=8, successful=7, failed=1),
        impianto="DAPX",
    )
    assert oggetto.startswith("❌")
    assert "1 non partiti" in oggetto


def test_tutto_a_posto_resta_tutto_a_posto():
    oggetto = r.oggetto_mail(
        riepilogo([job()], total_runs=8, successful=8, failed=0), impianto="DAPX"
    )
    assert oggetto.startswith("✅") and "tutto regolare" in oggetto


def test_i_fermi_hanno_il_loro_numero_in_cima():
    html = r.render_html(
        riepilogo([job(runs_24h=0, in_ritardo=True, last_run="02/09")], total_runs=8, successful=8),
        impianto="DAPX",
    )
    assert "Non partiti" in html
    pulito = r.render_html(riepilogo([job()], total_runs=8, successful=8), impianto="DAPX")
    assert "Non partiti" not in pulito, "un contatore a zero non si mostra"


def test_il_testo_distingue_job_che_replicano_la_stessa_vm():
    """Tre job sulla stessa VM (dischi diversi) davano tre righe identiche."""
    testo = r.render_testo(
        riepilogo([
            job(name="seven-disk0", vm_name="DA-SEVEN", vm_id=404, source_dataset="zfs/vm-404-disk-0"),
            job(name="seven-disk1", vm_name="DA-SEVEN", vm_id=404, source_dataset="zfs/vm-404-disk-1"),
        ]),
        impianto="DAPX",
    )
    assert "zfs/vm-404-disk-0" in testo and "zfs/vm-404-disk-1" in testo


# --- fermo si dice al cron, non al calendario -----------------------------
#
# Il 2026-09-08 il riepilogo ha gridato «6 job pianificati non sono partiti»
# su un impianto in perfetta salute: erano repliche SETTIMANALI (lunedì,
# mercoledì, venerdì), tutte puntuali sul loro slot. La regola era «zero
# esecuzioni in 24 ore + ha un cron», che per un job settimanale è vera sei
# giorni su sette. Adesso lo decide `check_job_overdue` a monte.

def test_un_job_settimanale_fuori_dal_suo_giorno_non_e_fermo():
    settimanale = job(
        schedule="0 2 * * 1", runs_24h=0, success_24h=0,
        in_ritardo=False, last_status="success", last_run="07/09 02:05",
    )
    assert r._stato(settimanale) == "success"
    oggetto = r.oggetto_mail(
        riepilogo([settimanale], total_runs=8, successful=8), impianto="DAPX"
    )
    assert "tutto regolare" in oggetto, "allarme falso su un job settimanale puntuale"


def test_il_riepilogo_non_ricalcola_il_ritardo_per_conto_suo():
    """Una seconda definizione di «in ritardo» prima o poi contraddice la prima."""
    import inspect
    sorgente = inspect.getsource(r)
    assert "croniter" not in sorgente
    assert "prev_run_before" not in sorgente


# --- la riprova automatica ------------------------------------------------

def test_fallito_e_rientrato_alla_riprova_non_e_un_guasto():
    rientrato = job(runs_24h=2, success_24h=1, failed_24h=1,
                    esito_finale="success", tentativi_max=2,
                    last_error="dataset is busy")
    assert r._stato(rientrato) == "riprovato"
    assert ml.STATI["riprovato"][0] == "Riuscita alla riprova"


def test_ma_resta_scritto_nel_riepilogo():
    """Un job che ogni notte fallisce e rientra è un problema che matura."""
    html = r.render_html(
        riepilogo([job(name="ballerino", vm_name="DA-SEVEN", vm_id=404, runs_24h=2,
                       success_24h=1, failed_24h=1, esito_finale="success",
                       tentativi_max=2, last_error="dataset is busy")]),
        impianto="DAPX",
    )
    assert "Riuscita alla riprova" in html
    assert "dataset is busy" in html


def test_fallito_anche_alla_riprova_e_un_guasto():
    perso = job(runs_24h=2, success_24h=0, failed_24h=2,
                esito_finale="failed", tentativi_max=2, last_error="host unreachable")
    assert r._stato(perso) == "failed"


def test_un_successo_al_turno_dopo_non_e_una_riprova():
    """Male alle 2 e bene alle 6 di un ALTRO slot resta da guardare.

    Li distingue `attempt_number`: la riprova automatica scrive 2, uno slot
    cron nuovo riparte da 1.
    """
    altro_turno = job(runs_24h=2, success_24h=1, failed_24h=1,
                      esito_finale="success", tentativi_max=1)
    assert r._stato(altro_turno) == "failed"


def test_i_riprovati_non_contano_come_fallimenti_nelloggetto():
    oggetto = r.oggetto_mail(
        riepilogo([job(runs_24h=2, success_24h=1, failed_24h=1,
                       esito_finale="success", tentativi_max=2)],
                  total_runs=2, successful=1, failed=0),
        impianto="DAPX",
    )
    assert oggetto.startswith("✅")
