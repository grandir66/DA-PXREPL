"""Snapshot `__replicate_*` mai potati sulla destinazione (DTS, 25/11/2026).

Su DTS-PX-04 la replica della VM 115 tratteneva 4,4 T: un `__replicate_115-0_*`
per corsa dal 30/07, perché alla sorgente pvesr ne tiene uno solo e sulla
destinazione nessuno li toglieva. I nomi qui sotto hanno la forma vera.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.potatura_destinazione import pota_replicate_orfani, scegli_orfani

SORGENTE = ["prelic", "__replicate_115-0_1795539622__", "syncoid_DTS-PX-DOWN_2026-11-24:18:00:41-GMT01:00"]
DESTINAZIONE = [
    "autogold_20260729_100454",
    "__replicate_115-0_1785427215__",
    "__replicate_115-0_1794502820__",
    "__replicate_115-0_1795539622__",
    "backup_2026-11-24_17:05:00",
    "pre-gc-20261101",
    "syncoid_DTS-PX-DOWN_2026-11-24:18:00:41-GMT01:00",
]


def test_solo_i_replicate_spariti_dalla_sorgente():
    assert scegli_orfani(SORGENTE, DESTINAZIONE) == [
        "__replicate_115-0_1785427215__", "__replicate_115-0_1794502820__"]


class _Ssh:
    def __init__(self, sorgente_ok=True, sorgente=SORGENTE):
        self.comandi, self.sorgente_ok, self.sorgente = [], sorgente_ok, sorgente

    async def execute(self, hostname, command, **_):
        self.comandi.append((hostname, command))
        if command.startswith("zfs list"):
            if hostname == "src":
                return SimpleNamespace(success=self.sorgente_ok, stderr="",
                                       stdout="\n".join(f"ZFS/vm-115-disk-1@{n}" for n in self.sorgente))
            return SimpleNamespace(success=True, stderr="",
                                   stdout="\n".join(f"ZFS/replica/vm-115-disk-1@{n}" for n in DESTINAZIONE))
        return SimpleNamespace(success=True, stdout="", stderr="")


def _nodo(h):
    return SimpleNamespace(hostname=h, ssh_port=22, ssh_user="root", ssh_key_path="/k")


@pytest.mark.asyncio
async def test_distrugge_solo_sulla_destinazione_e_solo_gli_orfani():
    ssh = _Ssh()
    n = await pota_replicate_orfani(ssh, _nodo("src"), _nodo("dst"), "ZFS/vm-115-disk-1", "ZFS/replica/vm-115-disk-1")
    assert n == 2
    distruzioni = [c for c in ssh.comandi if "destroy" in c[1]]
    assert distruzioni == [("dst", "zfs destroy ZFS/replica/vm-115-disk-1@"
                            "__replicate_115-0_1785427215__,__replicate_115-0_1794502820__")]


@pytest.mark.asyncio
@pytest.mark.parametrize("ok,elenco", [(False, SORGENTE), (True, [])])
async def test_sorgente_non_letta_o_vuota_non_cancella_niente(ok, elenco):
    ssh = _Ssh(sorgente_ok=ok, sorgente=elenco)
    n = await pota_replicate_orfani(ssh, _nodo("src"), _nodo("dst"), "ZFS/vm-115-disk-1", "ZFS/replica/vm-115-disk-1")
    assert n == 0 and not [c for c in ssh.comandi if "destroy" in c[1]]
