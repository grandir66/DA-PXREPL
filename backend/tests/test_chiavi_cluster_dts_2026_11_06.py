"""Chiavi sparite dal cluster DTS (6 novembre 2026, 07:25).

`/etc/pve/priv/authorized_keys` (condiviso dai tre nodi, ~/.ssh/authorized_keys
ne è un link) si è ritrovato senza la chiave di `dts-repl` (dapx-unified) e
senza quella di DTS-PX-04. Da lì tutte le repliche verso PX-04 e i backup della
configurazione di UP e DOWN sono falliti, per due giorni, con messaggi falsi:
«Dataset sorgente non trovato» e «Nessun file di configurazione trovato».

Cause, provate qui una per una:

1. `_ensure_executor_authorized` riscriveva l'INTERO file del cluster a ogni
   corsa di ogni job (`awk > tmp; cat tmp > authorized_keys`), con un tmp dal
   nome fisso e senza alcuna serializzazione: due job insieme verso PX-04 →
   uno legge il file mentre l'altro lo tronca → righe perse.
2. Un errore di trasporto SSH (exit_code -1) veniva letto come risposta
   negativa del comando.

Le prove sul file eseguono il comando generato con bash vero, su una HOME
temporanea dove authorized_keys è un link simbolico, come su Proxmox.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from services.ssh_service import SSHResult
from services.syncoid_service import SyncoidService

CHIAVE_EXECUTOR = "ssh-rsa AAAAexecutorNUOVA root@DTS-PX-UP"
ALTRE = [
    "ssh-ed25519 AAAAzabbix wizard@da-zabbix",
    "ssh-rsa AAAAorchestratore dapx-unified@dapx-unified",
    "ssh-rsa AAAApx04 root@DTS-PX-04",
]


def _casa(tmp_path: Path, righe: list[str]) -> tuple[Path, Path]:
    """HOME finta con ~/.ssh/authorized_keys -> cluster/authorized_keys."""
    home = tmp_path / "home"
    (home / ".ssh").mkdir(parents=True)
    cluster = tmp_path / "cluster" / "authorized_keys"
    cluster.parent.mkdir()
    cluster.write_text("".join(r + "\n" for r in righe))
    (home / ".ssh" / "authorized_keys").symlink_to(cluster)
    return home, cluster


def _finto_execute(home: Path, pubkey: str = CHIAVE_EXECUTOR, stato: dict | None = None):
    """ssh_service.execute finto: la lettura della pub key risponde subito,
    ogni altro comando gira in bash vero con HOME=home. Conta le esecuzioni
    contemporanee sul file delle chiavi."""
    stato = stato if stato is not None else {}
    stato.setdefault("in_volo", 0)
    stato.setdefault("max_in_volo", 0)

    async def finto(hostname, command, **kw):
        if command.startswith("cat ~/.ssh/id_rsa.pub"):
            k = pubkey(hostname) if callable(pubkey) else pubkey
            return SSHResult(True, k + "\n", "", 0)
        stato["in_volo"] += 1
        stato["max_in_volo"] = max(stato["max_in_volo"], stato["in_volo"])
        try:
            await asyncio.sleep(0.02)  # dà modo a un'altra corsa di entrare
            p = subprocess.run(
                ["bash", "-c", command],
                env={**os.environ, "HOME": str(home)},
                capture_output=True, text=True, timeout=20,
            )
            return SSHResult(p.returncode == 0, p.stdout, p.stderr, p.returncode)
        finally:
            stato["in_volo"] -= 1

    return finto


async def _autorizza(svc: SyncoidService, executor: str = "172.16.1.141"):
    await svc._ensure_executor_authorized(
        executor_host=executor, executor_port=22, executor_user="root",
        executor_key="/k", endpoints=[("172.16.1.144", 22)],
    )


@pytest.mark.asyncio
async def test_chiave_gia_presente_il_file_del_cluster_non_si_tocca(tmp_path):
    riga = f"{CHIAVE_EXECUTOR} # dapx-executor:172.16.1.141"
    home, cluster = _casa(tmp_path, ALTRE + [riga])
    os.utime(cluster, ns=(1_000_000_000, 1_000_000_000))
    prima = cluster.stat().st_mtime_ns

    with patch("services.syncoid_service.ssh_service.execute", _finto_execute(home)):
        await _autorizza(SyncoidService())

    assert cluster.stat().st_mtime_ns == prima, "riscritto un file che non andava toccato"
    assert cluster.read_text().splitlines() == ALTRE + [riga]


@pytest.mark.asyncio
async def test_chiave_nuova_aggiunta_senza_perdere_le_altre_e_link_intatto(tmp_path):
    vecchia = "ssh-rsa AAAAexecutorVECCHIA root@DTS-PX-UP # dapx-executor:172.16.1.141"
    home, cluster = _casa(tmp_path, ALTRE + [vecchia])

    with patch("services.syncoid_service.ssh_service.execute", _finto_execute(home)):
        await _autorizza(SyncoidService())

    link = home / ".ssh" / "authorized_keys"
    assert link.is_symlink(), "il link al file del cluster è stato sostituito"
    righe = cluster.read_text().splitlines()
    assert righe == ALTRE + [f"{CHIAVE_EXECUTOR} # dapx-executor:172.16.1.141"]
    assert not list((home / ".ssh").glob("authorized_keys.dapx*")), "tmp rimasto"


@pytest.mark.asyncio
async def test_corse_contemporanee_non_scrivono_mai_insieme(tmp_path):
    """Sei job che partono alla stessa ora verso PX-04 (01:00 a DTS): le
    modifiche al file del cluster devono passare una alla volta."""
    home, cluster = _casa(tmp_path, ALTRE)
    stato: dict = {}
    svc = SyncoidService()

    f = _finto_execute(
        home, pubkey=lambda h: f"ssh-rsa AAAAexec{h.rsplit('.', 1)[1]} root@{h}", stato=stato,
    )
    with patch("services.syncoid_service.ssh_service.execute", f):
        await asyncio.gather(*(_autorizza(svc, executor=f"10.0.0.{i}") for i in range(6)))

    assert stato["max_in_volo"] == 1, f"{stato['max_in_volo']} scritture insieme sul file del cluster"
    righe = cluster.read_text().splitlines()
    for r in ALTRE:
        assert r in righe, f"persa: {r}"
    assert len(righe) == len(ALTRE) + 6


@pytest.mark.asyncio
async def test_preflight_errore_ssh_non_diventa_dataset_non_trovato():
    svc = SyncoidService()

    async def finto(hostname, command, **kw):
        if command.startswith("cat ~/.ssh/id_rsa.pub"):
            return SSHResult(False, "", "Authentication failed.", -1)
        return SSHResult(False, "", f"{hostname} in quarantena SSH per altri 57s dopo: Authentication failed.", -1)

    with patch("services.syncoid_service.ssh_service.execute", finto), \
         patch.object(svc, "_ensure_known_hosts", return_value=None):
        r = await svc.run_sync(
            source_dataset="ZFS/vm-130-disk-0",
            dest_dataset="ZFS/replica/vm-130-disk-0",
            dest_host="172.16.1.144",
            source_host="172.16.1.141",
            executor_host="172.16.1.141",
        )

    assert r["success"] is False
    assert "non trovato" not in r["error"], r["error"]
    assert "SSH" in r["error"] and "172.16.1.141" in r["error"]


@pytest.mark.asyncio
async def test_backup_config_errore_ssh_non_diventa_nessun_file():
    from services.host_backup_service import host_backup_service

    async def finto(hostname, command, **kw):
        return SSHResult(False, "", "Authentication failed.", -1)

    with patch("services.host_backup_service.ssh_service.execute", finto):
        r = await host_backup_service.create_host_backup(hostname="172.16.1.141")

    assert r["success"] is False
    assert "Nessun file" not in r["error"], r["error"]
    assert "SSH" in r["error"] and "172.16.1.141" in r["error"]
