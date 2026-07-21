"""Test configurazione e invio notifiche email."""

import os

from database import NotificationConfig
from services.email_service import email_service
from services.notification_service import notification_service
from services.secrets import encrypt_secret


def test_configure_email_service_decrypts_password():
    os.environ["DAPX_SECRET_KEY"] = "test-secret-key-for-testing-only"
    cfg = NotificationConfig(
        smtp_enabled=True,
        smtp_host="mail.example.com",
        smtp_port=25,
        smtp_user="utente",
        smtp_password=encrypt_secret("pw-vera"),
        smtp_from="a@example.com",
        smtp_to="dest@example.com",
        smtp_tls=False,
    )
    notification_service._configure_email_service(cfg)
    assert email_service.password == "pw-vera"


def test_configure_email_service_bad_token_no_crash():
    os.environ["DAPX_SECRET_KEY"] = "test-secret-key-for-testing-only"
    cfg = NotificationConfig(
        smtp_enabled=True,
        smtp_host="mail.example.com",
        smtp_port=25,
        smtp_user="utente",
        smtp_password="token-non-valido",
        smtp_from="a@example.com",
        smtp_to="dest@example.com",
        smtp_tls=False,
    )
    notification_service._configure_email_service(cfg)  # non deve sollevare
    assert email_service.password is None
