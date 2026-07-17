"""Test messaggi errore connessione endpoint."""

import httpx

from services.file_replication.connection_errors import format_connection_error


def test_connect_timeout_message():
    exc = httpx.ConnectTimeout("timed out")
    msg = format_connection_error("172.16.1.120", 5001, exc)
    assert "172.16.1.120:5001" in msg
    assert "dapx" in msg


def test_connect_error_message():
    exc = httpx.ConnectError("refused")
    msg = format_connection_error("10.0.0.1", 22, exc)
    assert "10.0.0.1:22" in msg
    assert "non raggiungibile" in msg
