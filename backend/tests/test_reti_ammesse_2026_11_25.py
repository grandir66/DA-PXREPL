"""Filtro delle reti ammesse e indirizzo di ascolto.

Incidente del 25/11/2026: l'app, in ascolto su 0.0.0.0, rispondeva anche
sull'IP pubblico di un Proxmox su OVH.
"""

import asyncio

from services import dapx_systemd
from services.reti_ammesse import FiltroReti, ammesso, leggi_reti


def test_default_solo_reti_private():
    reti = leggi_reti("")
    assert ammesso("192.168.40.4", reti)
    assert ammesso("10.1.2.3", reti)
    assert ammesso("172.16.1.141", reti)
    assert ammesso("100.92.0.5", reti)
    assert ammesso("127.0.0.1", reti)
    assert ammesso("::1", reti)
    assert ammesso("::ffff:192.168.1.1", reti)
    assert not ammesso("51.68.10.20", reti)
    assert not ammesso("8.8.8.8", reti)
    assert not ammesso("2001:41d0::1", reti)


def test_elenco_esplicito_e_loopback_sempre():
    reti = leggi_reti("203.0.113.7, 192.168.4.0/24")
    assert ammesso("203.0.113.7", reti)
    assert ammesso("192.168.4.19", reti)
    assert ammesso("127.0.0.1", reti)
    assert not ammesso("192.168.40.4", reti)


def test_asterisco_apre_tutto():
    assert leggi_reti("*") is None
    assert ammesso("8.8.8.8", None)


def test_fallisce_chiuso():
    reti = leggi_reti("non-una-rete")
    assert not ammesso("8.8.8.8", reti)       # voci tutte sbagliate: sole private
    assert ammesso("10.0.0.1", reti)
    assert not ammesso(None, reti)
    assert not ammesso("testclient", reti)


def _chiama(filtro, host):
    inviati = []
    passato = []

    async def app(scope, receive, send):
        passato.append(True)

    async def send(msg):
        inviati.append(msg)

    async def receive():
        return {"type": "http.request"}

    f = FiltroReti(app, reti=leggi_reti(filtro), leggi_env=False)
    asyncio.run(f({"type": "http", "client": (host, 1234)}, receive, send))
    return passato, inviati


def test_middleware_rifiuta_prima_delle_rotte():
    passato, inviati = _chiama("", "51.68.10.20")
    assert not passato
    assert inviati[0]["status"] == 403

    passato, inviati = _chiama("", "192.168.4.10")
    assert passato and not inviati


def test_exec_start_rispetta_dapx_host(tmp_path, monkeypatch):
    monkeypatch.setattr(dapx_systemd, "install_dir", lambda: tmp_path)
    monkeypatch.setattr(dapx_systemd, "ENV_FILE", tmp_path / "manca.env")
    cfg = {"port": 8420, "ssl_enabled": False}

    monkeypatch.delenv("DAPX_HOST", raising=False)
    assert "--host 0.0.0.0 " in dapx_systemd.build_exec_start(cfg)

    monkeypatch.setenv("DAPX_HOST", "192.168.40.5")
    assert "--host 192.168.40.5 " in dapx_systemd.build_exec_start(cfg)

    monkeypatch.setenv("DAPX_HOST", "x; rm -rf /")
    assert "--host 0.0.0.0 " in dapx_systemd.build_exec_start(cfg)

    monkeypatch.delenv("DAPX_HOST")
    env = tmp_path / "dapx-unified.env"
    env.write_text('# commento\nDAPX_HOST="127.0.0.1"\n', encoding="utf-8")
    monkeypatch.setattr(dapx_systemd, "ENV_FILE", env)
    assert "--host 127.0.0.1 " in dapx_systemd.build_exec_start(cfg)
