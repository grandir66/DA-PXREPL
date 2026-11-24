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
