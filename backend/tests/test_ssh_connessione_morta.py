"""SSH: una connessione morta non tiene appeso un comando per sempre (3.24.0).

Il 21/09/2026 su dts-repl `recv_exit_status()` — che non ha timeout — e'
rimasto appeso su una connessione mezza morta (nodo spento col tasto durante
una tempesta L2) e con lui lo scheduler intero, per nove ore. Ora: keepalive
paramiko + TCP sul socket appena connesso, e l'attesa dell'esito controlla a
passi che il trasporto sia vivo. Un comando lungo e vivo non viene toccato.
"""

import socket
import threading
from unittest.mock import MagicMock, patch

import pytest

from services.ssh_service import SSHService


def test_connect_arma_keepalive_paramiko_e_tcp():
    svc = SSHService()
    transport = MagicMock(); transport.is_active.return_value = True
    sock = MagicMock(); transport.sock = sock
    client = MagicMock(); client.get_transport.return_value = transport

    with patch("services.ssh_service.paramiko.SSHClient", return_value=client), \
         patch("services.ssh_service.os.path.exists", return_value=False):
        svc._get_client("px-01", 22, "root", "/k")

    transport.set_keepalive.assert_called_once_with(svc.KEEPALIVE_S)
    opzioni = {(c.args[0], c.args[1]): c.args[2] for c in sock.setsockopt.call_args_list}
    assert opzioni[(socket.SOL_SOCKET, socket.SO_KEEPALIVE)] == 1
    if hasattr(socket, "TCP_USER_TIMEOUT"):
        assert opzioni[(socket.IPPROTO_TCP, socket.TCP_USER_TIMEOUT)] == svc.TCP_USER_TIMEOUT_MS
    assert client.connect.call_args.kwargs["auth_timeout"] == 30


def test_attendi_esito_alza_se_il_trasporto_muore():
    svc = SSHService()
    svc.ATTESA_ESITO_PASSO_S = 0.01
    channel = MagicMock()
    channel.status_event.wait.return_value = False          # l'esito non arriva mai
    transport = MagicMock(); transport.is_active.return_value = False
    channel.get_transport.return_value = transport
    with pytest.raises(ConnectionError):
        svc._attendi_esito(channel, "px-01")
    channel.recv_exit_status.assert_not_called()


def test_attendi_esito_aspetta_un_comando_lungo_ma_vivo():
    svc = SSHService()
    svc.ATTESA_ESITO_PASSO_S = 0.01
    channel = MagicMock()
    channel.status_event.wait.side_effect = [False, False, False, True]  # tre passi, poi l'esito
    transport = MagicMock(); transport.is_active.return_value = True
    channel.get_transport.return_value = transport
    channel.recv_exit_status.return_value = 0
    assert svc._attendi_esito(channel, "px-01") == 0
    assert channel.status_event.wait.call_count == 4


@pytest.mark.asyncio
async def test_execute_torna_con_errore_di_trasporto_invece_di_appendersi():
    svc = SSHService()
    svc.ATTESA_ESITO_PASSO_S = 0.01
    channel = MagicMock()
    channel.status_event.wait.return_value = False
    transport = MagicMock(); transport.is_active.return_value = False
    channel.get_transport.return_value = transport
    stdout = MagicMock(); stdout.channel = channel
    client = MagicMock(); client.exec_command.return_value = (MagicMock(), stdout, MagicMock())
    with patch.object(svc, "_get_client", return_value=client):
        esito = await svc.execute("px-01", "zfs list", key_path="/k", timeout=5)
    assert esito.success is False and esito.exit_code == -1
    assert "caduta" in esito.stderr
