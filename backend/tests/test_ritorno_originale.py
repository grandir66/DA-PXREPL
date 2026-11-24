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


def test_fotografia_letta_dal_nodo_anche_a_vm_gia_registrata(db, nodi):
    """Prova a Domarc del 24/11/2026: agganciata alla registrazione, la
    fotografia restava quella della prima corsa. Ora e' un passo a se'."""
    from services.sync_job_execution import fotografa_originale

    a = _job(db, nodi)
    conf = {"testo": CONF_103}

    async def execute(hostname, command, **kw):
        assert hostname == "px-up.dts" and "qemu-server/103.conf" in command
        return SSHResult(success=True, stdout=conf["testo"], stderr="", exit_code=0)

    with patch("services.ssh_service.ssh_service.execute", AsyncMock(side_effect=execute)):
        assert asyncio.run(fotografa_originale(db, a, nodi[0])) is True
        conf["testo"] = CONF_103.replace("vmbr_vm", "vmbr_nuovo")
        assert asyncio.run(fotografa_originale(db, a, nodi[0])) is True
    assert "bridge=vmbr_nuovo" in a.source_config_snapshot


def test_corsa_riuscita_chiama_la_fotografia():
    import inspect
    from services import sync_job_execution

    corpo = inspect.getsource(sync_job_execution.execute_sync_job_task)
    assert "await fotografa_originale(db_session, job_record, source_node)" in corpo


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


# ───────────────────────── Task 3: passi SSH e rotte ─────────────────────────


class Mondo:
    """Due nodi finti: stato delle VM, dataset, file di conf, comandi ricevuti."""

    def __init__(self):
        self.vm = {("px-up.dts", 103): "stopped", ("px-04.dts", 9103): "running"}
        self.dataset = {"px-up.dts": {"ZFS/vm-103-disk-0"}, "px-04.dts": {"ZFS/replica/vm-103-disk-0"}}
        self.conf = {("px-up.dts", 103): CONF_103, ("px-04.dts", 9103): CONF_9103}
        self.comandi = []
        self.sync = []
        self.replica_si_spegne = True
        self.originale_risponde = True
        self.sync_riesce = True

    def _ok(self, out=""):
        return SSHResult(success=True, stdout=out, stderr="", exit_code=0)

    def _no(self, err, code=1):
        return SSHResult(success=False, stdout=err, stderr=err, exit_code=code)

    async def execute(self, hostname, command, **kw):
        self.comandi.append((hostname, command))
        m = re.match(r"qm (status|shutdown|start|stop) (\d+)", command)
        if m:
            azione, vmid = m.group(1), int(m.group(2))
            chiave = (hostname, vmid)
            if chiave not in self.conf:
                return self._no(f"Configuration file 'nodes/x/qemu-server/{vmid}.conf' does not exist", 2)
            if azione == "status":
                return self._ok(f"status: {self.vm.get(chiave, 'stopped')}\n")
            if azione == "shutdown":
                if vmid == 9103 and not self.replica_si_spegne:
                    return self._no("VM quit/powerdown failed - got timeout", 255)
                self.vm[chiave] = "stopped"
            elif azione == "start":
                self.vm[chiave] = "running"
            elif azione == "stop":
                self.vm[chiave] = "stopped"
            return self._ok()
        m = re.match(r"qm agent (\d+) ping", command)
        if m:
            return self._ok() if self.originale_risponde else self._no("QEMU guest agent is not running", 255)
        if command.startswith("qm set"):
            return self._ok("update VM")
        m = re.match(r"zfs list -H -o name (\S+)", command)
        if m:
            ds = m.group(1).strip("'")
            if ds in self.dataset[hostname]:
                return self._ok(ds + "\n")
            return self._no(f"cannot open '{ds}': dataset does not exist")
        m = re.match(r"zfs rename (\S+) (\S+)", command)
        if m:
            a, b = m.group(1).strip("'"), m.group(2).strip("'")
            self.dataset[hostname].discard(a)
            self.dataset[hostname].add(b)
            return self._ok()
        m = re.match(r"cat /etc/pve/qemu-server/(\d+)\.conf", command)
        if m:
            chiave = (hostname, int(m.group(1)))
            if chiave in self.conf:
                return self._ok(self.conf[chiave])
            return self._no("cat: No such file or directory")
        m = re.search(r"cat > /etc/pve/qemu-server/(\d+)\.conf << 'DAPX_RITORNO_EOF'\n(.*)\nDAPX_RITORNO_EOF", command, re.S)
        if m:
            self.conf[(hostname, int(m.group(1)))] = m.group(2) + "\n"
            return self._ok()
        return self._no(f"comando inatteso: {command}")

    async def run_sync(self, **kw):
        self.sync.append(kw)
        if not self.sync_riesce:
            return {"success": False, "error": "cannot receive: out of space", "output": "", "duration": 1, "transferred": None}
        if kw.get("dest_host"):
            self.dataset[kw["dest_host"]].add(kw["dest_dataset"])
        return {"success": True, "error": "", "output": "", "duration": 1, "transferred": "1.0G"}

    def cmd(self, pezzo):
        return [(h, c) for h, c in self.comandi if pezzo in c]


@pytest.fixture
def mondo():
    m = Mondo()
    with patch("services.ritorno_originale.ssh_service.execute", AsyncMock(side_effect=m.execute)), \
         patch("services.ritorno_originale.syncoid_service.run_sync", AsyncMock(side_effect=m.run_sync)), \
         patch("services.ritorno_originale._dormi", AsyncMock()):
        yield m


@pytest.fixture
def fabbrica(db):
    from sqlalchemy.orm import sessionmaker
    return sessionmaker(autocommit=False, autoflush=False, bind=db.get_bind())


def _prepara(job, fabbrica):
    from services import ritorno_originale as ro
    asyncio.run(ro.prepara([job.id], None, "riccardo", session_factory=fabbrica))


def _completa(job, fabbrica, attesa=60):
    from services import ritorno_originale as ro
    asyncio.run(ro.completa([job.id], None, "riccardo", attesa_avvio_s=attesa, session_factory=fabbrica))


def test_prepara_mette_da_parte_il_disco_e_copia_al_contrario(db, nodi, mondo, fabbrica):
    j = _job(db, nodi, source_config_snapshot=CONF_103)
    _prepara(j, fabbrica)
    db.refresh(j)
    assert j.ritorno_stato == "pronto", j.ritorno_dettaglio
    assert j.is_active is False  # una corsa normale riporterebbe indietro la replica
    rinomine = mondo.cmd("zfs rename")
    assert len(rinomine) == 1 and rinomine[0][0] == "px-up.dts"
    assert re.search(r"zfs rename ZFS/vm-103-disk-0 ZFS/dapx-vecchio-103-disk-0-\d{8}-\d{4}$", rinomine[0][1])
    s = mondo.sync[0]
    assert s["executor_host"] == "px-04.dts" and s["source_dataset"] == "ZFS/replica/vm-103-disk-0"
    assert s["dest_host"] == "px-up.dts" and s["dest_dataset"] == "ZFS/vm-103-disk-0"
    assert s["force_delete"] is False and s["no_sync_snap"] is False
    # la replica non e' stata toccata
    assert not mondo.cmd("qm shutdown") and not mondo.cmd("qm start") and mondo.vm[("px-04.dts", 9103)] == "running"
    assert db.query(JobLog).filter(JobLog.job_type == "ritorno_prepara").one().status == "success"

    # ripetibile: la seconda volta solo l'incrementale, il disco nuovo NON si rinomina
    _prepara(j, fabbrica)
    db.refresh(j)
    assert j.ritorno_stato == "pronto"
    assert len(mondo.cmd("zfs rename")) == 1 and len(mondo.sync) == 2


def test_prepara_si_rifiuta_se_l_originale_e_accesa(db, nodi, mondo, fabbrica):
    j = _job(db, nodi)
    mondo.vm[("px-up.dts", 103)] = "running"
    _prepara(j, fabbrica)
    db.refresh(j)
    assert j.ritorno_stato == "fallito" and "accesa" in j.ritorno_dettaglio
    assert not mondo.cmd("zfs rename") and not mondo.sync


def test_prepara_riparte_dopo_un_fallimento_a_meta(db, nodi, mondo, fabbrica):
    """Disco gia' messo da parte, syncoid fallito: al secondo giro non si rinomina di nuovo."""
    j = _job(db, nodi)
    mondo.sync_riesce = False
    _prepara(j, fabbrica)
    db.refresh(j)
    assert j.ritorno_stato == "fallito"
    mondo.sync_riesce = True
    _prepara(j, fabbrica)
    db.refresh(j)
    assert j.ritorno_stato == "pronto"
    assert len(mondo.cmd("zfs rename")) == 1


def test_completa_senza_pronto_non_fa_niente(db, nodi, mondo, fabbrica):
    j = _job(db, nodi)
    _completa(j, fabbrica)
    db.refresh(j)
    assert j.ritorno_stato in (None, "nessuno")
    assert mondo.comandi == [] and mondo.sync == []


def test_completa_riuscita_rimette_i_valori_dell_originale(db, nodi, mondo, fabbrica):
    j = _job(db, nodi, source_config_snapshot=CONF_103)
    _prepara(j, fabbrica)
    _completa(j, fabbrica)
    db.refresh(j)
    assert j.ritorno_stato == "completato", j.ritorno_dettaglio
    assert j.is_active is True
    testi = [c for _, c in mondo.comandi]
    i_spegni = next(i for i, c in enumerate(testi) if c.startswith("qm shutdown 9103"))
    i_scrivi = next(i for i, c in enumerate(testi) if "cat > /etc/pve/qemu-server/103.conf" in c)
    i_accendi = next(i for i, c in enumerate(testi) if c.startswith("qm start 103"))
    assert i_spegni < i_scrivi < i_accendi
    assert "dapx-bak-" in testi[i_scrivi]  # copia della conf di prima
    conf = mondo.conf[("px-up.dts", 103)]
    assert "bridge=vmbr_vm,tag=20" in conf and "vmbr1" not in conf
    assert "name: 3CX-V20\n" in conf and "onboot: 1" in conf and f"uuid={UUID_ORIG}" in conf
    assert mondo.vm[("px-up.dts", 103)] == "running" and mondo.vm[("px-04.dts", 9103)] == "stopped"
    # la replica torna replica: uuid derivato, onboot 0, segno nella description
    qm_set = mondo.cmd("qm set 9103")
    assert len(qm_set) == 1 and "--onboot 0" in qm_set[0][1] and "dapx-replica" in qm_set[0][1]
    assert UUID_ORIG not in qm_set[0][1].split("--description")[0]
    assert len(mondo.sync) == 2  # prepara + incrementale finale
    assert db.query(JobLog).filter(JobLog.job_type == "ritorno_completa").one().status == "success"


def test_completa_replica_non_spenta_non_accende_l_originale(db, nodi, mondo, fabbrica):
    j = _job(db, nodi, source_config_snapshot=CONF_103)
    _prepara(j, fabbrica)
    mondo.replica_si_spegne = False
    _completa(j, fabbrica)
    db.refresh(j)
    assert j.ritorno_stato == "fallito"
    assert not mondo.cmd("qm start 103")
    assert not mondo.cmd("cat > /etc/pve/qemu-server/103.conf")
    assert len(mondo.sync) == 1  # nessun syncoid finale
    assert mondo.vm[("px-04.dts", 9103)] == "running"


def test_completa_avvio_fallito_riaccende_la_replica(db, nodi, mondo, fabbrica):
    j = _job(db, nodi, source_config_snapshot=CONF_103)
    _prepara(j, fabbrica)
    mondo.originale_risponde = False
    _completa(j, fabbrica)
    db.refresh(j)
    assert j.ritorno_stato == "fallito" and "non ha risposto" in j.ritorno_dettaglio
    testi = [c for _, c in mondo.comandi]
    i_stop = next(i for i, c in enumerate(testi) if c.startswith("qm stop 103"))
    i_riaccendi = next(i for i, c in enumerate(testi) if c.startswith("qm start 9103"))
    assert i_stop < i_riaccendi
    assert mondo.vm[("px-up.dts", 103)] == "stopped" and mondo.vm[("px-04.dts", 9103)] == "running"
    assert j.is_active is False
    assert not mondo.cmd("qm set 9103")  # la replica resta com'era
    assert db.query(JobLog).filter(JobLog.job_type == "ritorno_completa").one().status == "failed"


def test_completa_syncoid_finale_fallito_riaccende_la_replica(db, nodi, mondo, fabbrica):
    j = _job(db, nodi, source_config_snapshot=CONF_103)
    _prepara(j, fabbrica)
    mondo.sync_riesce = False
    _completa(j, fabbrica)
    db.refresh(j)
    assert j.ritorno_stato == "fallito"
    assert not mondo.cmd("qm start 103")
    assert mondo.vm[("px-04.dts", 9103)] == "running"


def test_originale_sparita_si_ricrea_dalla_fotografia(db, nodi, mondo, fabbrica):
    j = _job(db, nodi, source_config_snapshot=CONF_103)
    del mondo.conf[("px-up.dts", 103)]
    del mondo.vm[("px-up.dts", 103)]
    mondo.dataset["px-up.dts"].clear()
    _prepara(j, fabbrica)
    assert not mondo.cmd("zfs rename")
    _completa(j, fabbrica)
    db.refresh(j)
    assert j.ritorno_stato == "completato", j.ritorno_dettaglio
    assert "bridge=vmbr_vm" in mondo.conf[("px-up.dts", 103)]


def test_due_dischi_tutti_copiati_prima_di_accendere(db, nodi, mondo, fabbrica):
    a = _job(db, nodi, "scsi0", 0, source_config_snapshot=CONF_103)
    _job(db, nodi, "scsi1", 1, source_config_snapshot=CONF_103)
    mondo.dataset["px-04.dts"].add("ZFS/replica/vm-103-disk-1")
    _prepara(a, fabbrica)
    _completa(a, fabbrica)
    db.refresh(a)
    assert a.ritorno_stato == "completato", a.ritorno_dettaglio
    assert len(mondo.sync) == 4
    assert "scsi1: ZFS:vm-103-disk-1" in mondo.conf[("px-up.dts", 103)]


def test_nessun_comando_distrugge(db, nodi, mondo, fabbrica):
    j = _job(db, nodi, source_config_snapshot=CONF_103)
    _prepara(j, fabbrica)
    mondo.originale_risponde = False
    _completa(j, fabbrica)
    _prepara(j, fabbrica)
    mondo.originale_risponde = True
    _completa(j, fabbrica)
    db.refresh(j)
    assert j.ritorno_stato == "completato"
    assert mondo.comandi and not any("destroy" in c for _, c in mondo.comandi)
    assert all(s["force_delete"] is False for s in mondo.sync)


def _url(dst, coda=""):
    return f"/api/vms/node/{dst.id}/vm/9103/ritorno{coda}"


def test_rotta_stato_da_piano_e_stato(client, operator_token, db, nodi, mondo):
    _job(db, nodi, source_config_snapshot=CONF_103)
    r = client.get(_url(nodi[1]), headers={"Authorization": f"Bearer {operator_token}"})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["stato"] == "nessuno" and b["piano"]["possibile"] is True
    assert b["piano"]["dischi"][0]["rinomina"] is True
    assert b["originale"]["vmid"] == 103 and b["originale"]["stato"] == "stopped"
    assert b["replica"]["stato"] == "running" and b["fotografia"]["presente"] is True


def test_rotte_rifiutano_senza_conferma_e_senza_pronto(client, operator_token, viewer_token, db, nodi, mondo):
    _job(db, nodi)
    h = {"Authorization": f"Bearer {operator_token}"}
    avviati = []

    def finto_task(coro):
        avviati.append(coro)
        coro.close()

    with patch("routers.vms.asyncio.create_task", finto_task):
        assert client.post(_url(nodi[1], "/prepara"), json={"confirm": "si"}, headers=h).status_code == 400
        assert client.post(_url(nodi[1], "/completa"), json={"confirm": "RITORNA"}, headers=h).status_code == 409
        assert client.post(_url(nodi[1], "/prepara"), json={"confirm": "RITORNA"},
                           headers={"Authorization": f"Bearer {viewer_token}"}).status_code == 403
        assert avviati == []
        r = client.post(_url(nodi[1], "/prepara"), json={"confirm": "RITORNA"}, headers=h)
        assert r.status_code == 200, r.text
        assert len(avviati) == 1
    assert not mondo.cmd("zfs rename")


def test_rotta_prepara_rifiuta_se_il_piano_e_impossibile(client, operator_token, db, nodi, mondo):
    _job(db, nodi)
    mondo.vm[("px-up.dts", 103)] = "running"
    with patch("routers.vms.asyncio.create_task") as ct:
        r = client.post(_url(nodi[1], "/prepara"), json={"confirm": "RITORNA"},
                        headers={"Authorization": f"Bearer {operator_token}"})
    assert r.status_code == 409 and "accesa" in r.json()["detail"]
    ct.assert_not_called()
