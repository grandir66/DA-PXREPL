"""Controllo periodico «UUID SMBIOS duplicati» (spec §2.3).

Tre config finte, due con lo stesso uuid → un alert con la coppia giusta;
uuid tutti diversi → nessun alert. Il testo dell'alert nomina le VM.
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from database import Node, SystemConfig
from services.ssh_service import SSHResult
from services.uuid_duplicati import (
    COMANDO_SMBIOS,
    chiavi_duplicati,
    descrivi_duplicati,
    raccogli_smbios,
    trova_uuid_duplicati,
)

U1 = "6f5d9e1a-2b3c-4d5e-8f90-1a2b3c4d5e6f"
U2 = "11111111-2222-3333-4444-555555555555"
U3 = "22222222-3333-4444-5555-666666666666"

GREP_CON_DOPPIONE = f"""/etc/pve/nodes/px-01/qemu-server/101.conf:smbios1: uuid={U1}
/etc/pve/nodes/px-02/qemu-server/102.conf:smbios1: uuid={U2},base64=1
/etc/pve/nodes/px-04/qemu-server/9101.conf:smbios1: uuid={U1}
"""
GREP_SENZA = f"""/etc/pve/nodes/px-01/qemu-server/101.conf:smbios1: uuid={U1}
/etc/pve/nodes/px-02/qemu-server/102.conf:smbios1: uuid={U2}
/etc/pve/nodes/px-04/qemu-server/9101.conf:smbios1: uuid={U3}
"""


def _nodo(name, hostname):
    n = MagicMock()
    n.name, n.hostname, n.ssh_port, n.ssh_user, n.ssh_key_path = name, hostname, 22, "root", "/k"
    return n


@pytest.mark.asyncio
async def test_raccogli_smbios_fonde_le_risposte_dei_nodi_dello_stesso_cluster():
    """Ogni nodo risponde per tutto il cluster: le righe non si contano due volte,
    e un nodo muto non fa perdere quelle degli altri."""
    ssh = MagicMock()

    async def execute(hostname, command, **kw):
        assert command == COMANDO_SMBIOS
        if hostname == "px-03":
            return SSHResult(success=False, stdout="", stderr="timeout", exit_code=-1)
        return SSHResult(success=True, stdout=GREP_CON_DOPPIONE, stderr="", exit_code=0)

    ssh.execute = AsyncMock(side_effect=execute)
    righe, muti = await raccogli_smbios(ssh, [_nodo("px-01", "px-01"), _nodo("px-03", "px-03"), _nodo("px-04", "px-04")])
    assert muti == ["px-03"]
    assert righe == [("px-01", 101, U1), ("px-02", 102, U2), ("px-04", 9101, U1)]


def test_descrivi_duplicati_nomina_le_vm():
    dup = trova_uuid_duplicati([("px-01", 101, U1), ("px-04", 9101, U1)])
    testo = descrivi_duplicati(dup)
    assert f"uuid {U1}: VM 101 su px-01, VM 9101 su px-04" in testo
    assert "Veeam" in testo
    assert chiavi_duplicati(dup) == [U1]


def _scheduler_con_db(db):
    from services.scheduler import SchedulerService

    sched = SchedulerService()
    db.add_all([
        Node(name="px-01", hostname="px-01", node_type="pve", is_active=True),
        Node(name="px-04", hostname="px-04", node_type="pve", is_active=True),
        Node(name="pbs", hostname="pbs", node_type="pbs", is_active=True),
    ])
    db.commit()
    return sched


@pytest.mark.asyncio
async def test_check_uuid_duplicati_manda_un_alert_con_la_coppia(db):
    sched = _scheduler_con_db(db)
    comandi = []

    async def execute(hostname, command, **kw):
        comandi.append(hostname)
        return SSHResult(success=True, stdout=GREP_CON_DOPPIONE, stderr="", exit_code=0)

    invio = AsyncMock(return_value={"sent": True, "channels": {"smtp": True}})
    with patch("services.scheduler.SessionLocal", return_value=db), \
         patch("services.ssh_service.ssh_service.execute", AsyncMock(side_effect=execute)), \
         patch("services.scheduler.notification_service.send_uuid_duplicati_alert", invio):
        await sched._check_uuid_duplicati()

    assert sorted(comandi) == ["px-01", "px-04"]  # il PBS non si interroga
    invio.assert_awaited_once()
    duplicati = invio.await_args.args[0]
    assert duplicati == [{"uuid": U1, "vms": [("px-01", 101), ("px-04", 9101)]}]
    chiavi = db.query(SystemConfig).filter(SystemConfig.key == "uuid_duplicati_last_alert_keys").first()
    assert chiavi.value == U1


@pytest.mark.asyncio
async def test_check_uuid_duplicati_tace_se_tutti_diversi(db):
    sched = _scheduler_con_db(db)
    invio = AsyncMock(return_value={"sent": True, "channels": {}})
    with patch("services.scheduler.SessionLocal", return_value=db), \
         patch("services.ssh_service.ssh_service.execute",
               AsyncMock(return_value=SSHResult(success=True, stdout=GREP_SENZA, stderr="", exit_code=0))), \
         patch("services.scheduler.notification_service.send_uuid_duplicati_alert", invio):
        await sched._check_uuid_duplicati()
    invio.assert_not_awaited()


@pytest.mark.asyncio
async def test_check_uuid_duplicati_cooldown_stesse_coppie_e_coppia_nuova(db):
    sched = _scheduler_con_db(db)
    db.add(SystemConfig(key="uuid_duplicati_last_alert", value=(datetime.utcnow() - timedelta(hours=2)).isoformat()))
    db.add(SystemConfig(key="uuid_duplicati_last_alert_keys", value=U1))
    db.commit()
    invio = AsyncMock(return_value={"sent": True, "channels": {}})

    # stesse coppie di due ore fa: silenzio
    with patch("services.scheduler.SessionLocal", return_value=db), \
         patch("services.ssh_service.ssh_service.execute",
               AsyncMock(return_value=SSHResult(success=True, stdout=GREP_CON_DOPPIONE, stderr="", exit_code=0))), \
         patch("services.scheduler.notification_service.send_uuid_duplicati_alert", invio):
        await sched._check_uuid_duplicati()
    invio.assert_not_awaited()

    # una coppia NUOVA: si segnala subito, cooldown o no
    sched._last_uuid_dup_check = None
    nuova = GREP_CON_DOPPIONE + f"/etc/pve/nodes/px-04/qemu-server/9102.conf:smbios1: uuid={U2}\n"
    with patch("services.scheduler.SessionLocal", return_value=db), \
         patch("services.ssh_service.ssh_service.execute",
               AsyncMock(return_value=SSHResult(success=True, stdout=nuova, stderr="", exit_code=0))), \
         patch("services.scheduler.notification_service.send_uuid_duplicati_alert", invio):
        await sched._check_uuid_duplicati()
    invio.assert_awaited_once()
    assert [d["uuid"] for d in invio.await_args.args[0]] == sorted([U2, U1])


@pytest.mark.asyncio
async def test_check_uuid_duplicati_non_piu_di_una_volta_ogni_sei_ore(db):
    sched = _scheduler_con_db(db)
    sched._last_uuid_dup_check = datetime.utcnow() - timedelta(hours=1)
    ssh = AsyncMock()
    with patch("services.scheduler.SessionLocal", return_value=db), \
         patch("services.ssh_service.ssh_service.execute", ssh):
        await sched._check_uuid_duplicati()
    ssh.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_uuid_duplicati_alert_passa_dal_canale_warning():
    from services.notification_service import notification_service

    config = MagicMock(smtp_enabled=True, webhook_enabled=False, telegram_enabled=False, notify_on_warning=True)
    dup = [{"uuid": U1, "vms": [("px-01", 101), ("px-04", 9101)]}]
    with patch.object(notification_service, "_load_config", return_value=config), \
         patch.object(notification_service, "send_job_notification", AsyncMock(return_value={"sent": True})) as invio:
        esito = await notification_service.send_uuid_duplicati_alert(dup)
    assert esito == {"sent": True}
    kw = invio.await_args.kwargs
    assert kw["status"] == "warning"
    assert "VM 101 su px-01" in kw["details"]
    assert kw["job_name"].startswith("UUID SMBIOS duplicati")

    config.notify_on_warning = False
    with patch.object(notification_service, "_load_config", return_value=config):
        assert (await notification_service.send_uuid_duplicati_alert(dup))["sent"] is False
