"""«Ritorna all'originale»: dalla replica accesa alla VM originale, con syncoid.

Incidente DTS 2026-11-24: il 3CX (VM 103 su DTS-PX-UP) lavorava da 12 giorni
sulla replica 9103 (DTS-PX-04). Il ritorno fatto a mano ha lasciato la 103
isolata 3 minuti: la conf della replica portava `bridge=vmbr1`, che sul nodo
d'origine non ha porte; quello giusto era `vmbr_vm`. Da qui le regole:
al ritorno valgono i valori DELL'ORIGINALE, il disco vecchio si rinomina e
non si cancella, due VM con lo stesso uuid non stanno mai accese insieme.

Le conf qui sotto hanno la forma di quelle vere (103 e 9103), con uuid e MAC
di fantasia.
"""

import asyncio
import json
import re
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from database import JobLog, Node, SyncJob
from services.ssh_service import SSHResult

UUID_ORIG = "4221cbd1-1a2b-4c3d-8e9f-0a1b2c3d4e5f"
UUID_REPL = "0d7a3a3d-1a8b-5c1f-9d2e-2b3c4d5e6f70"
VMGENID_ORIG = "0c1d2e3f-4a5b-6c7d-8e9f-0a1b2c3d4e5f"
QUANDO = datetime(2026, 11, 24, 19, 33)

CONF_103 = f"""#Centralino 3CX
agent: 1
boot: order=scsi0
cores: 4
cpu: x86-64-v2-AES
memory: 8192
name: 3CX-V20
net0: virtio=BC:24:11:AA:BB:CC,bridge=vmbr_vm,tag=20
onboot: 1
ostype: l26
scsi0: ZFS:vm-103-disk-0,discard=on,size=100G
scsihw: virtio-scsi-single
smbios1: uuid={UUID_ORIG}
tags: ha;p1;r
vmgenid: {VMGENID_ORIG}

[pre-upgrade]
name: 3CX-V20
onboot: 1
smbios1: uuid={UUID_ORIG}
snaptime: 1762000000
"""

DESCR_REPLICA = (
    f"dapx-replica di VM 103 da DTS-PX-UP | smbios1 originale: uuid={UUID_ORIG} | "
    f"vmgenid originale: {VMGENID_ORIG} | attivazione DR: ripristinare smbios1 prima dello start"
    " | DR ATTIVATO 2026-11-12 08:10 UTC da admin"
)

CONF_9103 = f"""agent: 1
boot: order=scsi0
cores: 4
cpu: host
description: {DESCR_REPLICA}
memory: 8192
name: 3CX-V20-replica
net0: virtio=BC:24:11:AA:BB:CC,bridge=vmbr1
onboot: 0
ostype: l26
scsi0: ZFS-REPL:vm-103-disk-0,discard=on,size=100G
scsihw: virtio-scsi-single
smbios1: uuid={UUID_ORIG}
unused0: ZFS-REPL:vm-9103-disk-9
vmgenid: 11111111-2222-3333-4444-555555555555
"""


# ───────────────────────── Task 1: fotografia ─────────────────────────


@pytest.fixture
def nodi(db):
    src = Node(name="DTS-PX-UP", hostname="px-up.dts", ssh_port=22, ssh_user="root")
    dst = Node(name="DTS-PX-04", hostname="px-04.dts", ssh_port=22, ssh_user="root")
    db.add_all([src, dst])
    db.commit()
    return src, dst


def _job(db, nodi, disco="scsi0", n=0, **kw):
    src, dst = nodi
    j = SyncJob(
        name=f"VM 103 {disco}", source_node_id=src.id, dest_node_id=dst.id,
        source_dataset=f"ZFS/vm-103-disk-{n}", dest_dataset=f"ZFS/replica/vm-103-disk-{n}",
        register_vm=True, vm_id=103, dest_vm_id=9103, vm_type="qemu", vm_group_id="grp-103",
        disk_name=disco, source_storage="ZFS", dest_storage="ZFS-REPL",
        dest_vm_name_suffix="-replica", sync_method="syncoid", **kw,
    )
    db.add(j)
    db.commit()
    return j


def test_fotografia_salvata_su_tutti_i_dischi_del_gruppo(db, nodi):
    from services.sync_job_execution import salva_fotografia_originale

    a = _job(db, nodi, "scsi0", 0)
    b = _job(db, nodi, "scsi1", 1)
    assert salva_fotografia_originale(db, a, CONF_103) is True
    db.commit()
    for j in (a, b):
        db.refresh(j)
        assert "bridge=vmbr_vm" in j.source_config_snapshot
        assert "[pre-upgrade]" not in j.source_config_snapshot  # sezioni snapshot via
        assert j.source_config_at is not None


def test_conf_con_dapx_replica_non_sovrascrive(db, nodi):
    """Una replica promossa non deve coprire la fotografia buona dell'originale."""
    from services.sync_job_execution import salva_fotografia_originale

    a = _job(db, nodi)
    salva_fotografia_originale(db, a, CONF_103)
    assert salva_fotografia_originale(db, a, CONF_9103) is False
    assert "bridge=vmbr_vm" in a.source_config_snapshot


def test_durante_un_ritorno_la_fotografia_non_si_tocca(db, nodi):
    from services.sync_job_execution import salva_fotografia_originale

    a = _job(db, nodi)
    salva_fotografia_originale(db, a, CONF_103)
    a.ritorno_stato = "pronto"
    assert salva_fotografia_originale(db, a, CONF_103.replace("vmbr_vm", "vmbr9")) is False
    assert "bridge=vmbr_vm" in a.source_config_snapshot


def test_colonne_aggiunte_a_un_database_vecchio():
    """`update_db_schema` deve aggiungere le quattro colonne a `sync_jobs`."""
    import inspect
    import update_db_schema

    testo = inspect.getsource(update_db_schema)
    for col in ("source_config_snapshot", "source_config_at", "ritorno_stato", "ritorno_dettaglio"):
        assert f'"sync_jobs", "{col}"' in testo


# ───────────────────────── Task 2: logica pura ─────────────────────────


def test_nome_disco_vecchio_non_combacia_con_il_modello_di_proxmox():
    from services.ritorno_originale import nome_disco_vecchio

    nome = nome_disco_vecchio("ZFS/vm-103-disk-0", QUANDO)
    assert nome == "ZFS/dapx-vecchio-103-disk-0-20261124-1933"
    assert not re.match(r"^vm-\d+-disk-\d+$", nome.split("/")[-1])
    assert nome_disco_vecchio("rpool/data/vm-103-disk-1", QUANDO).startswith("rpool/data/dapx-vecchio-103-disk-1-")


def test_bridge_dell_originale_rimesso_caso_dts():
    from services.replica_identity import valore_config
    from services.ritorno_originale import config_originale_per_ritorno

    conf, avvisi = config_originale_per_ritorno(
        CONF_103, CONF_9103, {"scsi0": "ZFS:vm-103-disk-0"}, QUANDO, "riccardo", vmid_replica=9103,
    )
    assert "bridge=vmbr_vm,tag=20" in valore_config(conf, "net0")
    assert "vmbr1" not in conf
    assert valore_config(conf, "name") == "3CX-V20"
    assert valore_config(conf, "onboot") == "1"
    assert valore_config(conf, "tags") == "ha;p1;r"
    assert valore_config(conf, "smbios1") == f"uuid={UUID_ORIG}"
    assert valore_config(conf, "vmgenid") == VMGENID_ORIG
    assert valore_config(conf, "cpu") == "x86-64-v2-AES"  # hardware dalla fotografia
    assert valore_config(conf, "scsi0").startswith("ZFS:vm-103-disk-0,")
    assert "unused0" not in conf and "[pre-upgrade]" not in conf
    assert "dapx-replica" not in conf
    assert "Ripristinata da replica 9103 il 2026-11-24 19:33 da riccardo" in conf
    assert "#Centralino 3CX" in conf  # la nota dell'originale resta
    # replica e fotografia differiscono sulla cpu: lo dice
    assert any("cpu" in a for a in avvisi)


def test_senza_fotografia_nome_senza_suffisso_e_avviso():
    from services.replica_identity import valore_config
    from services.ritorno_originale import config_originale_per_ritorno

    conf_replica = CONF_9103.replace(f"smbios1: uuid={UUID_ORIG}", f"smbios1: uuid={UUID_REPL}")
    conf, avvisi = config_originale_per_ritorno(
        None, conf_replica, {"scsi0": "ZFS:vm-103-disk-0"}, QUANDO, "riccardo",
        vmid_replica=9103, suffisso_nome="-replica",
    )
    assert valore_config(conf, "name") == "3CX-V20"
    assert valore_config(conf, "smbios1") == f"uuid={UUID_ORIG}"
    assert valore_config(conf, "vmgenid") == VMGENID_ORIG
    assert valore_config(conf, "scsi0").startswith("ZFS:vm-103-disk-0,")
    assert "unused0" not in conf and "dapx-replica" not in conf
    assert any("bridge" in a and "controllare" in a for a in avvisi)


def _jd(**kw):
    base = dict(job_id=1, disk_name="scsi0", sync_method="syncoid", vm_type="qemu",
                source_dataset="ZFS/vm-103-disk-0", dest_dataset="ZFS/replica/vm-103-disk-0",
                source_esiste=True)
    base.update(kw)
    return base


def test_piano_ritorno_possibile_e_dischi():
    from services.ritorno_originale import piano_ritorno

    p = piano_ritorno([_jd(), _jd(job_id=2, disk_name="scsi1", source_esiste=False,
                                  source_dataset="ZFS/vm-103-disk-1", dest_dataset="ZFS/replica/vm-103-disk-1")],
                      "running", "stopped", True)
    assert p["possibile"] is True
    assert p["dischi"][0] == {"job_id": 1, "disk_name": "scsi0", "da": "ZFS/replica/vm-103-disk-0",
                              "a": "ZFS/vm-103-disk-0", "rinomina": True}
    assert p["dischi"][1]["rinomina"] is False


@pytest.mark.parametrize("kw, parola", [
    (dict(stato_originale="running"), "accesa"),
    (dict(stato_originale="sconosciuto"), "non"),
    (dict(replica_segnata=False), "replica"),
    (dict(jobs=[_jd(sync_method="pve_native")]), "syncoid"),
    (dict(jobs=[_jd(vm_type="lxc")]), "qemu"),
    (dict(jobs=[]), "job"),
])
def test_piano_ritorno_impossibile(kw, parola):
    from services.ritorno_originale import piano_ritorno

    arg = dict(jobs=[_jd()], stato_replica="running", stato_originale="stopped",
               conf_originale_presente=True)
    arg.update(kw)
    p = piano_ritorno(**arg)
    assert p["possibile"] is False
    assert parola in p["motivo"]


def test_piano_avvisa_se_l_originale_non_c_e_piu_e_manca_la_fotografia():
    from services.ritorno_originale import piano_ritorno

    p = piano_ritorno([_jd(source_esiste=False)], "running", "assente", False, fotografia_presente=False)
    assert p["possibile"] is True
    assert any("ricreata" in a for a in p["avvisi"])
    assert any("bridge" in a for a in p["avvisi"])
