"""Test client Synology session handling."""

from services.file_replication.synology_client import (
    _SESSION_RETRY_CODES,
    _session_key,
    _synology_error_message,
)


def test_session_key():
    assert _session_key("172.16.1.120", 5001, "qnap") == "172.16.1.120:5001:qnap"


def test_synology_error_message_119():
    msg = _synology_error_message(119)
    assert "non valida" in msg or "119" in msg
    assert 119 in _SESSION_RETRY_CODES
