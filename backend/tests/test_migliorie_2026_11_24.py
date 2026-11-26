"""3.26.0 — migliorie dopo la verifica del 24/11/2026.

- DTS, 12-24/11: container spento 12 giorni; alla ripartenza le corse saltate
  aspettavano il prossimo orario. Recupero all'avvio, spento di default.
- Un nodo che non risponde dava «elenco vuoto» e la cache cancellava le sue VM.
"""
import asyncio
import subprocess
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

from database import Node, VirtualMachine
from services import scheduler as sch
from services.cache_service import CacheService, GIRI_MUTI_PER_OFFLINE

ORA = datetime(2026, 11, 24, 13, 0, 0)          # 14:00 locali
CRON = "0 2 * * *"                              # ogni notte alle 02:00 locali


def test_recupero_spento_aspetta_il_prossimo_orario():
    sch.apri_finestra_recupero(ORA, accesa=False)
    prossimo = sch.compute_initial_next_run(CRON, ORA - timedelta(days=12), ORA)
    assert prossimo > ORA


def test_recupero_acceso_fa_partire_subito_chi_ha_saltato():
    try:
        sch.apri_finestra_recupero(ORA, accesa=True)
        assert sch.compute_initial_next_run(CRON, ORA - timedelta(days=12), ORA) == ORA
        # chi ha gia' corso stanotte non riparte
        assert sch.compute_initial_next_run(CRON, ORA - timedelta(hours=11), ORA) > ORA
        # un job mai partito non ha saltato niente
        assert sch.compute_initial_next_run(CRON, None, ORA) > ORA
        # finita la finestra, niente recupero (es. un job modificato a mano ore dopo)
        dopo = ORA + timedelta(seconds=sch._RECUPERO_FINESTRA_S + 1)
        assert sch.compute_initial_next_run(CRON, ORA - timedelta(days=12), dopo) > dopo
    finally:
        sch.apri_finestra_recupero(ORA, accesa=False)


def _nodo_con_vm(db):
    n = Node(name="px-01", hostname="px-01.x", ssh_port=22, ssh_user="root", node_type="pve", is_online=True)
    db.add(n)
    db.commit()
    db.add(VirtualMachine(node_id=n.id, vmid=101, name="a", type="qemu"))
    db.commit()
    return n


def _giro(db, nodo, esito):
    svc = CacheService()
    with patch("services.host_info_service.HostInfoService.update_host_details", AsyncMock()), \
         patch("services.cache_service.CacheService._porta_aperta", AsyncMock(return_value=True)), \
         patch("services.cache_service.proxmox_service.get_cluster_resources_esito", AsyncMock(return_value=esito)), \
         patch("services.cache_service.proxmox_service.get_all_guests", AsyncMock(return_value=[])):
        for _ in range(GIRI_MUTI_PER_OFFLINE):
            asyncio.run(svc.refresh_node_vms(db, nodo))
    db.refresh(nodo)


def test_nodo_muto_non_cancella_le_vm_e_dopo_tre_giri_e_offline(db):
    nodo = _nodo_con_vm(db)
    _giro(db, nodo, (False, []))
    assert db.query(VirtualMachine).filter_by(node_id=nodo.id).count() == 1
    assert nodo.is_online is False


def test_nodo_che_risponde_aggiorna_stato_e_toglie_le_vm_sparite(db):
    nodo = _nodo_con_vm(db)
    nodo.is_online = False
    db.commit()
    risorse = [{"node": "px-01", "type": "qemu", "vmid": 202, "name": "b", "status": "running"}]
    _giro(db, nodo, (True, risorse))
    assert [v.vmid for v in db.query(VirtualMachine).filter_by(node_id=nodo.id)] == [202]
    assert nodo.is_online is True and nodo.last_check is not None


def test_rotazione_tiene_le_ultime_dieci(tmp_path):
    for i in range(14):
        f = tmp_path / f"dapx.db.pre-update-202611{i:02d}"
        f.write_text("x")
        subprocess.run(["touch", "-t", f"2026010100{i:02d}", str(f)], check=True)
    (tmp_path / "altro.txt").write_text("resta")
    funzione = subprocess.run(
        ["sed", "-n", "/^ruota_copie() {/,/^}/p", "../update.sh"], capture_output=True, text=True, check=True
    ).stdout
    subprocess.run(["bash", "-c", f'{funzione}\nruota_copie "{tmp_path}" "dapx.db.pre-update-" 10'], check=True)
    rimasti = sorted(p.name for p in tmp_path.iterdir())
    assert len(rimasti) == 11 and "altro.txt" in rimasti
    assert "dapx.db.pre-update-20261100" not in rimasti and "dapx.db.pre-update-20261113" in rimasti
