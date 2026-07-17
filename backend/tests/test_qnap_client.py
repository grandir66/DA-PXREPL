"""Test client QNAP auth encoding."""

import base64

from services.file_replication.qnap_client import _auth_failure_message, _encode_qnap_password, _parse_auth_response


def test_encode_qnap_password_base64():
    assert _encode_qnap_password("admin") == base64.b64encode(b"admin").decode("ascii")


def test_auth_failure_message_wrong_credentials():
    root = _parse_auth_response(
        """<?xml version="1.0"?><QDocRoot><authPassed>0</authPassed><errorValue>-1</errorValue></QDocRoot>"""
    )
    msg = _auth_failure_message(root)
    assert "username o password errati" in msg


def test_auth_failure_message_2fa():
    root = _parse_auth_response(
        """<?xml version="1.0"?><QDocRoot><authPassed>0</authPassed><need_2sv>1</need_2sv><errorValue>-1</errorValue></QDocRoot>"""
    )
    msg = _auth_failure_message(root)
    assert "2 passaggi" in msg
