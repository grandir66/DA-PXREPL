"""Il job segue la VM: dove sta ADESSO la VM sorgente nel cluster.

Un job di replica nasce con `source_node_id` fissato al nodo su cui la VM
stava quel giorno. In un cluster Proxmox la VM si sposta — migrazione a
mano, HA — e il job partiva comunque dal nodo vecchio, cadendo sul
pre-check «dataset does not exist» senza dire perché. Da qui (3.23.0),
prima di ogni corsa si chiede al cluster dove sta la VM e, se il nodo
nuovo ha le carte in regola, si parte da lì.

Tre esiti, mai confusi fra loro (lezione DTS 2026-09-13: «non so» non si
mappa su «sì» né su «no»):

- `uguale`    — la VM sta ancora sul nodo registrato: come sempre;
- `spostata`  — sta su un altro nodo censito, raggiungibile, col dataset:
                si esegue da lì e il job lo ricorda;
- `non_so`    — il cluster non risponde o non elenca la VM: si usa il nodo
                registrato e lo si scrive nel log;
- `rifiutata` — sta su un nodo NON censito, o senza il dataset, o sul nodo
                di destinazione stesso: la corsa fallisce con un motivo
                leggibile invece di provare dal nodo vecchio.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

COMANDO_RISORSE = "pvesh get /cluster/resources --output-format json 2>/dev/null"
TTL_CACHE_S = 60

# Una chiamata per cluster per tick dello scheduler: i job di un gruppo VM
# (un disco per job) chiedono la stessa cosa a pochi secondi di distanza.
# Chiave: hostname del nodo interrogato → (istante, mappa).
_cache: Dict[str, Tuple[float, "MappaCluster"]] = {}


@dataclass
class MappaCluster:
    """Cosa dice `/cluster/resources`: nodi del cluster e posizione delle VM."""
    nodi: List[str] = field(default_factory=list)
    vm: Dict[int, str] = field(default_factory=dict)  # vmid → nome nodo PVE

    def conosce(self, nome_nodo: Optional[str]) -> bool:
        return bool(nome_nodo) and nome_nodo in self.nodi


@dataclass
class Posizione:
    esito: str                 # uguale | spostata | non_so | rifiutata
    nodo: Any                  # Node da cui eseguire (None se rifiutata)
    nodo_pve: Optional[str]    # dove il cluster dice che sta la VM
    messaggio: str

    @property
    def spostata(self) -> bool:
        return self.esito == "spostata"


def parse_risorse(stdout: str) -> Optional[MappaCluster]:
    """Legge il JSON di `/cluster/resources`. None se non è JSON leggibile."""
    try:
        dati = json.loads(stdout or "")
    except (TypeError, ValueError):
        return None
    if not isinstance(dati, list):
        return None
    mappa = MappaCluster()
    for r in dati:
        if not isinstance(r, dict):
            continue
        tipo = r.get("type")
        if tipo == "node" and r.get("node"):
            mappa.nodi.append(str(r["node"]))
        elif tipo in ("qemu", "lxc") and r.get("vmid") is not None and r.get("node"):
            try:
                mappa.vm[int(r["vmid"])] = str(r["node"])
            except (TypeError, ValueError):
                continue
    return mappa


def svuota_cache() -> None:
    _cache.clear()


async def mappa_cluster(ssh_service, nodo, *, usa_cache: bool = True) -> Optional[MappaCluster]:
    """La mappa del cluster vista dal nodo `nodo`; None se non risponde."""
    chiave = getattr(nodo, "hostname", None) or ""
    adesso = time.monotonic()
    if usa_cache and chiave in _cache:
        quando, mappa = _cache[chiave]
        if adesso - quando < TTL_CACHE_S:
            return mappa
    try:
        esito = await ssh_service.execute(
            hostname=nodo.hostname,
            command=COMANDO_RISORSE,
            port=nodo.ssh_port or 22,
            username=nodo.ssh_user or "root",
            key_path=nodo.ssh_key_path or "/root/.ssh/id_rsa",
            timeout=20,
        )
    except Exception as e:  # pragma: no cover - difensivo
        logger.debug("cluster/resources su %s: %s", chiave, e)
        return None
    if not esito.success:
        return None
    mappa = parse_risorse(esito.stdout)
    if mappa is None:
        return None
    _cache[chiave] = (adesso, mappa)
    return mappa


async def _mappa_del_cluster_di(ssh_service, db, source_node) -> Optional[MappaCluster]:
    """Prima il nodo registrato; se è lui a essere giù (HA!), un altro nodo
    censito che elenchi il nodo registrato fra i membri del cluster —
    così una mappa di un ALTRO cluster non viene scambiata per la sua."""
    mappa = await mappa_cluster(ssh_service, source_node)
    if mappa is not None and mappa.conosce(source_node.name):
        return mappa
    from database import Node

    altri = (
        db.query(Node)
        .filter(Node.is_active == True, Node.node_type == "pve", Node.id != source_node.id)  # noqa: E712
        .order_by(Node.is_online.desc(), Node.id)
        .all()
    )
    for n in altri:
        m = await mappa_cluster(ssh_service, n)
        if m is not None and m.conosce(source_node.name):
            return m
    return None


async def _dataset_presente(ssh_service, nodo, dataset: str) -> Tuple[bool, str]:
    """(presente, motivo). Solo exit 1 vale «manca»: il resto è «non risponde»."""
    esito = await ssh_service.execute(
        hostname=nodo.hostname,
        command=f"zfs list -H -o name {dataset} 2>&1",
        port=nodo.ssh_port or 22,
        username=nodo.ssh_user or "root",
        key_path=nodo.ssh_key_path or "/root/.ssh/id_rsa",
        timeout=20,
    )
    if esito.success and esito.exit_code == 0:
        return True, ""
    if esito.exit_code == 1:
        return False, f"il dataset {dataset} non esiste su {nodo.name}"
    return False, f"{nodo.name} non risponde ({(esito.stderr or esito.stdout or '').strip()[:120]})"


async def risolvi_nodo_sorgente(db, job, source_node, dest_node, *, ssh_service) -> Posizione:
    """Da quale nodo eseguire il job `job`, adesso."""
    if not getattr(job, "vm_id", None) or source_node is None:
        return Posizione("uguale", source_node, None, "")

    mappa = await _mappa_del_cluster_di(ssh_service, db, source_node)
    if mappa is None:
        return Posizione(
            "non_so", source_node, None,
            f"il cluster di {source_node.name} non risponde: uso il nodo registrato",
        )
    nome = mappa.vm.get(int(job.vm_id))
    if nome is None:
        return Posizione(
            "non_so", source_node, None,
            f"VM {job.vm_id} non è nell'elenco del cluster di {source_node.name}: uso il nodo registrato",
        )
    if nome == source_node.name:
        return Posizione("uguale", source_node, nome, "")
    if dest_node is not None and nome == dest_node.name:
        return Posizione(
            "rifiutata", None, nome,
            f"VM {job.vm_id} sta su {nome}, che è il nodo di DESTINAZIONE di questo job: "
            f"replicarla su se stessa non ha senso. Riportarla su un altro nodo o rivedere il job.",
        )

    from database import Node

    nuovo = (
        db.query(Node)
        .filter(Node.name == nome, Node.is_active == True, Node.node_type == "pve")  # noqa: E712
        .first()
    )
    if nuovo is None:
        return Posizione(
            "rifiutata", None, nome,
            f"VM {job.vm_id} è migrata su {nome}, che non è censito in DA-PXREPL: "
            f"censire il nodo (con lo stesso nome Proxmox) o riportare la VM su {source_node.name}.",
        )
    presente, motivo = await _dataset_presente(ssh_service, nuovo, job.source_dataset)
    if not presente:
        return Posizione(
            "rifiutata", None, nome,
            f"VM {job.vm_id} è migrata su {nome} ma {motivo}: impossibile replicare da lì.",
        )
    return Posizione(
        "spostata", nuovo, nome,
        f"VM {job.vm_id} trovata su {nome} (era registrata su {source_node.name}): eseguo da {nome}",
    )


def persisti_spostamento(db, job, nuovo) -> int:
    """Il job (e i dischi gemelli del gruppo) ricordano il nodo nuovo. Ritorna quanti."""
    from database import SyncJob

    gemelli = [job]
    if getattr(job, "vm_group_id", None):
        gemelli = db.query(SyncJob).filter(SyncJob.vm_group_id == job.vm_group_id).all() or [job]
    n = 0
    for g in gemelli:
        if g.source_node_id != nuovo.id:
            g.source_node_id = nuovo.id
            n += 1
    return n


def senza_snapshot_in_comune(output: Optional[str]) -> bool:
    """Il messaggio con cui syncoid si rifiuta di ricreare una destinazione
    che non ha snapshot in comune con la sorgente (dopo una migrazione live
    i dischi sono copiati con drive-mirror, senza gli snapshot ZFS)."""
    low = (output or "").lower()
    return "has no snapshots matching" in low or "cowardly refusing" in low


MARCATORE_REPLICA_COMPLETA = "[REPLICA-COMPLETA]"


def motivo_replica_completa(nodo_pve: Optional[str]) -> str:
    dove = f" su {nodo_pve}" if nodo_pve else ""
    return (
        f"{MARCATORE_REPLICA_COMPLETA} VM migrata{dove}: la destinazione non ha snapshot in comune "
        "con la sorgente (migrazione live: i dischi sono stati copiati senza gli snapshot ZFS). "
        "Serve una replica completa: «Esegui con replica completa» dal job, oppure attivare "
        "sul job «dopo una migrazione riparti con replica completa»."
    )
