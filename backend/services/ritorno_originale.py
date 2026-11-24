"""Ritorno all'originale: dalla replica accesa alla VM originale, con syncoid.

Caso reale: 3CX di DTS, 24/11/2026. L'originale (VM 103) si era danneggiata,
la replica (9103) ha lavorato 12 giorni al suo posto, e il ritorno fatto a
mano ha lasciato la 103 isolata 3 minuti perche' la conf della replica
portava il bridge della destinazione. Piano:
docs/superpowers/plans/2026-11-24-ritorno-all-originale.md.

Regole che questo modulo non viola mai:
- nessun `zfs destroy`, nessun `qm destroy`: il disco vecchio si RINOMINA;
- la replica non si tocca finche' l'originale non ha risposto;
- mai due VM accese con lo stesso uuid e lo stesso MAC;
- al ritorno valgono i valori dell'originale (nome, rete, onboot, tag, uuid).

In alto le funzioni pure (nessun SSH), in basso i passi che parlano coi nodi.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from services.replica_identity import (
    SALE_REPLICA,
    _RE_UUID,
    _imposta,
    estrai_identita_da_descrizione,
    rimuovi_sezioni_snapshot,
    valore_config,
)

# Chiavi dell'hardware: valgono quelle dell'originale; se la replica ne ha di
# diverse (es. `cpu: host` forzato alla registrazione) lo si dice.
CHIAVI_HARDWARE = ("cores", "sockets", "memory", "cpu", "scsihw", "bios", "machine")
_RE_CHIAVE_DISCO = re.compile(r"^(?:(?:scsi|virtio|sata|ide)\d+|efidisk\d+|tpmstate\d+)$")
STATI = ("nessuno", "preparazione", "pronto", "scambio", "completato", "fallito")


def nome_disco_vecchio(dataset: str, quando: datetime) -> str:
    """Il nome con cui il disco dell'originale viene messo da parte.

    "ZFS/vm-103-disk-0" -> "ZFS/dapx-vecchio-103-disk-0-20261124-1933".
    Non deve combaciare con `vm-<id>-disk-N`: Proxmox lo considererebbe
    ancora di quella VM, e un ripristino forzato lo cancellerebbe.
    """
    padre, _, foglia = dataset.rpartition("/")
    corpo = re.sub(r"^(?:vm|base|subvol)-", "", foglia)
    nuovo = f"dapx-vecchio-{corpo}-{quando.strftime('%Y%m%d-%H%M')}"
    return f"{padre}/{nuovo}" if padre else nuovo


def _righe_descrizione(config: str) -> List[str]:
    """Le righe di nota del .conf: `#...` in testa al file o `description:`."""
    return [r for r in config.splitlines() if r.startswith("#") or r.startswith("description:")]


def _ascii(testo: str) -> str:
    return testo.encode("ascii", "ignore").decode("ascii").replace("%", "").replace("\n", " ")


def config_originale_per_ritorno(
    snapshot_originale: Optional[str],
    config_replica: str,
    dischi: Dict[str, str],
    quando: datetime,
    utente: str,
    *,
    vmid_replica=None,
    suffisso_nome: Optional[str] = None,
) -> Tuple[str, List[str]]:
    """La conf con cui l'originale riparte. Ritorna (conf, avvisi).

    Base = fotografia dell'originale; se manca (job nati prima della 3.27.0)
    base = conf della replica con nome senza suffisso e uuid/vmgenid letti
    dalla sua description, piu' un avviso: bridge, onboot e tag non si
    recuperano. `dischi` = {"scsi0": "ZFS:vm-103-disk-0"} sul nodo d'origine.
    """
    avvisi: List[str] = []
    replica = rimuovi_sezioni_snapshot(config_replica or "")

    if snapshot_originale and snapshot_originale.strip():
        base = rimuovi_sezioni_snapshot(snapshot_originale)
        diversi = [
            f"{k} (originale {valore_config(base, k) or '-'}, replica {valore_config(replica, k) or '-'})"
            for k in CHIAVI_HARDWARE
            if valore_config(base, k) != valore_config(replica, k)
        ]
        if diversi:
            avvisi.append("Hardware diverso tra originale e replica, vale l'originale: " + "; ".join(diversi))
        note_originali = [r for r in _righe_descrizione(base) if SALE_REPLICA not in r]
    else:
        base = replica
        nome = valore_config(base, "name")
        if nome and suffisso_nome and nome.endswith(suffisso_nome):
            base = _imposta(base, "name", nome[: -len(suffisso_nome)])
        ident = estrai_identita_da_descrizione(valore_config(replica, "description"))
        smbios = valore_config(base, "smbios1")
        if ident.get("source_smbios_uuid"):
            if smbios and re.search(r"(?:^|,)uuid=", smbios):
                smbios = re.sub(r"((?:^|,)uuid=)" + _RE_UUID, rf"\g<1>{ident['source_smbios_uuid']}", smbios, count=1)
            else:
                smbios = f"uuid={ident['source_smbios_uuid']}"
            base = _imposta(base, "smbios1", smbios)
        else:
            avvisi.append("uuid SMBIOS dell'originale non trovato: resta quello della replica")
        if ident.get("source_vmgenid"):
            base = _imposta(base, "vmgenid", str(ident["source_vmgenid"]))
        avvisi.append(
            "Manca la fotografia della configurazione dell'originale: bridge, onboot e tag "
            "non recuperabili, sono quelli della replica: controllare prima di completare"
        )
        note_originali = []

    righe = []
    for riga in base.splitlines():
        if riga.startswith("#") or riga.startswith("description:"):
            continue
        if re.match(r"^unused\d+:", riga) or riga.startswith("parent:"):
            continue
        righe.append(riga)
    corpo = "\n".join(righe).strip("\n") + "\n"

    for chiave, volume in dischi.items():
        attuale = valore_config(corpo, chiave) or valore_config(replica, chiave)
        opzioni = attuale.split(",", 1)[1] if attuale and "," in attuale else ""
        corpo = _imposta(corpo, chiave, volume + (f",{opzioni}" if opzioni else ""))

    for riga in corpo.splitlines():
        chiave = riga.split(":", 1)[0]
        if _RE_CHIAVE_DISCO.match(chiave) and chiave not in dischi and "media=cdrom" not in riga \
                and not riga.split(":", 1)[1].strip().startswith("none"):
            avvisi.append(f"Il disco {chiave} non e' tra quelli replicati: resta com'e' nella configurazione")

    nota = _ascii(
        f"Ripristinata da replica {vmid_replica if vmid_replica is not None else '?'} "
        f"il {quando.strftime('%Y-%m-%d %H:%M')} da {utente}"
    )
    testa: List[str] = []
    description = next((r for r in note_originali if r.startswith("description:")), None)
    if description:
        vecchia = description.split(":", 1)[1].strip()
        corpo = _imposta(corpo, "description", f"{nota} | {vecchia}" if vecchia else nota)
        testa = [r for r in note_originali if r.startswith("#")]
    else:
        testa = [f"#{nota}"] + [r for r in note_originali if r.startswith("#")]
    return ("\n".join(testa) + "\n" if testa else "") + corpo, avvisi


def piano_ritorno(
    jobs: List[dict],
    stato_replica: str,
    stato_originale: str,
    conf_originale_presente: bool,
    *,
    replica_segnata: bool = True,
    fotografia_presente: bool = True,
) -> Dict:
    """Cosa farebbe il ritorno, e se si puo' fare.

    `jobs`: un dict per disco con job_id, disk_name, sync_method, vm_type,
    source_dataset, dest_dataset, source_esiste. Stati delle VM: `running`,
    `stopped`, `assente` (la VM non c'e' piu'), `sconosciuto` (il nodo non ha
    risposto: non e' un «spenta»).
    """
    dischi = [
        {
            "job_id": j.get("job_id"),
            "disk_name": j.get("disk_name"),
            "da": j.get("dest_dataset"),
            "a": j.get("source_dataset"),
            "rinomina": bool(j.get("source_esiste")),
        }
        for j in jobs
    ]
    avvisi: List[str] = []
    motivo = ""
    if not jobs:
        motivo = "Nessun job di replica collegato a questa VM"
    elif any((j.get("vm_type") or "qemu") != "qemu" for j in jobs):
        motivo = "Il ritorno e' previsto solo per le VM qemu"
    elif any((j.get("sync_method") or "syncoid") != "syncoid" for j in jobs):
        motivo = "Il ritorno usa solo syncoid: un job del gruppo usa un altro metodo"
    elif not replica_segnata:
        motivo = "Questa VM non porta il segno dapx-replica: non e' una replica registrata da DA-PXREPL"
    elif stato_originale == "running":
        motivo = "La VM originale risulta accesa: il ritorno le sostituirebbe il disco"
    elif stato_originale not in ("stopped", "assente"):
        motivo = f"Lo stato della VM originale non e' leggibile ({stato_originale}): non procedo alla cieca"

    if not motivo:
        if any(d["rinomina"] for d in dischi):
            avvisi.append(
                "Il disco attuale dell'originale viene messo da parte (rinominato, mai cancellato): "
                "sul nodo d'origine serve lo spazio per una copia completa"
            )
        if not conf_originale_presente:
            avvisi.append("La VM originale non esiste piu' sul nodo: viene ricreata con lo stesso VMID")
        if not fotografia_presente:
            avvisi.append(
                "Manca la fotografia della configurazione dell'originale: bridge, onboot e tag "
                "saranno quelli della replica, da controllare"
            )
        if stato_replica != "running":
            avvisi.append("La replica non e' accesa: il ritorno copia i dati cosi' come sono adesso")
    return {"possibile": not motivo, "motivo": motivo, "dischi": dischi, "avvisi": avvisi}


def dischi_per_ritorno(jobs: List[dict], config_replica: str) -> Tuple[Dict[str, str], List[str]]:
    """{chiave disco: "storage:volume"} sul nodo d'origine, e gli errori.

    La chiave e' `disk_name` del job; se manca (job vecchi a disco singolo) si
    cerca nella conf della replica la riga che punta al volume replicato.
    """
    replica = rimuovi_sezioni_snapshot(config_replica or "")
    dischi: Dict[str, str] = {}
    errori: List[str] = []
    for j in jobs:
        foglia_dest = (j.get("dest_dataset") or "").rsplit("/", 1)[-1]
        foglia_orig = (j.get("source_dataset") or "").rsplit("/", 1)[-1]
        chiave = j.get("disk_name")
        if not chiave:
            for riga in replica.splitlines():
                k, _, v = riga.partition(":")
                if _RE_CHIAVE_DISCO.match(k) and v.strip().split(",", 1)[0].endswith(f":{foglia_dest}"):
                    chiave = k
                    break
        if not chiave:
            errori.append(f"job {j.get('job_id')}: non so a quale disco della VM corrisponde {foglia_dest}")
            continue
        storage = j.get("source_storage")
        if not storage:
            errori.append(f"job {j.get('job_id')}: manca lo storage Proxmox d'origine per {chiave}")
            continue
        dischi[chiave] = f"{storage}:{foglia_orig}"
    return dischi, errori


# ───────────────────────── passi che parlano coi nodi ─────────────────────────

import asyncio  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import shlex  # noqa: E402

from services.ssh_service import ssh_service  # noqa: E402
from services.syncoid_service import _assert_dataset, syncoid_service  # noqa: E402

logger = logging.getLogger(__name__)

# Ritorni che QUESTO processo sta eseguendo. Lo stato vero sta nel DB: se il
# DB dice `preparazione`/`scambio` e qui non c'e', il servizio si e' riavviato
# a meta' e il passo si puo' rilanciare.
_in_corso: set = set()
PASSO_S = 5
TEMPO_COPIA_S = 24 * 3600  # una copia completa puo' durare ore


class Fermo(Exception):
    """Il passo non puo' proseguire: il messaggio va all'utente cosi' com'e'."""


async def _dormi(secondi: float) -> None:
    await asyncio.sleep(secondi)


async def _ssh(nodo, comando: str, timeout: int = 60):
    return await ssh_service.execute(
        hostname=nodo.hostname, command=comando, port=nodo.ssh_port,
        username=nodo.ssh_user, key_path=nodo.ssh_key_path, timeout=timeout,
    )


def _testo(esito) -> str:
    return ((esito.stdout or "") + " " + (esito.stderr or "")).strip()


async def stato_vm(nodo, vmid: int) -> str:
    """`running`, `stopped`, altro stato di qm, `assente`, o `sconosciuto`.

    Tre esiti, non due: un errore di trasporto non e' un «spenta».
    """
    esito = await _ssh(nodo, f"qm status {int(vmid)} 2>&1", timeout=20)
    m = re.search(r"status:\s*(\S+)", esito.stdout or "")
    if esito.success and m:
        return m.group(1)
    if esito.exit_code not in (-1, 255) and "does not exist" in _testo(esito):
        return "assente"
    return "sconosciuto"


async def dataset_esiste(nodo, dataset: str) -> Optional[bool]:
    """True, False, o None se il nodo non ha dato una risposta leggibile."""
    _assert_dataset(dataset)
    esito = await _ssh(nodo, f"zfs list -H -o name {shlex.quote(dataset)} 2>&1", timeout=20)
    if esito.success and dataset in (esito.stdout or "").split():
        return True
    if esito.exit_code not in (-1, 255) and "does not exist" in _testo(esito):
        return False
    return None


async def leggi_conf(nodo, vmid: int) -> Tuple[Optional[str], bool]:
    """(testo, letto). `(None, True)` = il file non c'e'; `(None, False)` = non so."""
    esito = await _ssh(nodo, f"cat /etc/pve/qemu-server/{int(vmid)}.conf 2>&1", timeout=20)
    if esito.success and (esito.stdout or "").strip():
        return esito.stdout, True
    if esito.exit_code not in (-1, 255) and "No such file" in _testo(esito):
        return None, True
    return None, False


def jobs_del_ritorno(db, node_id: int, vmid: int) -> list:
    """Tutti i job (uno per disco) che hanno questa VM come replica."""
    from sqlalchemy import and_, or_
    from database import SyncJob

    primo = (
        db.query(SyncJob)
        .filter(
            SyncJob.dest_node_id == node_id,
            or_(SyncJob.dest_vm_id == vmid, and_(SyncJob.dest_vm_id.is_(None), SyncJob.vm_id == vmid)),
        )
        .order_by(SyncJob.id)
        .first()
    )
    if not primo:
        return []
    if not primo.vm_group_id:
        return [primo]
    return db.query(SyncJob).filter(SyncJob.vm_group_id == primo.vm_group_id).order_by(SyncJob.id).all()


def _chiave(jobs) -> str:
    return f"{jobs[0].dest_node_id}:{jobs[0].dest_vm_id or jobs[0].vm_id}"


def _dettaglio(job) -> dict:
    try:
        d = json.loads(job.ritorno_dettaglio or "{}")
        return d if isinstance(d, dict) else {}
    except ValueError:
        return {}


def _scrivi(db, jobs, stato: str, dettaglio: dict) -> None:
    dettaglio["aggiornato"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    testo = json.dumps(dettaglio, ensure_ascii=False)
    for j in jobs:
        j.ritorno_stato = stato
        j.ritorno_dettaglio = testo
    db.commit()


def _job_dict(j, source_esiste=None) -> dict:
    return {
        "job_id": j.id, "disk_name": j.disk_name, "sync_method": j.sync_method or "syncoid",
        "vm_type": j.vm_type or "qemu", "source_dataset": j.source_dataset,
        "dest_dataset": j.dest_dataset, "source_storage": j.source_storage,
        "source_esiste": source_esiste,
    }


async def stato_ritorno(db, jobs, nodo_origine, nodo_replica) -> dict:
    """Per la pagina: stato del ritorno, piano, e cosa c'e' adesso sui due nodi."""
    vmid_o = int(jobs[0].vm_id)
    vmid_r = int(jobs[0].dest_vm_id or jobs[0].vm_id)
    stato_o = await stato_vm(nodo_origine, vmid_o)
    stato_r = await stato_vm(nodo_replica, vmid_r)
    conf_r, _ = await leggi_conf(nodo_replica, vmid_r)
    dett = _dettaglio(jobs[0])
    stato = jobs[0].ritorno_stato or "nessuno"
    gia_trattati = dett.get("dischi", {}) if stato not in ("nessuno", "completato") else {}
    descritti = []
    for j in jobs:
        if str(j.id) in gia_trattati:
            esiste = False  # il disco vecchio e' gia' da parte: non si rinomina piu'
        else:
            esiste = await dataset_esiste(nodo_origine, j.source_dataset)
        descritti.append(_job_dict(j, esiste))
    segnata = SALE_REPLICA in rimuovi_sezioni_snapshot(conf_r or "")
    piano = piano_ritorno(
        descritti, stato_r, stato_o, stato_o != "assente",
        replica_segnata=segnata, fotografia_presente=bool(jobs[0].source_config_snapshot),
    )
    if any(d["source_esiste"] is None for d in descritti) and piano["possibile"]:
        piano["possibile"] = False
        piano["motivo"] = f"Il nodo {nodo_origine.name} non ha risposto sui dischi dell'originale: non procedo alla cieca"
    in_corso = _chiave(jobs) in _in_corso
    return {
        "stato": stato,
        "in_corso": in_corso,
        "interrotto": stato in ("preparazione", "scambio") and not in_corso,
        "dettaglio": dett,
        "piano": piano,
        "originale": {"vmid": vmid_o, "nodo": nodo_origine.name, "stato": stato_o,
                      "nome": valore_config(jobs[0].source_config_snapshot or "", "name") or jobs[0].vm_name},
        "replica": {"vmid": vmid_r, "nodo": nodo_replica.name, "stato": stato_r,
                    "nome": valore_config(conf_r or "", "name")},
        "fotografia": {
            "presente": bool(jobs[0].source_config_snapshot),
            "del": jobs[0].source_config_at.strftime("%Y-%m-%d %H:%M UTC") if jobs[0].source_config_at else None,
        },
    }


async def _sync_inverso(job, nodo_origine, nodo_replica) -> None:
    """syncoid dalla replica al nodo d'origine. Mai --force-delete."""
    _assert_dataset(job.source_dataset)
    _assert_dataset(job.dest_dataset)
    stesso_nodo = nodo_origine.hostname == nodo_replica.hostname
    esito = await syncoid_service.run_sync(
        executor_host=nodo_replica.hostname,
        source_host=None,
        source_dataset=job.dest_dataset,
        dest_host=None if stesso_nodo else nodo_origine.hostname,
        dest_dataset=job.source_dataset,
        dest_user=nodo_origine.ssh_user,
        dest_port=nodo_origine.ssh_port,
        dest_key=nodo_origine.ssh_key_path,
        executor_port=nodo_replica.ssh_port,
        executor_user=nodo_replica.ssh_user,
        executor_key=nodo_replica.ssh_key_path,
        recursive=False,
        compress=job.compress or "lz4",
        mbuffer_size=job.mbuffer_size or "128M",
        no_sync_snap=False,
        force_delete=False,
        extra_args=job.extra_args or "",
        timeout=TEMPO_COPIA_S,
    )
    if not esito.get("success"):
        errore = (esito.get("error") or esito.get("output") or "").strip()[-400:]
        raise Fermo(f"syncoid {job.dest_dataset} -> {nodo_origine.name}:{job.source_dataset} fallito: {errore}")


def _carica(db, job_ids):
    from database import Node, SyncJob

    jobs = db.query(SyncJob).filter(SyncJob.id.in_(list(job_ids))).order_by(SyncJob.id).all()
    if not jobs:
        raise Fermo("Job di replica non trovati")
    # Sempre tutti i dischi della VM, anche se e' arrivato un job solo.
    if jobs[0].vm_group_id:
        jobs = db.query(SyncJob).filter(SyncJob.vm_group_id == jobs[0].vm_group_id).order_by(SyncJob.id).all()
    origine = db.query(Node).filter(Node.id == jobs[0].source_node_id).first()
    replica = db.query(Node).filter(Node.id == jobs[0].dest_node_id).first()
    if not origine or not replica:
        raise Fermo("Nodo d'origine o della replica non censito")
    return jobs, origine, replica


def _apri_log(db, tipo: str, jobs, origine, replica, utente_id):
    from database import JobLog

    log = JobLog(
        job_type=tipo, job_id=jobs[0].id, node_name=f"{replica.name} -> {origine.name}",
        dataset=", ".join(f"{j.dest_dataset} -> {j.source_dataset}" for j in jobs),
        status="started", message="", output="", started_at=datetime.utcnow(),
        triggered_by=utente_id, trigger_source="manual",
    )
    db.add(log)
    db.commit()
    return log


def _riga(log, db, testo: str) -> None:
    logger.info("ritorno: %s", testo)
    log.output = (log.output or "") + f"[{datetime.utcnow().strftime('%H:%M:%S')}] {testo}\n"
    db.commit()


def _chiudi_log(db, log, ok: bool, messaggio: str) -> None:
    log.status = "success" if ok else "failed"
    log.message = messaggio
    if not ok:
        log.error = messaggio
    log.completed_at = datetime.utcnow()
    log.duration = int((log.completed_at - log.started_at).total_seconds())
    db.commit()


async def prepara(job_ids, utente_id, utente_nome: str, session_factory=None) -> None:
    """Primo tempo, a replica accesa: disco vecchio da parte, copia verso l'origine.

    Ripetibile: i dischi gia' messi da parte sono scritti nel DB, una seconda
    corsa fa solo l'incrementale.
    """
    if session_factory is None:
        from database import SessionLocal as session_factory
    db = session_factory()
    chiave = None
    log = None
    jobs = []
    dett: dict = {}
    try:
        jobs, origine, replica = _carica(db, job_ids)
        chiave = _chiave(jobs)
        if chiave in _in_corso:
            return
        _in_corso.add(chiave)
        vmid_o = int(jobs[0].vm_id)
        vmid_r = int(jobs[0].dest_vm_id or jobs[0].vm_id)
        precedente = jobs[0].ritorno_stato or "nessuno"
        dett = _dettaglio(jobs[0]) if precedente not in ("nessuno", "completato") else {}
        dett.pop("errore", None)
        dett.update(fase="prepara", utente=utente_nome, messaggio="Preparazione in corso")
        dischi = dett.setdefault("dischi", {})
        for j in jobs:
            j.is_active = False  # una corsa normale riporterebbe indietro il disco della replica
        _scrivi(db, jobs, "preparazione", dett)
        log = _apri_log(db, "ritorno_prepara", jobs, origine, replica, utente_id)
        _riga(log, db, f"Prepara ritorno: replica {vmid_r} su {replica.name} -> originale {vmid_o} su {origine.name}")

        stato_o = await stato_vm(origine, vmid_o)
        if stato_o == "running":
            raise Fermo(f"La VM originale {vmid_o} e' accesa su {origine.name}: non le tocco il disco")
        if stato_o not in ("stopped", "assente"):
            raise Fermo(f"Stato della VM originale {vmid_o} non leggibile su {origine.name} ({stato_o})")

        for j in jobs:
            if str(j.id) not in dischi:
                esiste = await dataset_esiste(origine, j.source_dataset)
                if esiste is None:
                    raise Fermo(f"{origine.name} non ha risposto su {j.source_dataset}: non procedo alla cieca")
                vecchio = None
                if esiste:
                    vecchio = nome_disco_vecchio(j.source_dataset, datetime.utcnow())
                    _assert_dataset(vecchio)
                    esito = await _ssh(
                        origine, f"zfs rename {shlex.quote(j.source_dataset)} {shlex.quote(vecchio)}", timeout=120
                    )
                    if not esito.success:
                        raise Fermo(f"Non riesco a mettere da parte {j.source_dataset}: {_testo(esito)[:300]}")
                    _riga(log, db, f"Disco vecchio messo da parte: {j.source_dataset} -> {vecchio}")
                dischi[str(j.id)] = {"dataset": j.source_dataset, "vecchio": vecchio}
                _scrivi(db, jobs, "preparazione", dett)  # subito: se cado qui non rinomino due volte
            _riga(log, db, f"Copia {j.dest_dataset} -> {origine.name}:{j.source_dataset}")
            await _sync_inverso(j, origine, replica)

        dett["messaggio"] = "Dati copiati sul nodo d'origine: si puo' completare il ritorno"
        _scrivi(db, jobs, "pronto", dett)
        _chiudi_log(db, log, True, f"Ritorno preparato per VM {vmid_o}: {len(jobs)} disco/i copiati su {origine.name}")
    except Exception as e:  # noqa: BLE001 - lo stato deve uscire comunque da «preparazione»
        motivo = str(e) if isinstance(e, Fermo) else f"Errore inatteso: {e}"
        if not isinstance(e, Fermo):
            logger.exception("ritorno: prepara fallita")
        try:
            db.rollback()
            if jobs:
                dett.update(fase="prepara", errore=motivo, messaggio="Preparazione fallita: " + motivo)
                _scrivi(db, jobs, "fallito", dett)
            if log is not None:
                _chiudi_log(db, log, False, motivo)
        except Exception:  # pragma: no cover
            logger.exception("ritorno: stato non scritto dopo il fallimento")
    finally:
        if chiave:
            _in_corso.discard(chiave)
        db.close()


async def _scrivi_conf(nodo, vmid: int, conf: str, quando: datetime) -> None:
    """Copia la conf di prima in /root/dapx-bak-<data>/ e scrive la nuova (heredoc, come `register_vm`)."""
    if "DAPX_RITORNO_EOF" in conf:
        raise Fermo("La configurazione contiene il delimitatore riservato")
    percorso = f"/etc/pve/qemu-server/{int(vmid)}.conf"
    cartella = f"/root/dapx-bak-{quando.strftime('%Y%m%d')}"
    copia = f"{cartella}/{int(vmid)}.conf.pre-ritorno-{quando.strftime('%H%M%S')}"
    comando = (
        f"set -e\nmkdir -p {cartella}\n"
        f"if [ -f {percorso} ]; then cp -a {percorso} {copia}; fi\n"
        f"cat > {percorso} << 'DAPX_RITORNO_EOF'\n{conf.rstrip(chr(10))}\nDAPX_RITORNO_EOF"
    )
    esito = await _ssh(nodo, comando, timeout=60)
    if not esito.success:
        raise Fermo(f"Scrittura di {percorso} su {nodo.name} fallita: {_testo(esito)[:300]}")


async def _aspetta_avvio(nodo, vmid: int, usa_agent: bool, attesa_s: int) -> bool:
    """True se l'originale risponde entro `attesa_s`.

    Con l'agent: `qm agent ping`. Senza: `running` per 30 secondi di fila.
    """
    giri = max(1, int(attesa_s) // PASSO_S)
    di_fila = 0
    for _ in range(giri):
        await _dormi(PASSO_S)
        if usa_agent:
            esito = await _ssh(nodo, f"qm agent {int(vmid)} ping 2>&1", timeout=15)
            if esito.success:
                return True
        else:
            di_fila = di_fila + 1 if await stato_vm(nodo, vmid) == "running" else 0
            if di_fila * PASSO_S >= 30:
                return True
    return False


async def _replica_torna_replica(replica, vmid_r: int, origine, vmid_o: int, conf_originale: str, conf_replica: str):
    """Sulla replica spenta: uuid e vmgenid derivati, onboot 0, segno nella description."""
    from services.replica_identity import descrizione_replica, identita_replica, uuid_da_smbios1

    ident = identita_replica(conf_originale, source_hostname=origine.hostname, source_vmid=vmid_o, vmid_replica=vmid_r)
    smbios = valore_config(rimuovi_sezioni_snapshot(conf_replica), "smbios1") or ""
    attuale = uuid_da_smbios1(smbios)
    nuovo = (
        smbios.replace(f"uuid={attuale}", f"uuid={ident['replica_smbios_uuid']}", 1)
        if attuale else f"uuid={ident['replica_smbios_uuid']}"
    )
    descr = descrizione_replica(
        source_vmid=vmid_o, source_hostname=origine.hostname,
        source_smbios_uuid=ident["source_smbios_uuid"], source_vmgenid=ident["source_vmgenid"],
    )
    comando = (
        f"qm set {int(vmid_r)} --smbios1 {shlex.quote(nuovo)} "
        f"--vmgenid {shlex.quote(ident['replica_vmgenid'])} --onboot 0 "
        f"--description {shlex.quote(descr)}"
    )
    return await _ssh(replica, comando, timeout=30), ident


async def completa(job_ids, utente_id, utente_nome: str, attesa_avvio_s: int = 180, session_factory=None) -> None:
    """Secondo tempo, con fermo breve: spegne la replica, ultimo syncoid,
    conf dell'originale, accensione e controllo. Se l'originale non risponde
    la spegne e riaccende la replica."""
    if session_factory is None:
        from database import SessionLocal as session_factory
    db = session_factory()
    chiave = None
    log = None
    jobs = []
    dett: dict = {}
    replica_da_riaccendere = False
    originale_avviata = False
    origine = replica = None
    vmid_o = vmid_r = 0
    try:
        jobs, origine, replica = _carica(db, job_ids)
        if (jobs[0].ritorno_stato or "nessuno") != "pronto":
            logger.warning("ritorno: completa chiesta senza stato «pronto» (job %s): niente da fare", jobs[0].id)
            return
        chiave = _chiave(jobs)
        if chiave in _in_corso:
            return
        _in_corso.add(chiave)
        vmid_o = int(jobs[0].vm_id)
        vmid_r = int(jobs[0].dest_vm_id or jobs[0].vm_id)
        dett = _dettaglio(jobs[0])
        dett.pop("errore", None)
        dett.update(fase="completa", utente=utente_nome, messaggio="Scambio in corso")
        _scrivi(db, jobs, "scambio", dett)
        log = _apri_log(db, "ritorno_completa", jobs, origine, replica, utente_id)
        adesso = datetime.utcnow()

        # Tutto cio' che puo' andare storto senza toccare niente, prima del fermo.
        conf_r, letta = await leggi_conf(replica, vmid_r)
        if not conf_r:
            raise Fermo(f"Configurazione della replica {vmid_r} non leggibile su {replica.name}")
        stato_o = await stato_vm(origine, vmid_o)
        if stato_o not in ("stopped", "assente"):
            raise Fermo(f"La VM originale {vmid_o} su {origine.name} e' in stato «{stato_o}»: deve essere spenta")
        dischi, errori = dischi_per_ritorno([_job_dict(j) for j in jobs], conf_r)
        if errori:
            raise Fermo("Dischi non riconducibili alla VM: " + "; ".join(errori))
        conf_nuova, avvisi = config_originale_per_ritorno(
            jobs[0].source_config_snapshot, conf_r, dischi, adesso, utente_nome,
            vmid_replica=vmid_r, suffisso_nome=jobs[0].dest_vm_name_suffix,
        )
        dett["avvisi"] = avvisi
        stato_r = await stato_vm(replica, vmid_r)
        if stato_r == "sconosciuto":
            raise Fermo(f"Stato della replica {vmid_r} non leggibile su {replica.name}")

        # (1) spegnimento della replica
        if stato_r != "stopped":
            _riga(log, db, f"Spengo la replica {vmid_r} su {replica.name} (fino a 300 s)")
            await _ssh(replica, f"qm shutdown {vmid_r} --timeout 300 2>&1", timeout=330)
        if await stato_vm(replica, vmid_r) != "stopped":
            raise Fermo(
                f"La replica {vmid_r} non si e' spenta: mi fermo qui, niente e' stato cambiato "
                "e la replica continua a lavorare"
            )
        replica_da_riaccendere = stato_r == "running"

        # (2) ultimo syncoid, a replica ferma: tutti i dischi allo stesso istante
        for j in jobs:
            _riga(log, db, f"Ultima copia {j.dest_dataset} -> {origine.name}:{j.source_dataset}")
            await _sync_inverso(j, origine, replica)

        # (3) conf dell'originale
        await _scrivi_conf(origine, vmid_o, conf_nuova, adesso)
        _riga(log, db, f"Configurazione della VM {vmid_o} scritta su {origine.name}")

        # (4) accensione e controllo. Mai due VM accese con lo stesso uuid.
        if await stato_vm(replica, vmid_r) != "stopped":
            raise Fermo(f"La replica {vmid_r} non risulta piu' spenta: non accendo l'originale")
        originale_avviata = True
        esito = await _ssh(origine, f"qm start {vmid_o} 2>&1", timeout=180)
        if not esito.success:
            raise Fermo(f"La VM originale {vmid_o} non parte: {_testo(esito)[:300]}")
        agent = valore_config(conf_nuova, "agent") or ""
        usa_agent = agent.startswith("1") or "enabled=1" in agent
        _riga(log, db, f"VM {vmid_o} accesa: aspetto " + ("l'agent" if usa_agent else "30 s di «running»"))
        if not await _aspetta_avvio(origine, vmid_o, usa_agent, attesa_avvio_s):
            raise Fermo(f"La VM originale {vmid_o} non ha risposto entro {int(attesa_avvio_s)} s")

        # (5a) riuscito: la replica torna replica, i job ripartono
        replica_da_riaccendere = False
        esito, ident = await _replica_torna_replica(replica, vmid_r, origine, vmid_o, conf_nuova, conf_r)
        if not esito.success:
            avvisi.append(
                f"L'originale lavora, ma la replica {vmid_r} porta ancora la sua identita' "
                f"(qm set fallito: {_testo(esito)[:200]}): va riallineata a mano e NON va accesa"
            )
        for j in jobs:
            j.is_active = True
            j.richiede_replica_completa = False
            j.source_smbios_uuid = ident.get("source_smbios_uuid")
            j.source_vmgenid = ident.get("source_vmgenid")
            j.replica_smbios_uuid = ident.get("replica_smbios_uuid")
        vecchi = [d["vecchio"] for d in dett.get("dischi", {}).values() if d.get("vecchio")]
        dett["messaggio"] = (
            f"Ritorno completato: la VM {vmid_o} lavora su {origine.name}, la replica {vmid_r} e' spenta."
            + (f" Dischi vecchi da parte su {origine.name}: {', '.join(vecchi)}" if vecchi else "")
        )
        _scrivi(db, jobs, "completato", dett)
        _chiudi_log(db, log, True, dett["messaggio"] + (f" [Avvisi: {'; '.join(avvisi)}]" if avvisi else ""))
    except Exception as e:  # noqa: BLE001 - qui si decide il ritorno indietro
        motivo = str(e) if isinstance(e, Fermo) else f"Errore inatteso: {e}"
        if not isinstance(e, Fermo):
            logger.exception("ritorno: completa fallita")
        try:
            db.rollback()
            esito_indietro = ""
            if replica_da_riaccendere and origine is not None:
                esito_indietro = await _torna_alla_replica(origine, vmid_o, replica, vmid_r, originale_avviata)
            if jobs:
                dett.update(fase="completa", errore=motivo,
                            messaggio=f"Ritorno non riuscito: {motivo}. {esito_indietro}".strip())
                _scrivi(db, jobs, "fallito", dett)
            if log is not None:
                _chiudi_log(db, log, False, f"{motivo}. {esito_indietro}".strip())
        except Exception:  # pragma: no cover
            logger.exception("ritorno: stato non scritto dopo il fallimento")
    finally:
        if chiave:
            _in_corso.discard(chiave)
        db.close()


async def _torna_alla_replica(origine, vmid_o: int, replica, vmid_r: int, originale_avviata: bool) -> str:
    """(5b) Spegne l'originale e riaccende la replica. Ritorna cosa e' successo."""
    if originale_avviata:
        await _ssh(origine, f"qm stop {int(vmid_o)} 2>&1", timeout=120)
    stato_o = await stato_vm(origine, vmid_o)
    if stato_o not in ("stopped", "assente"):
        return (
            f"ATTENZIONE: la VM originale {vmid_o} e' in stato «{stato_o}»: NON ho riacceso la replica "
            f"{vmid_r} per non avere due VM con lo stesso uuid. Serve un intervento a mano."
        )
    esito = await _ssh(replica, f"qm start {int(vmid_r)} 2>&1", timeout=180)
    if esito.success:
        return f"La replica {vmid_r} e' stata riaccesa su {replica.name}: la produzione e' di nuovo li'."
    return f"ATTENZIONE: la replica {vmid_r} NON si e' riaccesa ({_testo(esito)[:200]}): accenderla a mano."
