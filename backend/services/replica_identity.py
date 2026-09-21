"""Identità della VM replicata: UUID SMBIOS, vmgenid, onboot, snapshot.

Una replica registrata sul nodo DR NON porta l'identità della sorgente
(incidente DTS 2026-09-21: Veeam escludeva dal backup 12 VM di produzione
perché le repliche avevano lo stesso BIOS UUID). Qui vivono le funzioni pure
che decidono come la replica si distingue e come si ritrova l'originale per
attivare il DR. Specifica: docs/2026-09-21-replica-identita-vm-spec.md.

Formato della `description` scritta nella replica (una riga, ASCII):

    dapx-replica di VM 101 da px-01 | smbios1 originale: uuid=<U> |
    vmgenid originale: <G> | attivazione DR: ripristinare smbios1 prima dello start

Lo stesso `smbios1 originale: uuid=` e' la forma scritta a mano su DTS il
21/09, quindi `estrai_identita_da_descrizione` legge entrambe.
"""

from __future__ import annotations

import re
import uuid
from typing import Dict, Iterable, List, Optional, Tuple

# Spazio dei nomi di DA-PXREPL per gli uuid derivati (fisso: non cambiarlo,
# o le repliche gia' registrate cambierebbero identita' alla ri-registrazione).
NAMESPACE_DAPX = uuid.UUID("7d3a1c2e-5b4f-4e6a-9c8d-0f1e2d3c4b5a")
SALE_REPLICA = "dapx-replica"
SALE_VMGENID = "vmgenid"

_RE_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_RE_SMBIOS_ORIG = re.compile(r"smbios1 originale:?\s*uuid=(" + _RE_UUID + ")")
_RE_VMGENID_ORIG = re.compile(r"vmgenid originale:?\s*(" + _RE_UUID + ")")
_RE_SORGENTE = re.compile(r"dapx-replica di VM (\d+)(?: da ([A-Za-z0-9][A-Za-z0-9.\-]*))?")


def uuid_replica(uuid_sorgente: str) -> str:
    """L'uuid della replica: derivato dalla sorgente, sempre diverso, stabile."""
    return str(uuid.uuid5(uuid.UUID(str(uuid_sorgente)), SALE_REPLICA))


def uuid_replica_senza_sorgente(source_hostname: Optional[str], source_vmid) -> str:
    """Quando la sorgente non dichiara `smbios1`: stabile su host:vmid."""
    base = uuid.uuid5(NAMESPACE_DAPX, f"{source_hostname or ''}:{source_vmid}")
    return str(uuid.uuid5(base, SALE_REPLICA))


def vmgenid_replica(uuid_replica_: str) -> str:
    """Generation id della replica: derivato dall'uuid della replica.

    Deterministico di proposito (la spec diceva uuid4): ri-registrare la
    stessa VM produce lo stesso file. Diverso dalla sorgente per costruzione.
    """
    return str(uuid.uuid5(uuid.UUID(uuid_replica_), SALE_VMGENID))


def rimuovi_sezioni_snapshot(config: str) -> str:
    """Tiene solo la sezione principale del .conf e toglie `parent:`.

    Le sezioni `[nome]` sono gli snapshot della SORGENTE: copiate nella
    replica portano il suo uuid e il suo onboot, e un `qm rollback` sulla
    replica li riporterebbe in vita.
    """
    righe: List[str] = []
    for riga in config.splitlines():
        if re.match(r"^\[.+\]\s*$", riga):
            break
        if riga.startswith("parent:"):
            continue
        righe.append(riga)
    while righe and righe[-1].strip() == "":
        righe.pop()
    return "\n".join(righe) + "\n" if righe else ""


def valore_config(config: str, chiave: str) -> Optional[str]:
    """Il valore di `chiave:` nella sezione (prima riga che la porta), o None."""
    m = re.search(rf"^{re.escape(chiave)}:\s*(.*)$", config or "", re.MULTILINE)
    return m.group(1).strip() if m else None


_valore = valore_config


def _imposta(config: str, chiave: str, valore: str) -> str:
    """Sostituisce la riga `chiave:` (la prima) o la aggiunge in coda."""
    pattern = re.compile(rf"^{re.escape(chiave)}:.*$", re.MULTILINE)
    if pattern.search(config):
        return pattern.sub(f"{chiave}: {valore}", config, count=1)
    return config.rstrip("\n") + f"\n{chiave}: {valore}\n"


def uuid_da_smbios1(valore_smbios1: Optional[str]) -> Optional[str]:
    if not valore_smbios1:
        return None
    m = re.search(r"(?:^|,)uuid=(" + _RE_UUID + ")", valore_smbios1)
    return m.group(1).lower() if m else None


def descrizione_replica(
    *,
    source_vmid,
    source_hostname: Optional[str],
    source_smbios_uuid: Optional[str],
    source_vmgenid: Optional[str],
) -> str:
    """Una riga, solo ASCII: il file lo scrive un heredoc, non `qm set`,
    quindi niente accenti, niente `%` (PVE lo decodifica), niente a capo."""
    testa = "dapx-replica"
    if source_vmid is not None:
        testa += f" di VM {source_vmid}"
        if source_hostname:
            testa += f" da {source_hostname}"
    pezzi = [testa]
    if source_smbios_uuid:
        pezzi.append(f"smbios1 originale: uuid={source_smbios_uuid}")
    if source_vmgenid:
        pezzi.append(f"vmgenid originale: {source_vmgenid}")
    pezzi.append("attivazione DR: ripristinare smbios1 prima dello start")
    testo = " | ".join(pezzi)
    return testo.encode("ascii", "ignore").decode("ascii").replace("%", "").replace("\n", " ")


def estrai_identita_da_descrizione(description: Optional[str]) -> Dict[str, object]:
    """Legge gli originali dalla description di una replica (forma nuova o a mano).

    Ritorna {} se la description non e' di una replica: e' il segnale che
    `activate-dr` non ha niente da ripristinare.
    """
    if not description:
        return {}
    testo = description.replace("%0A", " ").replace("%3A", ":")
    out: Dict[str, object] = {}
    m = _RE_SMBIOS_ORIG.search(testo)
    if m:
        out["source_smbios_uuid"] = m.group(1).lower()
    m = _RE_VMGENID_ORIG.search(testo)
    if m:
        out["source_vmgenid"] = m.group(1).lower()
    m = _RE_SORGENTE.search(testo)
    if m:
        out["source_vmid"] = int(m.group(1))
        if m.group(2):
            out["source_hostname"] = m.group(2)
    return out


def identita_replica(
    config_sorgente: str,
    *,
    source_hostname: Optional[str] = None,
    source_vmid=None,
    vmid_replica=None,
) -> Dict[str, Optional[str]]:
    """Gli originali della sorgente e i valori che la replica portera'.

    `vmid_replica` serve solo al ripiego (sorgente senza `smbios1` e senza
    vmid sorgente noto, cioe' la registrazione manuale dalla pagina VM).
    """
    principale = rimuovi_sezioni_snapshot(config_sorgente or "")
    src_uuid = uuid_da_smbios1(_valore(principale, "smbios1"))
    src_vmgenid = _valore(principale, "vmgenid")
    if src_vmgenid and not re.fullmatch(_RE_UUID, src_vmgenid):
        # `vmgenid: 1` chiede a PVE di generarlo: non e' un valore da conservare
        src_vmgenid = None
    if src_uuid:
        rep_uuid = uuid_replica(src_uuid)
    else:
        rep_uuid = uuid_replica_senza_sorgente(
            source_hostname, source_vmid if source_vmid is not None else vmid_replica
        )
    return {
        "source_smbios_uuid": src_uuid,
        "source_vmgenid": src_vmgenid,
        "replica_smbios_uuid": rep_uuid,
        "replica_vmgenid": vmgenid_replica(rep_uuid),
    }


def applica_identita_replica(
    config: str,
    *,
    vm_type: str = "qemu",
    source_hostname: Optional[str] = None,
    source_vmid=None,
    vmid_replica=None,
) -> Tuple[str, Dict[str, Optional[str]]]:
    """Trasforma la config sorgente in quella della replica (parte identita').

    qemu: sezioni snapshot via, uuid derivato, vmgenid derivato, onboot 0,
    description con gli originali. lxc: solo onboot 0 (non ha smbios/vmgenid).
    Ritorna (config, identita').
    """
    if vm_type != "qemu":
        return _imposta(config, "onboot", "0"), {}

    ident = identita_replica(
        config, source_hostname=source_hostname, source_vmid=source_vmid, vmid_replica=vmid_replica
    )
    out = rimuovi_sezioni_snapshot(config)

    smbios = _valore(out, "smbios1")
    if smbios and ident["source_smbios_uuid"]:
        nuovo = re.sub(
            r"((?:^|,)uuid=)" + _RE_UUID, rf"\g<1>{ident['replica_smbios_uuid']}", smbios, count=1
        )
        out = _imposta(out, "smbios1", nuovo)
    else:
        out = _imposta(out, "smbios1", f"uuid={ident['replica_smbios_uuid']}")

    out = _imposta(out, "vmgenid", ident["replica_vmgenid"] or "")
    out = _imposta(out, "onboot", "0")

    desc = descrizione_replica(
        source_vmid=source_vmid,
        source_hostname=source_hostname,
        source_smbios_uuid=ident["source_smbios_uuid"],
        source_vmgenid=ident["source_vmgenid"],
    )
    esistente = _valore(out, "description")
    if esistente and "dapx-replica" not in esistente:
        desc = f"{desc} | {esistente}"
    out = _imposta(out, "description", desc)
    return out, ident


def trova_uuid_duplicati(righe: Iterable[Tuple[str, int, str]]) -> List[Dict[str, object]]:
    """Da (nodo, vmid, uuid) alle coppie (o terne) che condividono l'uuid."""
    per_uuid: Dict[str, List[Tuple[str, int]]] = {}
    for nodo, vmid, u in righe:
        if not u:
            continue
        per_uuid.setdefault(str(u).lower(), []).append((nodo, int(vmid)))
    out = []
    for u in sorted(per_uuid):
        vms = sorted(set(per_uuid[u]))
        if len(vms) > 1:
            out.append({"uuid": u, "vms": vms})
    return out


def righe_smbios_da_grep(stdout: str) -> List[Tuple[str, int, str]]:
    """Legge `grep -H '^smbios1:' /etc/pve/nodes/*/qemu-server/*.conf`.

    Una riga per VM: `/etc/pve/nodes/px-01/qemu-server/101.conf:smbios1: uuid=…`.
    Righe che non hanno quella forma (o senza uuid) si scartano; di uno stesso
    file conta solo la PRIMA riga (la sezione principale: le altre sono
    sezioni `[snapshot]`, con l'uuid di allora).
    """
    out: List[Tuple[str, int, str]] = []
    visti: set = set()
    pat = re.compile(r"^/etc/pve/nodes/([^/]+)/qemu-server/(\d+)\.conf:smbios1:\s*(.*)$")
    for riga in (stdout or "").splitlines():
        m = pat.match(riga.strip())
        if not m:
            continue
        chiave = (m.group(1), int(m.group(2)))
        if chiave in visti:
            # righe successive dello stesso file = sezioni [snapshot]: non contano
            continue
        u = uuid_da_smbios1(m.group(3))
        if u:
            visti.add(chiave)
            out.append((chiave[0], chiave[1], u))
    return out


def identita_replica_da_config_viva(config) -> Dict[str, object]:
    """Per la UI: e' una replica? con quale uuid originale? il DR e' gia' attivo?

    `config` e' il dict di `pvesh get .../config` (description decodificata)
    oppure il testo di `qm config`.
    """
    if isinstance(config, dict):
        descr = config.get("description")
        smbios = config.get("smbios1")
    else:
        descr = valore_config(config or "", "description")
        smbios = valore_config(config or "", "smbios1")
    ident = estrai_identita_da_descrizione(descr)
    attuale = uuid_da_smbios1(smbios)
    if not ident.get("source_smbios_uuid"):
        return {"is_replica": False}
    return {
        "is_replica": True,
        "source_smbios_uuid": ident["source_smbios_uuid"],
        "source_vmgenid": ident.get("source_vmgenid"),
        "source_vmid": ident.get("source_vmid"),
        "source_hostname": ident.get("source_hostname"),
        "current_smbios_uuid": attuale,
        "dr_attivo": bool(attuale) and attuale == ident["source_smbios_uuid"],
    }
