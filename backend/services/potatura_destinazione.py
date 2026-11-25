"""Snapshot della replica nativa di Proxmox che restano sulla destinazione.

Incidente (DTS, misurato il 25 novembre 2026): dove gira anche `pvesr`, la
sorgente tiene UN solo snapshot `__replicate_<job>_<ora>__` per disco e lo
sostituisce a ogni giro. Syncoid porta sulla destinazione quello presente al
momento della corsa; alla sorgente pvesr lo toglie, sulla destinazione non lo
toglieva nessuno: 1142 snapshot su DTS-PX-04, 4,4 T trattenuti dalla sola
replica della VM 115 (un `__replicate_` per corsa dal 30/07).

Dopo una corsa riuscita si tolgono dalla destinazione i `__replicate_*` che
alla sorgente non esistono più. Non si tocca nient'altro: `syncoid_*` (base
dell'incrementale), `backup_*` (conservazione del job), snapshot di Sanoid e
manuali. Se l'elenco della sorgente non si riesce a leggere, o torna vuoto,
non si cancella niente: un errore non è «alla sorgente non c'è più».
"""

from __future__ import annotations

import logging
import re
from typing import Iterable, List, Tuple

logger = logging.getLogger("dapx.potatura_destinazione")

FAMIGLIA = re.compile(r"^__replicate_[0-9]+-[0-9]+_[0-9]+__$")
TETTO_PER_CORSA = 500
_A_BLOCCHI_DI = 50


def scegli_orfani(nomi_sorgente: Iterable[str], nomi_destinazione: Iterable[str]) -> List[str]:
    """I `__replicate_*` della destinazione che la sorgente non ha più.

    Riceve i nomi senza dataset (la parte dopo `@`), nell'ordine di creazione.
    """
    alla_sorgente = set(nomi_sorgente)
    return [n for n in nomi_destinazione if FAMIGLIA.match(n) and n not in alla_sorgente][:TETTO_PER_CORSA]


def _nomi(stdout: str) -> List[str]:
    return [r.split("@", 1)[1].strip() for r in (stdout or "").splitlines() if "@" in r]


async def _elenco(ssh_service, node, dataset: str) -> Tuple[bool, List[str]]:
    r = await ssh_service.execute(
        hostname=node.hostname,
        command=f"zfs list -H -t snapshot -o name -s creation -d 1 {dataset}",
        port=node.ssh_port, username=node.ssh_user, key_path=node.ssh_key_path, timeout=60,
    )
    return bool(r.success), _nomi(r.stdout)


async def pota_replicate_orfani(ssh_service, source_node, dest_node,
                                source_dataset: str, dest_dataset: str) -> int:
    """Toglie gli orfani e dice quanti. Non solleva: la replica è già riuscita."""
    try:
        ok_s, sorgente = await _elenco(ssh_service, source_node, source_dataset)
        if not ok_s or not sorgente:
            logger.warning("Potatura __replicate_ saltata su %s: elenco della sorgente %s non letto o vuoto",
                           dest_dataset, source_dataset)
            return 0
        ok_d, destinazione = await _elenco(ssh_service, dest_node, dest_dataset)
        if not ok_d:
            logger.warning("Potatura __replicate_ saltata: elenco di %s non letto", dest_dataset)
            return 0
        orfani = scegli_orfani(sorgente, destinazione)
        tolti = 0
        for i in range(0, len(orfani), _A_BLOCCHI_DI):
            blocco = orfani[i:i + _A_BLOCCHI_DI]
            r = await ssh_service.execute(
                hostname=dest_node.hostname,
                command=f"zfs destroy {dest_dataset}@{','.join(blocco)}",
                port=dest_node.ssh_port, username=dest_node.ssh_user,
                key_path=dest_node.ssh_key_path, timeout=600,
            )
            if r.success:
                tolti += len(blocco)
            else:
                logger.warning("Potatura __replicate_ su %s fallita: %s", dest_dataset, (r.stderr or "")[:300])
                break
        if tolti:
            logger.info("Potati %d snapshot __replicate_ orfani su %s (da %s a %s)",
                        tolti, dest_dataset, orfani[0], orfani[tolti - 1])
        return tolti
    except Exception as e:  # la replica è riuscita: la potatura non la fa fallire, ma si vede
        logger.warning("Potatura __replicate_ su %s interrotta: %s", dest_dataset, e)
        return 0
