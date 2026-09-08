"""Il riepilogo giornaliero: raggruppato per tipologia, non un elenco piatto.

`send_daily_summary` in `notification_service` raccoglie i dati — una riga per
job, con i conti delle ultime 24 ore. Qui si decide **come si leggono**.

Prima era una tabella a sei colonne (Job | Sorgente | Destinazione | Stato |
24h | Durata), e su un telefono si accartocciava; per sapere se stanotte era
andato storto qualcosa bisognava leggerla tutta. Adesso:

* i numeri in cima rispondono in due secondi (quante esecuzioni, quante
  fallite): se non c'è niente di rosso, la mail si chiude lì;
* le attività sono raggruppate per **tipologia** — REPL-VM, DATI, BACKUP… —
  perché è così che l'utente pensa al proprio impianto, e la sigla dice da
  quale sistema arriva lo stato;
* dentro ogni tipologia **i guasti vengono per primi**, e la barra della
  sezione diventa rossa: si trova il problema scorrendo il margine;
* quello che NON è successo si vede: un job attivo che in 24 ore non è mai
  partito è la cosa più pericolosa che possa capitare a un impianto di
  backup, e in una tabella di righe verdi non si notava.

Una mail per installazione (il nome viene da `cluster_name`), non una per
job: l'impostazione predefinita dei job è «solo nel riepilogo», quindi questo
messaggio è l'unico che arriva quando tutto va come deve.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from services import mail_layout as ml


@dataclass(frozen=True)
class Tipologia:
    """Una famiglia di attività, con la sigla che compare nel messaggio.

    `chiave` è il `type` che il raccoglitore mette in ogni riga; `sigla` è
    come la chiamiamo noi parlando dell'impianto. Sono due cose diverse
    apposta: la chiave segue il codice, la sigla segue chi legge.
    """

    chiave: str
    sigla: str
    descrizione: str


# L'ordine è quello in cui compaiono nella mail: prima ciò che gira ogni
# notte e che deve essere andato bene, poi le operazioni occasionali.
TIPOLOGIE: tuple[Tipologia, ...] = (
    Tipologia("sync", "REPL-VM", "Replica VM (ZFS/BTRFS)"),
    Tipologia("vm_snapshot", "SNAPSHOT", "Snapshot VM pianificati"),
    Tipologia("file_replication", "DATI", "Replica file e cartelle"),
    Tipologia("nas_sync", "NAS", "Sincronizzazione verso NAS"),
    Tipologia("backup", "BACKUP", "Backup su Proxmox Backup Server"),
    Tipologia("recovery", "RECOVERY", "Recovery PBS (backup + restore)"),
    Tipologia("host_backup", "HOST", "Backup della configurazione host"),
    Tipologia("migration", "MIGRAZIONE", "Migrazione live fra nodi"),
)

_PER_CHIAVE = {t.chiave: t for t in TIPOLOGIE}
_SCONOSCIUTA = Tipologia("", "ALTRO", "Attività non classificate")

# Chi sta peggio si legge per primo. Un job attivo mai partito conta come
# guasto in attesa di essere scoperto, non come riga neutra in fondo.
_PESO_STATO = {
    "failed": 0, "fermo": 1, "warning": 2, "riprovato": 3,
    "never_run": 4, "running": 5, "success": 6,
}


def tipologia(chiave: str | None) -> Tipologia:
    return _PER_CHIAVE.get(chiave or "", _SCONOSCIUTA)


def durata_breve(secondi: int | float | None) -> str:
    """`1h 04m` / `27m 34s` / `12s`. Sotto il minuto i secondi contano."""
    s = int(secondi or 0)
    if s <= 0:
        return ""
    ore, resto = divmod(s, 3600)
    minuti, sec = divmod(resto, 60)
    if ore:
        return f"{ore}h {minuti:02d}m"
    if minuti:
        return f"{minuti}m {sec:02d}s"
    return f"{sec}s"


def _riuscito_alla_riprova(job: dict[str, Any]) -> bool:
    """È fallito e la riprova automatica l'ha rimesso a posto.

    Non è un guasto — il sistema si è aggiustato da solo — ma non è nemmeno
    silenzio: un job che ogni notte fallisce e rientra alla seconda è un
    problema che sta maturando, e nel silenzio non lo si vedrebbe.
    """
    return (
        int(job.get("failed_24h") or 0) > 0
        and int(job.get("success_24h") or 0) > 0
        and int(job.get("tentativi_max") or 1) > 1
        and str(job.get("esito_finale") or "") == "success"
    )


def _stato(job: dict[str, Any]) -> str:
    """Lo stato che conta è quello delle 24 ore, non l'ultimo per caso.

    Tre casi, e ognuno nasce da un difetto vero:

    * **fallito** — un job andato male alle 2 e bene alle 6 resta da
      guardare: il successo di stamattina non cancella la replica che
      stanotte non c'è. Fa eccezione la riprova automatica, che è il
      rimedio a quel preciso fallimento e quindi lo chiude;
    * **riprovato** — fallito, riprovato dopo un'ora, riuscito. Va detto,
      non allarmato;
    * **fermo** — il cron si aspettava una corsa e non c'è stata. Lo decide
      `check_job_overdue` a monte (campo `in_ritardo`): la regola «zero
      esecuzioni in 24 ore» che c'era prima gridava al guasto su ogni job
      settimanale, e il 2026-09-08 ha prodotto un allarme falso su sei
      repliche perfettamente puntuali.
    """
    if _riuscito_alla_riprova(job):
        return "riprovato"
    if int(job.get("failed_24h") or 0) > 0:
        return "failed"
    if job.get("in_ritardo"):
        return "fermo"
    ultimo = str(job.get("last_status") or "never_run")
    if ultimo in ml.STATI:
        return ultimo
    return "warning"


def _oggetto(job: dict[str, Any]) -> str:
    """Che cosa è stato replicato: la VM se c'è, altrimenti il nome del job."""
    nome_vm = (job.get("vm_name") or "").strip()
    vm_id = job.get("vm_id")
    if nome_vm and vm_id:
        return f"{nome_vm} ({vm_id})"
    if nome_vm:
        return nome_vm
    if vm_id:
        return f"VM {vm_id}"
    return str(job.get("name") or "senza nome")


def _quante_volte(job: dict[str, Any]) -> str:
    corse = int(job.get("runs_24h") or 0)
    ko = int(job.get("failed_24h") or 0)
    if corse == 0:
        return "nessuna esecuzione"
    if corse == 1:
        return "1 esecuzione" if ko == 0 else "1 esecuzione, fallita"
    if ko == 0:
        return f"{corse} esecuzioni"
    return f"{corse} esecuzioni, {ko} fallite" if ko > 1 else f"{corse} esecuzioni, 1 fallita"


def _attivita_html(job: dict[str, Any], *, ultima: bool) -> str:
    stato = _stato(job)
    sorgente = str(job.get("source_node") or "").strip()
    destinazione = str(job.get("dest_node") or "").strip()
    percorso = f"{sorgente} → {destinazione}" if sorgente and destinazione else sorgente

    dettagli: list[str] = []
    trasferito = (job.get("last_transferred") or "").strip() if job.get("last_transferred") else ""
    if trasferito:
        dettagli.append(f"trasferiti {trasferito}")
    da, a = job.get("source_dataset"), job.get("dest_dataset")
    if da or a:
        dettagli.append(f"{da or '—'} → {a or '—'}")

    errore = ""
    if job.get("last_error"):
        ora = job.get("last_error_time")
        errore = f"[{ora}] {job['last_error']}" if ora else str(job["last_error"])

    return ml.attivita(
        stato=stato,
        oggetto=_oggetto(job),
        quando=str(job.get("last_run") or "Mai"),
        durata=" · ".join(
            x for x in (_quante_volte(job), durata_breve(job.get("duration_24h"))) if x
        ),
        percorso=percorso,
        dettagli=dettagli,
        errore=errore,
        ultima=ultima,
    )


def raggruppa(jobs: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Le sezioni da mostrare, e i nomi dei job che hanno chiesto silenzio.

    Chi ha `notify_mode = never` esce dal riepilogo — è quello che «Mai»
    promette. Ma il suo nome resta in coda alla mail: un job silenziato deve
    restare silenzioso, non diventare invisibile.
    """
    esclusi = [
        str(j.get("name") or "senza nome")
        for j in jobs
        if (j.get("notifica") or "daily") == "never"
    ]
    vivi = [j for j in jobs if (j.get("notifica") or "daily") != "never"]

    sezioni: list[dict[str, Any]] = []
    for t in (*TIPOLOGIE, _SCONOSCIUTA):
        if t is _SCONOSCIUTA:
            suoi = [j for j in vivi if (j.get("type") or "") not in _PER_CHIAVE]
        else:
            suoi = [j for j in vivi if j.get("type") == t.chiave]
        if not suoi:
            continue
        suoi.sort(key=lambda j: (_PESO_STATO.get(_stato(j), 9), str(j.get("name") or "")))
        sezioni.append(
            {
                "tipologia": t,
                "jobs": suoi,
                "esecuzioni": sum(int(j.get("runs_24h") or 0) for j in suoi),
                "falliti": sum(int(j.get("failed_24h") or 0) for j in suoi),
                "fermi": [j for j in suoi if int(j.get("runs_24h") or 0) == 0],
            }
        )
    return sezioni, esclusi


def conta_fermi(sezioni: list[dict[str, Any]]) -> int:
    """Quanti job pianificati non sono partiti nelle 24 ore.

    Serve perché era possibile un riepilogo con l'oggetto «tutto regolare» e
    sei repliche ferme dentro: i conti guardavano solo le esecuzioni FALLITE,
    e un job che non parte non produce esecuzioni, quindi non ne produce
    nemmeno di fallite. Contato sul primo riepilogo vero, il 2026-09-08.
    """
    return sum(1 for s in sezioni for j in s["jobs"] if _stato(j) == "fermo")


def _riga_esclusi(esclusi: list[str]) -> str:
    """Il conto dei silenziati, con il singolare che non stona."""
    if len(esclusi) == 1:
        return "1 job escluso dalle notifiche"
    return f"{len(esclusi)} job esclusi dalle notifiche"


def _conta(n: int, singolare: str, plurale: str) -> str:
    return f"{n} {singolare if n == 1 else plurale}"


def _colore_sezione(sezione: dict[str, Any]) -> str:
    """Il colore della barra dice, scorrendo il margine, dove guardare."""
    if sezione["falliti"]:
        return ml.ROSSO
    if any(_stato(j) == "fermo" for j in sezione["jobs"]):
        return ml.AMBRA
    if sezione["esecuzioni"] == 0:
        return ml.MUTED
    return ml.VERDE


def oggetto_mail(summary: dict[str, Any], *, impianto: str) -> str:
    """La riga che si legge nell'elenco della posta, senza aprire niente.

    «Tutto regolare» si dice solo quando è vero: niente esecuzioni fallite
    **e** nessun job pianificato rimasto fermo. Sono due guasti diversi e il
    secondo non produce esecuzioni, quindi non comparirebbe fra le fallite.
    """
    sezioni, _ = raggruppa(summary.get("jobs") or [])
    falliti = int(summary.get("failed") or 0)
    fermi = conta_fermi(sezioni)
    corse = int(summary.get("total_runs") or 0)
    if falliti:
        coda = f", {fermi} non partiti" if fermi else ""
        return f"❌ {impianto} — {falliti} su {corse} esecuzioni fallite{coda}"
    if fermi:
        quali = "job pianificato non è partito" if fermi == 1 else "job pianificati non sono partiti"
        return f"⚠️ {impianto} — {fermi} {quali}"
    if corse == 0:
        return f"⏸️ {impianto} — nessuna esecuzione nelle ultime 24 ore"
    return f"✅ {impianto} — {corse} esecuzioni, tutto regolare"


def _occhiello(falliti: int, fermi: int) -> str:
    """La riga sotto il titolo: dice per cosa vale la pena leggere oltre."""
    pezzi = []
    if falliti:
        pezzi.append(f"{falliti} esecuzioni fallite")
    if fermi:
        pezzi.append(
            "1 job pianificato non è partito" if fermi == 1
            else f"{fermi} job pianificati non sono partiti"
        )
    if not pezzi:
        return "Ultime 24 ore, nessun guasto"
    return " · ".join(pezzi) + " nelle ultime 24 ore"


def render_html(summary: dict[str, Any], *, impianto: str, adesso: datetime | None = None) -> str:
    sezioni, esclusi = raggruppa(summary.get("jobs") or [])
    falliti = int(summary.get("failed") or 0)
    fermi = conta_fermi(sezioni)
    quando = (adesso or datetime.now().astimezone()).strftime("%d/%m/%Y %H:%M %Z").strip()

    corpo = ml.riquadro_numeri(
        [
            {"n": summary.get("total_runs"), "etichetta": "Esecuzioni", "colore": ml.NAVY},
            {"n": summary.get("successful"), "etichetta": "Riuscite", "colore": ml.VERDE},
            {"n": falliti, "etichetta": "Fallite", "colore": ml.ROSSO},
            {"n": fermi, "etichetta": "Non partiti", "colore": ml.AMBRA},
            {
                "n": summary.get("total_duration"),
                "testo": durata_breve(summary.get("total_duration")),
                "etichetta": "Durata",
                "colore": ml.MUTED,
            },
        ]
    )

    for sezione in sezioni:
        t: Tipologia = sezione["tipologia"]
        jobs = sezione["jobs"]
        corpo += ml.sezione(
            titolo=f"{t.sigla} · {t.descrizione}",
            sottotitolo=" · ".join(
                (
                    _conta(len(jobs), "job", "job"),
                    _conta(sezione["esecuzioni"], "esecuzione", "esecuzioni")
                    if sezione["esecuzioni"]
                    else "nessuna esecuzione in 24 ore",
                )
            ),
            colore=_colore_sezione(sezione),
            voci=[
                _attivita_html(j, ultima=(i == len(jobs) - 1)) for i, j in enumerate(jobs)
            ],
            vuoto="Nessun job configurato.",
        )

    if not sezioni:
        corpo += ml.sezione(
            titolo="Nessuna attività",
            sottotitolo="nessun job attivo su questo impianto",
            colore=ml.MUTED,
            voci=[],
            vuoto="Non c'è niente da riepilogare.",
        )

    piede = f"Ultime 24 ore · {quando}"
    if esclusi:
        piede += f"<br>{_riga_esclusi(esclusi)}: {ml.esc(', '.join(esclusi))}"

    return ml.documento(
        titolo=f"Riepilogo {impianto}",
        occhiello=_occhiello(falliti, fermi),
        corpo=corpo,
        piede=piede,
    )


def render_testo(summary: dict[str, Any], *, impianto: str) -> str:
    """Le stesse cose dell'HTML, per chi legge da orologio o da archivio."""
    sezioni, esclusi = raggruppa(summary.get("jobs") or [])
    righe = [
        f"Riepilogo {impianto} — ultime 24 ore",
        "",
        f"Esecuzioni {summary.get('total_runs', 0)} · riuscite {summary.get('successful', 0)}"
        f" · fallite {summary.get('failed', 0)} · non partiti {conta_fermi(sezioni)}"
        f" · durata {durata_breve(summary.get('total_duration')) or '0s'}",
    ]
    for sezione in sezioni:
        t: Tipologia = sezione["tipologia"]
        righe += ["", f"=== {t.sigla} — {t.descrizione} ({sezione['esecuzioni']} esecuzioni) ==="]
        for job in sezione["jobs"]:
            stato = _stato(job)
            parola = ml.STATI.get(stato, ("", ""))[0] or "OK"
            capo = f"- [{parola}] {_oggetto(job)}"
            sotto = " · ".join(
                x
                for x in (
                    str(job.get("last_run") or "Mai"),
                    _quante_volte(job),
                    durata_breve(job.get("duration_24h")),
                    f"{job.get('source_node') or '—'} -> {job.get('dest_node') or '—'}",
                )
                if x
            )
            righe += [capo, f"    {sotto}"]
            # I dataset distinguono job che replicano la stessa VM (dischi
            # diversi): senza, nel testo comparivano tre righe «DA-SEVEN (404)»
            # identiche e non si capiva quale fosse quale.
            da, a = job.get("source_dataset"), job.get("dest_dataset")
            if da or a:
                righe.append(f"    {da or '—'} -> {a or '—'}")
            if job.get("last_error"):
                righe.append(f"    errore: {job['last_error']}")
    if esclusi:
        righe += ["", f"{_riga_esclusi(esclusi)}: {', '.join(esclusi)}"]
    return "\n".join(righe)


def render_telegram(summary: dict[str, Any], *, impianto: str) -> str:
    """Telegram: gli stessi gruppi, ma corto — si legge sulla schermata di blocco."""
    sezioni, esclusi = raggruppa(summary.get("jobs") or [])
    falliti = int(summary.get("failed") or 0)
    fermi = conta_fermi(sezioni)
    testa = "❌" if falliti else ("⚠️" if fermi else "✅")
    righe = [
        f"{testa} *{impianto}* — ultime 24 ore",
        f"{summary.get('total_runs', 0)} esecuzioni · {summary.get('successful', 0)} ok"
        f" · {falliti} fallite · {fermi} non partiti",
    ]
    for sezione in sezioni:
        t: Tipologia = sezione["tipologia"]
        segno = "❌" if sezione["falliti"] else ("⏸" if not sezione["esecuzioni"] else "✅")
        righe.append(f"\n{segno} *{t.sigla}* ({sezione['esecuzioni']})")
        # Solo ciò che non va: su Telegram l'elenco completo non lo legge nessuno.
        guasti = [j for j in sezione["jobs"] if _stato(j) != "success"]
        for job in guasti[:5]:
            parola = ml.STATI.get(_stato(job), ("", ""))[0] or "?"
            righe.append(f"  · {_oggetto(job)} — {parola.lower()}")
        if len(guasti) > 5:
            righe.append(f"  · … e altri {len(guasti) - 5}")
    if esclusi:
        righe.append(f"\n{_riga_esclusi(esclusi)}.")
    return "\n".join(righe)
