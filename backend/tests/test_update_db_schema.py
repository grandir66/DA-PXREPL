"""Test migrazioni leggere di update_db_schema."""

import os

from sqlalchemy import create_engine, text

from services.secrets import decrypt_secret, encrypt_secret
from update_db_schema import _migrate_smtp_password


def _make_conn(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    conn = engine.connect()
    conn.execute(text(
        "CREATE TABLE notification_config (id INTEGER PRIMARY KEY, smtp_password VARCHAR(255))"
    ))
    return conn


def test_plaintext_password_gets_encrypted(tmp_path):
    os.environ["DAPX_SECRET_KEY"] = "test-secret-key-for-testing-only"
    conn = _make_conn(tmp_path)
    conn.execute(text("INSERT INTO notification_config (id, smtp_password) VALUES (1, 'chiara')"))
    _migrate_smtp_password(conn)
    stored = conn.execute(text("SELECT smtp_password FROM notification_config")).scalar()
    assert stored != "chiara"
    assert decrypt_secret(stored) == "chiara"


def test_encrypted_password_unchanged(tmp_path):
    os.environ["DAPX_SECRET_KEY"] = "test-secret-key-for-testing-only"
    conn = _make_conn(tmp_path)
    token = encrypt_secret("gia-cifrata")
    conn.execute(
        text("INSERT INTO notification_config (id, smtp_password) VALUES (1, :pw)"),
        {"pw": token},
    )
    _migrate_smtp_password(conn)
    stored = conn.execute(text("SELECT smtp_password FROM notification_config")).scalar()
    assert stored == token


def test_empty_password_noop(tmp_path):
    conn = _make_conn(tmp_path)
    conn.execute(text("INSERT INTO notification_config (id, smtp_password) VALUES (1, NULL)"))
    _migrate_smtp_password(conn)
    stored = conn.execute(text("SELECT smtp_password FROM notification_config")).scalar()
    assert stored is None


def test_missing_table_noop(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/vuoto.db")
    conn = engine.connect()
    _migrate_smtp_password(conn)  # non deve sollevare
