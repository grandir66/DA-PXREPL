"""Identità della VM replicata: UUID, vmgenid, onboot, snapshot, description.

Incidente DTS 2026-09-21: `register_vm` copiava la config sorgente cambiando
solo nome/storage/cpu/rete, quindi la replica portava lo STESSO `smbios1 uuid`
della produzione. Veeam Backup for Proxmox identifica le VM col BIOS UUID e,
trovandone due uguali, escludeva la SORGENTE dal backup («Another VM in the
cluster or node has the same BIOS ID»): 12 VM di produzione fuori backup, una
per replica registrata. In più `onboot: 1` ereditato — tre repliche sarebbero
partite da sole al riavvio del nodo DR con lo stesso MAC e IP della
produzione — e le sezioni `[snapshot]` copiate, con dentro l'UUID sorgente.

Specifica: docs/2026-09-21-replica-identita-vm-spec.md. Ogni prova qui è
stata vista FALLIRE sul codice precedente prima di essere tenuta buona.
"""

import re
import uuid

import pytest

from services.proxmox_service import prepara_config_replica
from services.replica_identity import (
    NAMESPACE_DAPX,
    descrizione_replica,
    estrai_identita_da_descrizione,
    identita_replica,
    rimuovi_sezioni_snapshot,
    trova_uuid_duplicati,
    uuid_replica,
    vmgenid_replica,
)

UUID_SORGENTE = "6f5d9e1a-2b3c-4d5e-8f90-1a2b3c4d5e6f"
VMGENID_SORGENTE = "0c1d2e3f-4a5b-6c7d-8e9f-0a1b2c3d4e5f"

CONFIG_QEMU = f"""agent: 1
boot: order=scsi0
cores: 4
cpu: x86-64-v2-AES
memory: 8192
name: 3CX-V20
net0: virtio=BC:24:11:AA:BB:CC,bridge=vmbr0,tag=17
onboot: 1
ostype: l26
parent: pre-upgrade
scsi0: local-zfs:vm-101-disk-0,size=64G
scsihw: virtio-scsi-single
smbios1: uuid={UUID_SORGENTE}
sockets: 1
vmgenid: {VMGENID_SORGENTE}

[pre-upgrade]
cores: 4
memory: 8192
name: 3CX-V20
net0: virtio=BC:24:11:AA:BB:CC,bridge=vmbr0,tag=17
onboot: 1
scsi0: local-zfs:vm-101-disk-0,size=64G
smbios1: uuid={UUID_SORGENTE}
snaptime: 1726000000
vmgenid: {VMGENID_SORGENTE}
"""

CONFIG_LXC = """arch: amd64
cores: 2
hostname: web01
memory: 2048
net0: name=eth0,bridge=vmbr0,hwaddr=BC:24:11:11:22:33,ip=dhcp
onboot: 1
ostype: debian
rootfs: local-zfs:subvol-200-disk-0,size=16G
"""


def _valore(config: str, chiave: str) -> str | None:
    m = re.search(rf"^{re.escape(chiave)}:\s*(.*)$", config, re.MULTILINE)
    return m.group(1).strip() if m else None


def _prepara(config: str = CONFIG_QEMU, **kw) -> tuple[str, list[str]]:
    kw.setdefault("vmid", 9101)
    kw.setdefault("vm_type", "qemu")
    kw.setdefault("source_hostname", "px-01")
    kw.setdefault("source_vmid", 101)
    return prepara_config_replica(config, **kw)


# --- 1. UUID: diverso, derivato, deterministico ------------------------------

def test_uuid_replica_diverso_dalla_sorgente_e_derivato():
    config, _ = _prepara()
    smbios = _valore(config, "smbios1")
    assert smbios is not None
    atteso = str(uuid.uuid5(uuid.UUID(UUID_SORGENTE), "dapx-replica"))
    assert smbios == f"uuid={atteso}"
    assert UUID_SORGENTE not in smbios


def test_uuid_replica_deterministico_su_due_registrazioni():
    """Ri-registrare la stessa VM deve dare lo stesso file: Veeam non deve
    vedere una VM nuova a ogni riconciliazione."""
    a, _ = _prepara()
    b, _ = _prepara()
    assert _valore(a, "smbios1") == _valore(b, "smbios1")
    assert _valore(a, "vmgenid") == _valore(b, "vmgenid")


def test_uuid_replica_conserva_gli_altri_attributi_di_smbios1():
    config = CONFIG_QEMU.replace(
        f"smbios1: uuid={UUID_SORGENTE}",
        f"smbios1: uuid={UUID_SORGENTE},manufacturer=RG9tYXJj,base64=1",
    )
    out, _ = _prepara(config)
    smbios = _valore(out, "smbios1")
    assert smbios.endswith(",manufacturer=RG9tYXJj,base64=1")
    assert smbios.startswith(f"uuid={uuid_replica(UUID_SORGENTE)}")


def test_smbios1_assente_viene_aggiunto_stabile():
    config = "\n".join(
        r for r in CONFIG_QEMU.splitlines() if not r.startswith("smbios1:")
    ) + "\n"
    out, _ = _prepara(config)
    smbios = _valore(out, "smbios1")
    base = uuid.uuid5(NAMESPACE_DAPX, "px-01:101")
    assert smbios == f"uuid={uuid.uuid5(base, 'dapx-replica')}"
    # e solo una volta (la sezione principale, non gli snapshot)
    assert out.count("smbios1:") == 1


# --- 2. vmgenid e onboot -------------------------------------------------------

def test_vmgenid_diverso_dalla_sorgente():
    config, _ = _prepara()
    assert _valore(config, "vmgenid") not in (None, VMGENID_SORGENTE)
    uuid.UUID(_valore(config, "vmgenid"))  # e' un uuid valido


def test_onboot_zero_sempre():
    config, _ = _prepara()
    assert _valore(config, "onboot") == "0"


def test_onboot_zero_aggiunto_se_la_sorgente_non_lo_ha():
    senza = "\n".join(
        r for r in CONFIG_QEMU.splitlines() if not r.startswith("onboot:")
    ) + "\n"
    config, _ = _prepara(senza)
    assert _valore(config, "onboot") == "0"
    assert config.count("onboot:") == 1


# --- 3. MAC e rete invariati ---------------------------------------------------

def test_mac_invariato_bridge_e_tag_seguono_le_regole_esistenti():
    config, _ = _prepara(dest_bridge="vmbr1", dest_vlan=117)
    net0 = _valore(config, "net0")
    assert "virtio=BC:24:11:AA:BB:CC" in net0
    assert "bridge=vmbr1" in net0
    assert "tag=117" in net0


# --- 4. sezioni snapshot e parent ---------------------------------------------

def test_nessuna_sezione_snapshot_ne_parent_nella_replica():
    config, _ = _prepara()
    assert not re.search(r"^\[.+\]$", config, re.MULTILINE), config
    assert "parent:" not in config
    assert "snaptime:" not in config
    # la sezione principale resta intera
    assert _valore(config, "scsi0") == "local-zfs:vm-101-disk-0,size=64G"
    assert _valore(config, "memory") == "8192"


def test_rimuovi_sezioni_snapshot_senza_sezioni_e_neutra():
    piatta = "name: x\nmemory: 512\n"
    assert rimuovi_sezioni_snapshot(piatta) == piatta


# --- 5. description con gli originali ----------------------------------------

def test_description_porta_gli_originali_e_la_sorgente():
    config, _ = _prepara()
    desc = _valore(config, "description")
    assert desc is not None
    assert f"smbios1 originale: uuid={UUID_SORGENTE}" in desc
    assert f"vmgenid originale: {VMGENID_SORGENTE}" in desc
    assert "VM 101" in desc and "px-01" in desc
    assert config.count("description:") == 1
    # ASCII puro, una riga sola: il file lo scrive un heredoc, non `qm set`
    assert desc.isascii()
    assert "\n" not in desc and "%" not in desc


def test_description_esistente_viene_conservata_in_coda():
    config = "description: nota del sysadmin\n" + CONFIG_QEMU
    out, _ = _prepara(config)
    desc = _valore(out, "description")
    assert desc.startswith("dapx-replica")
    assert desc.endswith("nota del sysadmin")
    assert out.count("description:") == 1


def test_estrai_identita_legge_la_forma_scritta_a_mano_su_px04():
    """Le 12 repliche corrette a mano su DTS il 21/09 portano questa forma:
    `activate-dr` deve saperla leggere, nel DB non hanno niente."""
    a_mano = (
        f"dapx-replica di VM 101 | smbios1 originale: uuid={UUID_SORGENTE} | "
        f"per attivare il DR: qm set 9101 --smbios1 uuid={UUID_SORGENTE} (poi start)"
    )
    ident = estrai_identita_da_descrizione(a_mano)
    assert ident["source_smbios_uuid"] == UUID_SORGENTE
    assert ident.get("source_vmgenid") is None


def test_estrai_identita_legge_la_forma_nuova_e_il_vuoto():
    desc = descrizione_replica(
        source_vmid=101, source_hostname="px-01",
        source_smbios_uuid=UUID_SORGENTE, source_vmgenid=VMGENID_SORGENTE,
    )
    ident = estrai_identita_da_descrizione(desc)
    assert ident == {
        "source_smbios_uuid": UUID_SORGENTE,
        "source_vmgenid": VMGENID_SORGENTE,
        "source_vmid": 101,
        "source_hostname": "px-01",
    }
    assert estrai_identita_da_descrizione("") == {}
    assert estrai_identita_da_descrizione("VM di produzione") == {}


def test_identita_replica_da_config_sorgente():
    ident = identita_replica(CONFIG_QEMU, source_hostname="px-01", source_vmid=101)
    assert ident["source_smbios_uuid"] == UUID_SORGENTE
    assert ident["source_vmgenid"] == VMGENID_SORGENTE
    assert ident["replica_smbios_uuid"] == uuid_replica(UUID_SORGENTE)
    assert ident["replica_vmgenid"] == vmgenid_replica(uuid_replica(UUID_SORGENTE))


# --- 6. lxc: solo onboot -------------------------------------------------------

def test_lxc_cambia_solo_onboot():
    out, _ = _prepara(CONFIG_LXC, vmid=9200, vm_type="lxc", source_vmid=200)
    atteso = CONFIG_LXC.replace("onboot: 1", "onboot: 0").rstrip() + "\ntags: REPL\n"
    assert out == atteso


# --- 7. il pezzo di register_vm che scrive il file usa la stessa funzione ----

@pytest.mark.asyncio
async def test_register_vm_scrive_la_config_preparata():
    """Il .conf scritto sul nodo e' l'uscita di prepara_config_replica: nessun
    percorso parallelo che copi la sorgente com'e'."""
    from unittest.mock import AsyncMock, patch
    from services.proxmox_service import proxmox_service
    from services.ssh_service import SSHResult

    scritti: list[str] = []

    async def finto(hostname, command, **kw):
        if "cat > " in command:
            scritti.append(command)
            return SSHResult(success=True, stdout="Configuration created", stderr="", exit_code=0)
        if "qm status" in command and "test -f" in command:
            return SSHResult(success=True, stdout="", stderr="", exit_code=1)
        return SSHResult(success=True, stdout="status: stopped", stderr="", exit_code=0)

    with patch("services.proxmox_service.ssh_service.execute", AsyncMock(side_effect=finto)), \
         patch("services.proxmox_service.ensure_vm_replication_tag", AsyncMock(return_value=(True, "ok"))):
        ok, msg, _ = await proxmox_service.register_vm(
            hostname="px-04", vmid=9101, vm_type="qemu", config_content=CONFIG_QEMU,
            source_hostname="px-01", source_vmid=101,
        )
    assert ok, msg
    assert len(scritti) == 1
    assert UUID_SORGENTE not in scritti[0].split("VMCONF_EOF")[1].replace(
        f"smbios1 originale: uuid={UUID_SORGENTE}", ""
    )
    assert "onboot: 0" in scritti[0]
    assert "[pre-upgrade]" not in scritti[0]


# --- 8. controllo duplicati ----------------------------------------------------

def test_trova_uuid_duplicati_segnala_la_coppia_giusta():
    righe = [
        ("px-01", 101, UUID_SORGENTE),
        ("px-04", 9101, UUID_SORGENTE),
        ("px-02", 102, "11111111-2222-3333-4444-555555555555"),
    ]
    dup = trova_uuid_duplicati(righe)
    assert dup == [
        {"uuid": UUID_SORGENTE, "vms": [("px-01", 101), ("px-04", 9101)]},
    ]


def test_trova_uuid_duplicati_nessuno_se_tutti_diversi():
    righe = [
        ("px-01", 101, UUID_SORGENTE),
        ("px-04", 9101, uuid_replica(UUID_SORGENTE)),
    ]
    assert trova_uuid_duplicati(righe) == []


def test_registrazione_manuale_senza_sorgente_nota():
    """La rotta manuale (/vms/node/{id}/register) non sa da dove viene la
    config: la description non deve inventare un VMID sorgente, e l'uuid di
    ripiego (sorgente senza smbios1) resta stabile sul vmid di destinazione."""
    senza_smbios = "\n".join(
        r for r in CONFIG_QEMU.splitlines() if not r.startswith("smbios1:")
    ) + "\n"
    out, _ = prepara_config_replica(senza_smbios, vmid=9101, vm_type="qemu")
    desc = _valore(out, "description")
    assert desc.startswith("dapx-replica |")
    assert "di VM" not in desc
    base = uuid.uuid5(NAMESPACE_DAPX, ":9101")
    assert _valore(out, "smbios1") == f"uuid={uuid.uuid5(base, 'dapx-replica')}"


# --- 9. l'identita' si salva nel DB, su tutti i dischi del gruppo -------------

def test_salva_identita_replica_su_tutti_i_job_del_gruppo(db):
    from database import Node, SyncJob
    from services.sync_job_execution import salva_identita_replica

    src = Node(name="px-01", hostname="px-01", ssh_port=22, ssh_user="root")
    dst = Node(name="px-04", hostname="px-04", ssh_port=22, ssh_user="root")
    db.add_all([src, dst])
    db.flush()
    comuni = dict(
        source_node_id=src.id, dest_node_id=dst.id, source_dataset="rpool/data",
        dest_dataset="ZFS/replica", register_vm=True, vm_id=101, dest_vm_id=9101,
        vm_group_id="grp-101",
    )
    j1 = SyncJob(name="VM 101 scsi0", disk_name="scsi0", **comuni)
    j2 = SyncJob(name="VM 101 scsi1", disk_name="scsi1", **comuni)
    altro = SyncJob(name="VM 102", vm_id=102, vm_group_id="grp-102", **{
        k: v for k, v in comuni.items() if k not in ("vm_id", "dest_vm_id", "vm_group_id")
    })
    db.add_all([j1, j2, altro])
    db.commit()

    salva_identita_replica(db, j1, CONFIG_QEMU, "px-01", 9101)
    db.commit()

    for j in (j1, j2):
        db.refresh(j)
        assert j.source_smbios_uuid == UUID_SORGENTE
        assert j.source_vmgenid == VMGENID_SORGENTE
        assert j.replica_smbios_uuid == uuid_replica(UUID_SORGENTE)
    db.refresh(altro)
    assert altro.source_smbios_uuid is None


def test_migrazione_aggiunge_le_colonne_identita(tmp_path, monkeypatch):
    """Un DB nato prima della 3.22.0 non ha le tre colonne: update_schema le aggiunge."""
    import sqlite3
    import update_db_schema

    percorso = tmp_path / "dapx.db"
    con = sqlite3.connect(percorso)
    con.execute(
        "CREATE TABLE sync_jobs (id INTEGER PRIMARY KEY, name VARCHAR(200), "
        "schedule VARCHAR(100), source_node_id INTEGER, dest_node_id INTEGER)"
    )
    con.commit()
    con.close()

    monkeypatch.setattr(update_db_schema, "DATABASE_PATH", str(percorso))
    update_db_schema.update_schema()

    con = sqlite3.connect(percorso)
    colonne = {r[1] for r in con.execute("PRAGMA table_info(sync_jobs)")}
    con.close()
    assert {"source_smbios_uuid", "source_vmgenid", "replica_smbios_uuid"} <= colonne
