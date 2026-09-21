"""Controllo periodico «UUID SMBIOS duplicati» sui nodi Proxmox censiti.

Due VM con lo stesso `smbios1 uuid` nello stesso cluster sono un guasto
silenzioso: Veeam esclude la sorgente dal backup («same BIOS ID») e non lo
dice a nessuno (DTS, 2026-09-21: 12 VM di produzione fuori backup per
settimane). Qui si legge una riga per VM da ogni nodo e si segnalano le
coppie; l'alert viaggia sul canale di «replica in ritardo».
"""

from __future__ import annotations

import logging
from typing import Dict, Iterable, List, Tuple

from services.replica_identity import righe_smbios_da_grep, trova_uuid_duplicati

logger = logging.getLogger(__name__)

# Un comando per nodo: `/etc/pve/nodes/*` e' l'intero cluster (pmxcfs), quindi
# ogni nodo dello stesso cluster risponde lo stesso insieme — le righe si
# fondono per (nodo, vmid) e la ripetizione non costa niente.
# `-m1`: la PRIMA riga per file, cioè la sezione principale. Le sezioni
# `[snapshot]` che seguono portano l'uuid di quando lo snapshot fu preso — in
# una replica registrata prima della 3.22.0 è quello della SORGENTE — e Veeam
# non le guarda (falso allarme DTS 2026-09-22: 9115 con 11 sezioni).
COMANDO_SMBIOS = "grep -H -m1 '^smbios1:' /etc/pve/nodes/*/qemu-server/*.conf 2>/dev/null || true"


async def raccogli_smbios(ssh_service, nodi: Iterable) -> Tuple[List[Tuple[str, int, str]], List[str]]:
    """(righe (nodo, vmid, uuid) senza doppioni, nodi che non hanno risposto)."""
    per_vm: Dict[Tuple[str, int], str] = {}
    muti: List[str] = []
    for nodo in nodi:
        try:
            esito = await ssh_service.execute(
                hostname=nodo.hostname,
                command=COMANDO_SMBIOS,
                port=nodo.ssh_port,
                username=nodo.ssh_user,
                key_path=nodo.ssh_key_path,
                timeout=20,
            )
        except Exception as e:  # pragma: no cover - difensivo
            logger.debug("uuid duplicati: %s non risponde (%s)", nodo.hostname, e)
            muti.append(nodo.name)
            continue
        if not esito.success:
            muti.append(nodo.name)
            continue
        for pve_node, vmid, u in righe_smbios_da_grep(esito.stdout):
            per_vm[(pve_node, vmid)] = u
    righe = [(n, v, u) for (n, v), u in sorted(per_vm.items())]
    return righe, muti


def descrivi_duplicati(duplicati: List[Dict[str, object]]) -> str:
    """Testo dell'alert: una riga per uuid condiviso, con le VM che lo portano."""
    righe = []
    for d in duplicati:
        vms = ", ".join(f"VM {vmid} su {nodo}" for nodo, vmid in d["vms"])  # type: ignore[union-attr]
        righe.append(f"- uuid {d['uuid']}: {vms}")
    righe.append("")
    righe.append(
        "Veeam Backup for Proxmox esclude dal backup le VM con BIOS ID duplicato. "
        "Se una delle due e' una replica registrata prima della 3.22.0: "
        "qm set <vmid replica> --smbios1 uuid=<uuid derivato> (vedi docs/identita-replica.md)."
    )
    return "\n".join(righe)


def chiavi_duplicati(duplicati: List[Dict[str, object]]) -> List[str]:
    return sorted(str(d["uuid"]) for d in duplicati)


__all__ = [
    "COMANDO_SMBIOS",
    "raccogli_smbios",
    "trova_uuid_duplicati",
    "descrivi_duplicati",
    "chiavi_duplicati",
]
