# Default SMTP domarc + identificazione cliente — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ogni installazione DAPX esce con l'SMTP domarc precompilato (password cifrata nel DB, mai in git) e ogni email di notifica ha l'oggetto `CODCLI - NOMECLI — …`.

**Architecture:** Helper Fernet generico (`services/secrets.py`) per cifratura at-rest della password SMTP; seed dei default non-segreti in `init_default_config()`; password consegnata al deploy via env file e cifrata al primo avvio; campi cliente su `NotificationConfig` iniettati nell'oggetto a livello di `EmailService.send_email()`.

**Tech Stack:** FastAPI + SQLAlchemy 2.x + SQLite, `cryptography.fernet`, Vue 3 + Vite, bash (install.sh), pytest.

Spec di riferimento: `docs/superpowers/specs/2026-07-21-smtp-default-notifications-design.md`.

## Global Constraints

- **Repo GitHub PUBBLICO**: la password SMTP reale NON deve MAI comparire in file, commit, log o messaggi. Nei test usare solo valori fittizi (`pw-in-chiaro`, `s3cr3t!`, …). La password reale vive nel vault dell'operatore e arriva solo via env al deploy.
- Valori default (verbatim, non-segreti, committabili): host `esva.domarc.it`, porta `25`, utente `smtp.domarc`, dominio mittente `domarc.it`.
- Nome env var runtime: `DAPX_SMTP_DEFAULT_PASSWORD` (nel file `/etc/dapx-unified/dapx-unified.env`). Nome env/flag installer: `DAPX_SMTP_PASSWORD` / `--smtp-password`.
- Python del venv è **3.9**: niente sintassi 3.10+ (`match`, `X | Y` nei type hints).
- Comando test: `cd /Users/riccardo/Progetti/DA-PXREPL/dapx-unified/backend && ./venv/bin/python -m pytest tests/<file> -v`
- NON bumpare i 5 file di versione né fare release/push: si fa solo al rilascio, su richiesta dell'utente.
- Il seed non deve MAI sovrascrivere configurazioni esistenti (`smtp_host` o `smtp_password` già valorizzati).
- `smtp_enabled` resta `False` di default.
- Commit frequenti, messaggi in stile `feat(...)`/`fix(...)` come da storia del repo, footer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: Helper cifratura generico `services/secrets.py`

**Files:**
- Create: `backend/services/secrets.py`
- Modify: `backend/services/file_replication/endpoint_crypto.py` (diventa wrapper)
- Test: `backend/tests/test_secrets.py`

**Interfaces:**
- Consumes: env `DAPX_SECRET_KEY` (o `SANOID_MANAGER_SECRET_KEY`), già impostata da conftest.py nei test.
- Produces: `encrypt_secret(plain: str) -> str`, `decrypt_secret(token: str) -> str` (solleva `ValueError` su token invalido, `RuntimeError` se manca la chiave), `is_encrypted(value: str) -> bool`. I task 2, 3, 5 importano da `services.secrets`.

- [ ] **Step 1: Scrivere i test (falliscono: modulo inesistente)**

Creare `backend/tests/test_secrets.py`:

```python
"""Test cifratura segreti applicativi (services.secrets)."""

import os

import pytest

from services.file_replication.endpoint_crypto import decrypt_password, encrypt_password
from services.secrets import decrypt_secret, encrypt_secret, is_encrypted


def test_encrypt_decrypt_roundtrip():
    os.environ["DAPX_SECRET_KEY"] = "test-secret-key-for-testing-only"
    enc = encrypt_secret("s3cr3t!")
    assert enc != "s3cr3t!"
    assert decrypt_secret(enc) == "s3cr3t!"


def test_empty_values():
    assert encrypt_secret("") == ""
    assert decrypt_secret("") == ""
    assert is_encrypted("") is False


def test_decrypt_invalid_raises():
    os.environ["DAPX_SECRET_KEY"] = "test-secret-key-for-testing-only"
    with pytest.raises(ValueError):
        decrypt_secret("not-valid-token")


def test_is_encrypted():
    os.environ["DAPX_SECRET_KEY"] = "test-secret-key-for-testing-only"
    assert is_encrypted(encrypt_secret("x")) is True
    assert is_encrypted("password-in-chiaro") is False


def test_endpoint_crypto_compat():
    """I token di endpoint_crypto e secrets sono interscambiabili (stessa chiave/algoritmo)."""
    os.environ["DAPX_SECRET_KEY"] = "test-secret-key-for-testing-only"
    assert decrypt_secret(encrypt_password("abc")) == "abc"
    assert decrypt_password(encrypt_secret("abc")) == "abc"
```

- [ ] **Step 2: Verificare che falliscano**

Run: `cd /Users/riccardo/Progetti/DA-PXREPL/dapx-unified/backend && ./venv/bin/python -m pytest tests/test_secrets.py -v`
Expected: FAIL/ERROR con `ModuleNotFoundError: No module named 'services.secrets'`

- [ ] **Step 3: Creare `backend/services/secrets.py`**

```python
"""Cifratura simmetrica dei segreti applicativi.

Fernet con chiave derivata SHA-256 da DAPX_SECRET_KEY: identica alla logica
storica di services/file_replication/endpoint_crypto.py, di cui questo modulo
è la generalizzazione (i token esistenti restano decifrabili).
"""

import base64
import hashlib
import logging
import os

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


def _fernet() -> Fernet:
    secret = os.environ.get("DAPX_SECRET_KEY") or os.environ.get("SANOID_MANAGER_SECRET_KEY")
    if not secret:
        raise RuntimeError("DAPX_SECRET_KEY non configurata")
    digest = hashlib.sha256(secret.encode()).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_secret(plain: str) -> str:
    if not plain:
        return ""
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_secret(token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        logger.warning("decrypt_secret: token invalido")
        raise ValueError("segreto non decifrabile") from exc


def is_encrypted(value: str) -> bool:
    """True se value è un token Fernet decifrabile con la chiave corrente."""
    if not value:
        return False
    try:
        _fernet().decrypt(value.encode())
        return True
    except InvalidToken:
        return False
```

- [ ] **Step 4: Trasformare `endpoint_crypto.py` in wrapper**

Sostituire l'intero contenuto di `backend/services/file_replication/endpoint_crypto.py` con:

```python
"""Cifratura password endpoint replica file.

Wrapper di compatibilità: la logica vive in services.secrets (stessa chiave,
stesso algoritmo — i token già salvati restano validi).
"""

from services.secrets import decrypt_secret, encrypt_secret


def encrypt_password(plain: str) -> str:
    return encrypt_secret(plain)


def decrypt_password(token: str) -> str:
    try:
        return decrypt_secret(token)
    except ValueError as exc:
        raise ValueError("password endpoint non decifrabile") from exc
```

- [ ] **Step 5: Verificare che i test passino (nuovi + regressione)**

Run: `cd /Users/riccardo/Progetti/DA-PXREPL/dapx-unified/backend && ./venv/bin/python -m pytest tests/test_secrets.py tests/test_endpoint_crypto.py tests/test_file_replication_models.py -v`
Expected: PASS (tutti)

- [ ] **Step 6: Commit**

```bash
cd /Users/riccardo/Progetti/DA-PXREPL/dapx-unified
git add backend/services/secrets.py backend/services/file_replication/endpoint_crypto.py backend/tests/test_secrets.py
git commit -m "feat(secrets): helper generico cifratura Fernet, endpoint_crypto come wrapper

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Cifratura at-rest della password SMTP (PUT + uso)

**Files:**
- Modify: `backend/routers/settings.py` (PUT `/notifications` ~riga 343-367; endpoint test ~riga 389-409; import in testa)
- Modify: `backend/services/notification_service.py` (`_configure_email_service`, ~riga 54-66; import in testa)
- Test: `backend/tests/test_settings.py` (nuova classe), `backend/tests/test_email_notifications.py` (nuovo file)

**Interfaces:**
- Consumes: `encrypt_secret`/`decrypt_secret` dal Task 1; fixtures `client`, `admin_token`, `db` di conftest.py.
- Produces: `NotificationConfig.smtp_password` in DB è SEMPRE un token Fernet (o vuoto). Chiunque legga quel campo d'ora in poi deve decifrarlo con `decrypt_secret`.

- [ ] **Step 1: Scrivere i test API (falliscono)**

Aggiungere in coda a `backend/tests/test_settings.py`:

```python
class TestNotificationSmtpPassword:
    """La password SMTP deve essere cifrata at-rest nel DB."""

    def test_put_encrypts_password(self, client, admin_token, db):
        resp = client.put(
            "/api/settings/notifications",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"smtp_password": "pw-in-chiaro"},
        )
        assert resp.status_code == 200

        from database import NotificationConfig
        from services.secrets import decrypt_secret, is_encrypted

        db.expire_all()
        stored = db.query(NotificationConfig).first().smtp_password
        assert stored != "pw-in-chiaro"
        assert is_encrypted(stored)
        assert decrypt_secret(stored) == "pw-in-chiaro"

    def test_put_without_password_keeps_existing(self, client, admin_token, db):
        headers = {"Authorization": f"Bearer {admin_token}"}
        client.put("/api/settings/notifications", headers=headers, json={"smtp_password": "pw-1"})
        client.put("/api/settings/notifications", headers=headers, json={"smtp_host": "mail.example.com"})

        from database import NotificationConfig
        from services.secrets import decrypt_secret

        db.expire_all()
        cfg = db.query(NotificationConfig).first()
        assert decrypt_secret(cfg.smtp_password) == "pw-1"
        assert cfg.smtp_host == "mail.example.com"
```

E creare `backend/tests/test_email_notifications.py`:

```python
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
```

- [ ] **Step 2: Verificare che falliscano**

Run: `cd /Users/riccardo/Progetti/DA-PXREPL/dapx-unified/backend && ./venv/bin/python -m pytest tests/test_settings.py::TestNotificationSmtpPassword tests/test_email_notifications.py -v`
Expected: FAIL (`is_encrypted(stored)` è False; `email_service.password == "pw-vera"` fallisce perché arriva il token cifrato)

- [ ] **Step 3: Cifrare nel PUT (`backend/routers/settings.py`)**

In testa al file, insieme agli altri import: `from services.secrets import decrypt_secret, encrypt_secret`

Nel handler `update_notification_config`, sostituire:

```python
    for key, value in update.model_dump(exclude_unset=True).items():
        setattr(config, key, value)
```

con:

```python
    data = update.model_dump(exclude_unset=True)
    # La password SMTP va salvata SOLO cifrata (at-rest nel DB).
    if data.get("smtp_password"):
        data["smtp_password"] = encrypt_secret(data["smtp_password"])
    for key, value in data.items():
        setattr(config, key, value)
```

- [ ] **Step 4: Decifrare nell'endpoint di test (`backend/routers/settings.py`)**

Nel handler `test_notification`, ramo `channel == "email"`, sostituire il blocco `email_service.configure(...)` con:

```python
        smtp_password = None
        if config.smtp_password:
            try:
                smtp_password = decrypt_secret(config.smtp_password)
            except (ValueError, RuntimeError):
                raise HTTPException(
                    status_code=400,
                    detail="Password SMTP non decifrabile: reinserirla nelle impostazioni",
                )

        email_service.configure(
            host=config.smtp_host,
            port=config.smtp_port or 587,
            user=config.smtp_user,
            password=smtp_password,
            from_addr=config.smtp_from,
            to_addrs=config.smtp_to,
            subject_prefix=config.smtp_subject_prefix or "[DAPX]",
            use_tls=config.smtp_tls
        )
```

- [ ] **Step 5: Decifrare in `notification_service._configure_email_service`**

In testa a `backend/services/notification_service.py`, insieme agli altri import: `from services.secrets import decrypt_secret` (verificare che `logger = logging.getLogger(__name__)` esista già; se manca, aggiungerlo con `import logging`).

Sostituire il metodo `_configure_email_service` con:

```python
    def _configure_email_service(self, config: NotificationConfig):
        """Configura il servizio email con i dati dal database"""
        if config and config.smtp_enabled and config.smtp_host:
            password = None
            if config.smtp_password:
                try:
                    password = decrypt_secret(config.smtp_password)
                except (ValueError, RuntimeError):
                    logger.error(
                        "Password SMTP non decifrabile: reinserirla nelle impostazioni "
                        "o verificare DAPX_SECRET_KEY"
                    )
            email_service.configure(
                host=config.smtp_host,
                port=config.smtp_port or 587,
                user=config.smtp_user,
                password=password,
                from_addr=config.smtp_from,
                to_addrs=config.smtp_to,
                subject_prefix=config.smtp_subject_prefix or "[DAPX]",
                use_tls=config.smtp_tls if config.smtp_tls is not None else True
            )
```

- [ ] **Step 6: Verificare che i test passino**

Run: `cd /Users/riccardo/Progetti/DA-PXREPL/dapx-unified/backend && ./venv/bin/python -m pytest tests/test_settings.py tests/test_email_notifications.py -v`
Expected: PASS (tutti, inclusi i test preesistenti di test_settings.py)

- [ ] **Step 7: Commit**

```bash
cd /Users/riccardo/Progetti/DA-PXREPL/dapx-unified
git add backend/routers/settings.py backend/services/notification_service.py backend/tests/test_settings.py backend/tests/test_email_notifications.py
git commit -m "fix(notifications): password SMTP cifrata at-rest nel DB (era in chiaro)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Migrazione idempotente delle password in chiaro

**Files:**
- Modify: `backend/update_db_schema.py` (nuova funzione + chiamata in `update_schema()`)
- Test: `backend/tests/test_update_db_schema.py` (nuovo file)

**Interfaces:**
- Consumes: `encrypt_secret`, `is_encrypted` dal Task 1; `text` di SQLAlchemy già importato in update_db_schema.py.
- Produces: `_migrate_smtp_password(conn) -> None`, chiamata a ogni avvio/update: dopo di essa ogni `smtp_password` non vuota in DB è un token Fernet.

- [ ] **Step 1: Scrivere i test (falliscono)**

Creare `backend/tests/test_update_db_schema.py`:

```python
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
```

- [ ] **Step 2: Verificare che falliscano**

Run: `cd /Users/riccardo/Progetti/DA-PXREPL/dapx-unified/backend && ./venv/bin/python -m pytest tests/test_update_db_schema.py -v`
Expected: FAIL/ERROR con `ImportError: cannot import name '_migrate_smtp_password'`

- [ ] **Step 3: Implementare la migrazione in `backend/update_db_schema.py`**

Aggiungere dopo `_ensure_column` (a livello modulo):

```python
def _migrate_smtp_password(conn) -> None:
    """Cifra in-place le smtp_password salvate in chiaro (idempotente).

    Le versioni precedenti salvavano la password SMTP in chiaro nonostante
    il commento "# Encrypted" sul modello. Se DAPX_SECRET_KEY non è
    disponibile la migrazione viene saltata senza bloccare l'avvio.
    """
    try:
        from services.secrets import encrypt_secret, is_encrypted
    except Exception as e:
        logger.warning(f"services.secrets non importabile, migrazione smtp_password saltata: {e}")
        return
    try:
        rows = conn.execute(text("SELECT id, smtp_password FROM notification_config")).fetchall()
    except Exception:
        # Tabella inesistente: create_all la creerà al primo avvio.
        return
    for row_id, password in rows:
        if not password:
            continue
        try:
            if is_encrypted(password):
                continue
            encrypted = encrypt_secret(password)
        except RuntimeError as e:
            logger.warning(f"DAPX_SECRET_KEY assente, migrazione smtp_password saltata: {e}")
            return
        conn.execute(
            text("UPDATE notification_config SET smtp_password = :pw WHERE id = :id"),
            {"pw": encrypted, "id": row_id},
        )
        logger.info("notification_config.smtp_password cifrata (migrazione da chiaro)")
```

Poi, dentro `update_schema()`, nel blocco `try` dopo l'ultima chiamata `_ensure_column(...)` esistente (attualmente `_ensure_column(conn, "backup_jobs", "notify_on_each_run", "BOOLEAN")`), aggiungere:

```python
            # --- notification_config: cifratura password legacy ---
            _migrate_smtp_password(conn)
```

- [ ] **Step 4: Verificare che i test passino**

Run: `cd /Users/riccardo/Progetti/DA-PXREPL/dapx-unified/backend && ./venv/bin/python -m pytest tests/test_update_db_schema.py -v`
Expected: PASS (4 test)

- [ ] **Step 5: Commit**

```bash
cd /Users/riccardo/Progetti/DA-PXREPL/dapx-unified
git add backend/update_db_schema.py backend/tests/test_update_db_schema.py
git commit -m "feat(migrations): cifratura idempotente delle password SMTP salvate in chiaro

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Campi cliente `client_code`/`client_name` (modello + migrazione + API)

**Files:**
- Modify: `backend/database.py` (modello `NotificationConfig`, ~riga 267)
- Modify: `backend/update_db_schema.py` (due `_ensure_column`)
- Modify: `backend/routers/settings.py` (`NotificationConfigUpdate` ~riga 56, `NotificationConfigResponse` ~riga 90)
- Test: `backend/tests/test_settings.py`

**Interfaces:**
- Consumes: pattern `_ensure_column(conn, table, column, ddl_type)` esistente.
- Produces: colonne/campi `client_code: Optional[str]` (max 50) e `client_name: Optional[str]` (max 255) su modello DB e API `GET/PUT /api/settings/notifications`. Il Task 7 li legge da `config.client_code`/`config.client_name`.

- [ ] **Step 1: Scrivere il test API (fallisce)**

Aggiungere alla classe `TestNotificationSmtpPassword` di `backend/tests/test_settings.py` (o in una nuova classe `TestNotificationClientFields` nello stesso file):

```python
class TestNotificationClientFields:
    """Campi identificazione cliente per l'oggetto email."""

    def test_client_fields_roundtrip(self, client, admin_token):
        headers = {"Authorization": f"Bearer {admin_token}"}
        resp = client.put(
            "/api/settings/notifications",
            headers=headers,
            json={"client_code": "C0123", "client_name": "ACME Srl"},
        )
        assert resp.status_code == 200

        resp = client.get("/api/settings/notifications", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["client_code"] == "C0123"
        assert body["client_name"] == "ACME Srl"
        assert "smtp_password" not in body
```

- [ ] **Step 2: Verificare che fallisca**

Run: `cd /Users/riccardo/Progetti/DA-PXREPL/dapx-unified/backend && ./venv/bin/python -m pytest tests/test_settings.py::TestNotificationClientFields -v`
Expected: FAIL con `KeyError: 'client_code'` (o 500 per campo inesistente sul modello)

- [ ] **Step 3: Aggiungere le colonne al modello (`backend/database.py`)**

Nel modello `NotificationConfig`, subito dopo la riga `smtp_tls = Column(Boolean, default=True)`:

```python
    # Identificazione cliente (oggetto email: "CODCLI - NOMECLI — …")
    client_code = Column(String(50), nullable=True)
    client_name = Column(String(255), nullable=True)
```

- [ ] **Step 4: Aggiungere la migrazione colonne (`backend/update_db_schema.py`)**

Dentro `update_schema()`, subito PRIMA della riga `_migrate_smtp_password(conn)` aggiunta nel Task 3:

```python
            # --- notification_config: identificazione cliente ---
            _ensure_column(conn, "notification_config", "client_code", "VARCHAR(50)")
            _ensure_column(conn, "notification_config", "client_name", "VARCHAR(255)")
```

- [ ] **Step 5: Esporre i campi nelle API (`backend/routers/settings.py`)**

In `NotificationConfigUpdate`, dopo `smtp_tls: Optional[bool] = None`:

```python
    # Identificazione cliente (oggetto email)
    client_code: Optional[str] = None
    client_name: Optional[str] = None
```

In `NotificationConfigResponse`, dopo `smtp_tls: bool`:

```python
    client_code: Optional[str]
    client_name: Optional[str]
```

- [ ] **Step 6: Verificare che i test passino**

Run: `cd /Users/riccardo/Progetti/DA-PXREPL/dapx-unified/backend && ./venv/bin/python -m pytest tests/test_settings.py tests/test_update_db_schema.py -v`
Expected: PASS (tutti)

- [ ] **Step 7: Commit**

```bash
cd /Users/riccardo/Progetti/DA-PXREPL/dapx-unified
git add backend/database.py backend/update_db_schema.py backend/routers/settings.py backend/tests/test_settings.py
git commit -m "feat(notifications): campi client_code/client_name su NotificationConfig e API

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Seed dei default SMTP domarc al primo avvio

**Files:**
- Modify: `backend/database.py` (costanti a livello modulo + blocco NotificationConfig in `init_default_config()`, ~riga 1126-1128)
- Test: `backend/tests/test_init_default_smtp.py` (nuovo file)

**Interfaces:**
- Consumes: `encrypt_secret` dal Task 1; env `DAPX_SMTP_DEFAULT_PASSWORD` (scritta da install.sh, Task 9).
- Produces: costanti `DEFAULT_SMTP_HOST = "esva.domarc.it"`, `DEFAULT_SMTP_PORT = 25`, `DEFAULT_SMTP_USER = "smtp.domarc"` in `database.py`; dopo `init_default_config()` una config vergine ha i default domarc e (se env presente) la password cifrata.

- [ ] **Step 1: Scrivere i test (falliscono)**

Creare `backend/tests/test_init_default_smtp.py`:

```python
"""Test seed default SMTP domarc in init_default_config."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import database as db_mod
from services.secrets import decrypt_secret, encrypt_secret


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    db_mod.Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


def test_seed_defaults_on_fresh_db(session, monkeypatch):
    monkeypatch.delenv("DAPX_SMTP_DEFAULT_PASSWORD", raising=False)
    db_mod.init_default_config(session)
    notif = session.query(db_mod.NotificationConfig).first()
    assert notif.smtp_host == "esva.domarc.it"
    assert notif.smtp_port == 25
    assert notif.smtp_user == "smtp.domarc"
    assert notif.smtp_tls is True
    assert notif.smtp_enabled is False
    assert notif.smtp_password is None
    assert notif.smtp_to is None


def test_seed_does_not_overwrite_existing(session, monkeypatch):
    monkeypatch.delenv("DAPX_SMTP_DEFAULT_PASSWORD", raising=False)
    session.add(db_mod.NotificationConfig(smtp_host="mail.cliente.it", smtp_port=587))
    session.commit()
    db_mod.init_default_config(session)
    notif = session.query(db_mod.NotificationConfig).first()
    assert notif.smtp_host == "mail.cliente.it"
    assert notif.smtp_port == 587


def test_seed_password_from_env(session, monkeypatch):
    monkeypatch.setenv("DAPX_SMTP_DEFAULT_PASSWORD", "pw-da-env")
    db_mod.init_default_config(session)
    notif = session.query(db_mod.NotificationConfig).first()
    assert notif.smtp_password
    assert notif.smtp_password != "pw-da-env"
    assert decrypt_secret(notif.smtp_password) == "pw-da-env"


def test_seed_password_not_overwritten(session, monkeypatch):
    session.add(db_mod.NotificationConfig(smtp_password=encrypt_secret("esistente")))
    session.commit()
    monkeypatch.setenv("DAPX_SMTP_DEFAULT_PASSWORD", "nuova")
    db_mod.init_default_config(session)
    notif = session.query(db_mod.NotificationConfig).first()
    assert decrypt_secret(notif.smtp_password) == "esistente"
```

- [ ] **Step 2: Verificare che falliscano**

Run: `cd /Users/riccardo/Progetti/DA-PXREPL/dapx-unified/backend && ./venv/bin/python -m pytest tests/test_init_default_smtp.py -v`
Expected: FAIL (`notif.smtp_host` è None, non "esva.domarc.it")

- [ ] **Step 3: Implementare il seed (`backend/database.py`)**

Aggiungere le costanti a livello modulo, subito sopra `def init_default_config(db_session):`:

```python
# Default SMTP domarc — SOLO dati non segreti (il repo è pubblico).
# La password arriva dall'env DAPX_SMTP_DEFAULT_PASSWORD al primo avvio
# (scritta da install.sh nell'env file, mai in git) e viene cifrata nel DB.
DEFAULT_SMTP_HOST = "esva.domarc.it"
DEFAULT_SMTP_PORT = 25
DEFAULT_SMTP_USER = "smtp.domarc"
```

Sostituire il blocco:

```python
    # Inizializza NotificationConfig se non esiste
    if not db_session.query(NotificationConfig).first():
        db_session.add(NotificationConfig())
```

con:

```python
    # Inizializza NotificationConfig e semina i default SMTP domarc.
    # Il seed tocca solo config vergini (smtp_host/smtp_password vuoti):
    # mai sovrascrivere una configurazione esistente. smtp_enabled resta
    # False finché l'admin non imposta i destinatari.
    notif = db_session.query(NotificationConfig).first()
    if not notif:
        notif = NotificationConfig()
        db_session.add(notif)
    if not notif.smtp_host:
        notif.smtp_host = DEFAULT_SMTP_HOST
        notif.smtp_port = DEFAULT_SMTP_PORT
        notif.smtp_user = DEFAULT_SMTP_USER
        notif.smtp_tls = True
    default_smtp_password = os.environ.get("DAPX_SMTP_DEFAULT_PASSWORD")
    if default_smtp_password and not notif.smtp_password:
        try:
            from services.secrets import encrypt_secret
            notif.smtp_password = encrypt_secret(default_smtp_password)
        except RuntimeError as e:
            logger.warning(f"Password SMTP di default non seminata: {e}")
```

(`import os` e `logger` sono già presenti in database.py; verificarlo, e in caso contrario aggiungerli in testa.)

- [ ] **Step 4: Verificare che i test passino**

Run: `cd /Users/riccardo/Progetti/DA-PXREPL/dapx-unified/backend && ./venv/bin/python -m pytest tests/test_init_default_smtp.py tests/test_settings.py -v`
Expected: PASS (tutti)

- [ ] **Step 5: Commit**

```bash
cd /Users/riccardo/Progetti/DA-PXREPL/dapx-unified
git add backend/database.py backend/tests/test_init_default_smtp.py
git commit -m "feat(notifications): default SMTP domarc seminati al primo avvio, password cifrata da env

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: STARTTLS opportunistico in `email_service`

**Files:**
- Modify: `backend/services/email_service.py` (`send_email`, rami connessione ~righe 92-112)
- Test: `backend/tests/test_email_notifications.py`

**Interfaces:**
- Consumes: attributi esistenti `self.host/port/user/password/use_tls`.
- Produces: con `use_tls=True` e porta ≠ 465, STARTTLS viene usato solo se il server lo annuncia (`has_extn("starttls")`), altrimenti si prosegue in chiaro. Porta 465 invariata (SSL diretto). `use_tls=False` invariato (mai TLS).

- [ ] **Step 1: Scrivere i test (falliscono)**

Aggiungere in coda a `backend/tests/test_email_notifications.py`:

```python
class FakeSMTP:
    """Doppione di smtplib.SMTP che registra le chiamate."""

    supports_starttls = True
    instances = []

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.calls = []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def ehlo(self):
        self.calls.append("ehlo")

    def has_extn(self, name):
        return FakeSMTP.supports_starttls

    def starttls(self, context=None):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append(("login", user))

    def sendmail(self, from_addr, to_addrs, msg):
        self.calls.append(("sendmail", from_addr, tuple(to_addrs)))


def _configure_smtp25(**overrides):
    params = dict(
        host="mail.example.com", port=25, user="utente", password="pw",
        from_addr="mittente@example.com", to_addrs="dest@example.com",
        subject_prefix="[DAPX]", use_tls=True,
    )
    params.update(overrides)
    email_service.configure(**params)


def test_starttls_used_when_offered(monkeypatch):
    import services.email_service as es
    FakeSMTP.instances = []
    FakeSMTP.supports_starttls = True
    monkeypatch.setattr(es.smtplib, "SMTP", FakeSMTP)
    _configure_smtp25()
    ok, _ = email_service.send_email("Oggetto", "Corpo")
    assert ok
    calls = FakeSMTP.instances[-1].calls
    assert "starttls" in calls


def test_plain_fallback_when_starttls_not_offered(monkeypatch):
    import services.email_service as es
    FakeSMTP.instances = []
    FakeSMTP.supports_starttls = False
    monkeypatch.setattr(es.smtplib, "SMTP", FakeSMTP)
    _configure_smtp25()
    ok, _ = email_service.send_email("Oggetto", "Corpo")
    assert ok
    calls = FakeSMTP.instances[-1].calls
    assert "starttls" not in calls
    assert ("login", "utente") in calls


def test_no_tls_when_disabled(monkeypatch):
    import services.email_service as es
    FakeSMTP.instances = []
    FakeSMTP.supports_starttls = True
    monkeypatch.setattr(es.smtplib, "SMTP", FakeSMTP)
    _configure_smtp25(use_tls=False)
    ok, _ = email_service.send_email("Oggetto", "Corpo")
    assert ok
    calls = FakeSMTP.instances[-1].calls
    assert "starttls" not in calls
```

- [ ] **Step 2: Verificare che falliscano**

Run: `cd /Users/riccardo/Progetti/DA-PXREPL/dapx-unified/backend && ./venv/bin/python -m pytest tests/test_email_notifications.py -v`
Expected: FAIL su `test_plain_fallback_when_starttls_not_offered` (il codice attuale chiama `starttls()` incondizionatamente quando `use_tls=True`)

- [ ] **Step 3: Implementare STARTTLS opportunistico**

In `backend/services/email_service.py`, `send_email()`: lasciare invariato il ramo `if self.port == 465:` e sostituire i due rami `elif self.use_tls:` e `else:` con un unico ramo:

```python
            else:
                # Porte non-465: STARTTLS opportunistico quando use_tls è attivo
                # (il server domarc lo espone come opzionale), altrimenti in chiaro.
                with smtplib.SMTP(self.host, self.port, timeout=30) as server:
                    if self.use_tls:
                        server.ehlo()
                        if server.has_extn("starttls"):
                            context = ssl.create_default_context()
                            server.starttls(context=context)
                            server.ehlo()
                        else:
                            logger.info(
                                f"STARTTLS non offerto da {self.host}:{self.port}, invio in chiaro"
                            )
                    if self.user and self.password:
                        server.login(self.user, self.password)
                    server.sendmail(self.from_addr, recipients, msg.as_string())
```

- [ ] **Step 4: Verificare che i test passino**

Run: `cd /Users/riccardo/Progetti/DA-PXREPL/dapx-unified/backend && ./venv/bin/python -m pytest tests/test_email_notifications.py -v`
Expected: PASS (tutti)

- [ ] **Step 5: Commit**

```bash
cd /Users/riccardo/Progetti/DA-PXREPL/dapx-unified
git add backend/services/email_service.py backend/tests/test_email_notifications.py
git commit -m "feat(email): STARTTLS opportunistico su porte non-465

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: Oggetto `CODCLI - NOMECLI — …` e mittente derivato

**Files:**
- Modify: `backend/services/email_service.py` (`__init__`, `configure`, nuovo `_build_subject`, `send_email`)
- Modify: `backend/services/notification_service.py` (`_configure_email_service`: due kwargs)
- Modify: `backend/routers/settings.py` (endpoint test: due kwargs)
- Test: `backend/tests/test_email_notifications.py`

**Interfaces:**
- Consumes: `config.client_code`/`config.client_name` dal Task 4.
- Produces: `EmailService.configure(..., client_code: Optional[str] = None, client_name: Optional[str] = None)`; `EmailService._build_subject(subject: str) -> str`; costante modulo `DEFAULT_SENDER_DOMAIN = "domarc.it"`. L'oggetto finale è `"{client_code} - {client_name} — {subject_prefix} {subject}"` quando entrambi i campi sono valorizzati, altrimenti il formato attuale. Mittente: `smtp_from` esplicito vince; altrimenti `dapx-<codcli minuscolo senza spazi>@domarc.it`; altrimenti `dapx@domarc.it` (il vecchio fallback `from_addr or user` sparisce: `smtp.domarc` non è un indirizzo email valido).

- [ ] **Step 1: Scrivere i test (falliscono)**

Aggiungere in coda a `backend/tests/test_email_notifications.py`:

```python
def _configure_client(**overrides):
    params = dict(
        host="mail.example.com", port=25, user="utente", password="pw",
        from_addr="mittente@example.com", to_addrs="dest@example.com",
        subject_prefix="[DAPX]", use_tls=False,
        client_code=None, client_name=None,
    )
    params.update(overrides)
    email_service.configure(**params)


def test_subject_with_client():
    _configure_client(client_code="C0123", client_name="ACME Srl")
    assert email_service._build_subject("Job OK") == "C0123 - ACME Srl — [DAPX] Job OK"


def test_subject_without_client():
    _configure_client()
    assert email_service._build_subject("Job OK") == "[DAPX] Job OK"


def test_subject_partial_client_falls_back():
    _configure_client(client_code="C0123", client_name=None)
    assert email_service._build_subject("Job OK") == "[DAPX] Job OK"


def test_from_derived_from_client_code():
    _configure_client(from_addr=None, client_code="C 0123", client_name="ACME Srl")
    assert email_service.from_addr == "dapx-c0123@domarc.it"


def test_from_default_without_client():
    _configure_client(from_addr=None)
    assert email_service.from_addr == "dapx@domarc.it"


def test_from_explicit_wins():
    _configure_client(from_addr="custom@domarc.it", client_code="C0123", client_name="ACME Srl")
    assert email_service.from_addr == "custom@domarc.it"
```

- [ ] **Step 2: Verificare che falliscano**

Run: `cd /Users/riccardo/Progetti/DA-PXREPL/dapx-unified/backend && ./venv/bin/python -m pytest tests/test_email_notifications.py -v`
Expected: FAIL/ERROR (`configure()` non accetta `client_code`; `_build_subject` non esiste)

- [ ] **Step 3: Implementare in `backend/services/email_service.py`**

Costante a livello modulo, sotto `logger = logging.getLogger(__name__)`:

```python
# Dominio mittente di default per gli indirizzi derivati (dapx@…, dapx-<codcli>@…)
DEFAULT_SENDER_DOMAIN = "domarc.it"
```

In `__init__`, dopo `self.use_tls: bool = True`:

```python
        self.client_code: str = ""
        self.client_name: str = ""
```

Sostituire la firma e il corpo di `configure` con:

```python
    def configure(
        self,
        host: str,
        port: int = 587,
        user: Optional[str] = None,
        password: Optional[str] = None,
        from_addr: Optional[str] = None,
        to_addrs: Optional[str] = None,
        subject_prefix: str = "[DAPX]",
        use_tls: bool = True,
        client_code: Optional[str] = None,
        client_name: Optional[str] = None
    ):
        """Configura il servizio email"""
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.client_code = (client_code or "").strip()
        self.client_name = (client_name or "").strip()
        if from_addr:
            self.from_addr = from_addr
        elif self.client_code:
            local = "dapx-" + self.client_code.lower().replace(" ", "")
            self.from_addr = f"{local}@{DEFAULT_SENDER_DOMAIN}"
        else:
            self.from_addr = f"dapx@{DEFAULT_SENDER_DOMAIN}"
        self.to_addrs = [addr.strip() for addr in (to_addrs or "").split(",") if addr.strip()]
        self.subject_prefix = subject_prefix
        self.use_tls = use_tls
```

Aggiungere il metodo `_build_subject` subito dopo `configure`:

```python
    def _build_subject(self, subject: str) -> str:
        """Oggetto finale: 'CODCLI - NOMECLI — <prefix> <subject>' se il cliente è configurato."""
        full = f"{self.subject_prefix} {subject}".strip()
        if self.client_code and self.client_name:
            return f"{self.client_code} - {self.client_name} — {full}"
        return full
```

In `send_email`, sostituire `msg["Subject"] = f"{self.subject_prefix} {subject}"` con:

```python
            msg["Subject"] = self._build_subject(subject)
```

- [ ] **Step 4: Passare i campi cliente dai chiamanti**

In `backend/services/notification_service.py`, nella chiamata `email_service.configure(...)` dentro `_configure_email_service`, aggiungere dopo `use_tls=...`:

```python
                client_code=config.client_code,
                client_name=config.client_name,
```

In `backend/routers/settings.py`, nella chiamata `email_service.configure(...)` dell'endpoint `test_notification`, aggiungere dopo `use_tls=config.smtp_tls`:

```python
            client_code=config.client_code,
            client_name=config.client_name,
```

- [ ] **Step 5: Verificare che i test passino (nuovi + regressione completa)**

Run: `cd /Users/riccardo/Progetti/DA-PXREPL/dapx-unified/backend && ./venv/bin/python -m pytest tests/test_email_notifications.py tests/test_settings.py -v`
Expected: PASS (tutti)

- [ ] **Step 6: Commit**

```bash
cd /Users/riccardo/Progetti/DA-PXREPL/dapx-unified
git add backend/services/email_service.py backend/services/notification_service.py backend/routers/settings.py backend/tests/test_email_notifications.py
git commit -m "feat(email): oggetto 'CODCLI - NOMECLI' su ogni email e mittente derivato dapx-<codcli>@domarc.it

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: Frontend — campi cliente nella tab Notifiche

**Files:**
- Modify: `frontend/src/services/settings.ts` (interfaccia `NotificationConfig`, ~riga 12)
- Modify: `frontend/src/views/Settings.vue` (tab Notifiche, dopo il form-group "Prefisso Oggetto Email", ~riga 122)

**Interfaces:**
- Consumes: campi API `client_code`/`client_name` dal Task 4; `notifications = ref<NotificationConfig | null>(null)` esistente (i valori arrivano dal GET, nessun default da inizializzare lato client).
- Produces: due input testuali bindati a `notifications.client_code` / `notifications.client_name`, salvati dal bottone di salvataggio esistente della tab.

- [ ] **Step 1: Estendere l'interfaccia TypeScript**

In `frontend/src/services/settings.ts`, dentro `export interface NotificationConfig`, dopo `smtp_tls: boolean;`:

```typescript
    client_code?: string;
    client_name?: string;
```

- [ ] **Step 2: Aggiungere i campi nella vista**

In `frontend/src/views/Settings.vue`, subito DOPO il `</div>` che chiude il form-group "Prefisso Oggetto Email" (riga ~122, dentro il blocco `v-if="notifications.smtp_enabled"`), aggiungere — replicando ESATTAMENTE il contenitore a due colonne già usato per la coppia Host/Porta poche righe sopra (stesso wrapper, stesse classi):

```html
                        <div class="form-group">
                            <label>Codice Cliente (oggetto email)</label>
                            <input type="text" v-model="notifications.client_code" class="form-input" placeholder="C0123">
                        </div>

                        <div class="form-group">
                            <label>Nome Cliente (oggetto email)</label>
                            <input type="text" v-model="notifications.client_name" class="form-input" placeholder="ACME Srl">
                        </div>
```

Nota: prima di incollare, guardare le righe 71-100 del file per copiare l'eventuale wrapper `<div class="form-row">`/griglia usato per Host+Porta e applicare lo stesso pattern a questa coppia. Indentazione coerente col file (il file usa indentazione a spazi come le righe adiacenti).

- [ ] **Step 3: Verificare la build frontend**

Run: `cd /Users/riccardo/Progetti/DA-PXREPL/dapx-unified/frontend && npm run build`
Expected: build Vite completata senza errori TypeScript. NON committare `dist/` adesso (si rigenera al rilascio).

- [ ] **Step 4: Commit**

```bash
cd /Users/riccardo/Progetti/DA-PXREPL/dapx-unified
git add frontend/src/services/settings.ts frontend/src/views/Settings.vue
git commit -m "feat(ui): campi Codice/Nome Cliente nella tab Notifiche

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 9: install.sh, config.env.example, CHANGELOG

**Files:**
- Modify: `install.sh` (pre-parse argomenti, funzione `persist_smtp_password`, chiamate, testi `--help`)
- Modify: `backend/config.env.example`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: env file `$CONFIG_DIR/dapx-unified.env` scritto da `generate_secret_key()` (già `chmod 600`); variabili globali `CONFIG_DIR`, funzioni `log_success` esistenti in install.sh.
- Produces: `install.sh --smtp-password <PW>` (o env `DAPX_SMTP_PASSWORD`) scrive `DAPX_SMTP_DEFAULT_PASSWORD=<PW>` nell'env file, sia in install fresca sia in `--update`. Il backend la consuma al primo avvio (Task 5).

- [ ] **Step 1: Pre-parse del flag `--smtp-password`**

In `install.sh`, subito PRIMA del commento `# ============== ENTRY POINT ==============` (riga ~1381), aggiungere:

```bash
# --- Password SMTP di default (MAI committata: arriva da env o flag) ---
SMTP_DEFAULT_PASSWORD="${DAPX_SMTP_PASSWORD:-}"
_args=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --smtp-password)
            SMTP_DEFAULT_PASSWORD="${2:-}"
            shift 2
            ;;
        --smtp-password=*)
            SMTP_DEFAULT_PASSWORD="${1#*=}"
            shift
            ;;
        *)
            _args+=("$1")
            shift
            ;;
    esac
done
if [[ ${#_args[@]} -gt 0 ]]; then
    set -- "${_args[@]}"
else
    set --
fi
unset _args
```

- [ ] **Step 2: Funzione di persistenza**

Aggiungere la funzione subito DOPO `generate_secret_key()` (riga ~692):

```bash
persist_smtp_password() {
    # Scrive/aggiorna DAPX_SMTP_DEFAULT_PASSWORD nell'env file.
    # Il valore non viene MAI loggato. Riscrittura via file temporaneo
    # per evitare problemi di escaping con sed.
    [[ -n "$SMTP_DEFAULT_PASSWORD" ]] || return 0
    local env_file="$CONFIG_DIR/dapx-unified.env"
    if [[ ! -f "$env_file" ]]; then
        log_error "Env file $env_file non trovato: password SMTP non registrata"
        return 1
    fi
    local tmp
    tmp=$(mktemp)
    grep -v '^DAPX_SMTP_DEFAULT_PASSWORD=' "$env_file" > "$tmp" || true
    printf 'DAPX_SMTP_DEFAULT_PASSWORD=%s\n' "$SMTP_DEFAULT_PASSWORD" >> "$tmp"
    install -m 600 "$tmp" "$env_file"
    rm -f "$tmp"
    log_success "Password SMTP di default registrata nell'env file (verrà cifrata nel DB al primo avvio)"
}
```

- [ ] **Step 3: Chiamare la funzione nei flussi install e update**

Individuare i punti con: `grep -n "generate_secret_key\b" install.sh` e `grep -n "^update_existing()\|update_existing()" install.sh`.

1. In ogni punto in cui viene INVOCATA `generate_secret_key` (flusso install), aggiungere sulla riga successiva: `persist_smtp_password`
2. Dentro la funzione `update_existing()`, dopo i controlli iniziali sull'installazione esistente (quando `$CONFIG_DIR` è noto e l'installazione è confermata), aggiungere: `persist_smtp_password`

- [ ] **Step 4: Aggiornare i testi di help**

In ENTRAMBI i blocchi di help (il `--help` dentro `main()` riga ~1292 e la funzione `show_help`, trovarla con `grep -n "show_help" install.sh`), aggiungere accanto alle altre opzioni:

```bash
    echo "  --smtp-password P Registra la password SMTP di default (equivalente: env DAPX_SMTP_PASSWORD)"
```

- [ ] **Step 5: Verificare la sintassi**

Run: `bash -n /Users/riccardo/Progetti/DA-PXREPL/dapx-unified/install.sh && echo SYNTAX_OK`
Expected: `SYNTAX_OK`

Run: `grep -c "persist_smtp_password" /Users/riccardo/Progetti/DA-PXREPL/dapx-unified/install.sh`
Expected: almeno 3 (definizione + 2 chiamate)

- [ ] **Step 6: Documentare in `backend/config.env.example`**

Aggiungere in coda al file:

```bash
# Password SMTP di default (opzionale). Se presente al primo avvio e il DB
# non ha ancora una password SMTP, viene cifrata e salvata nel DB
# (services/secrets.py). MAI committare il valore reale: il repo è pubblico.
# DAPX_SMTP_DEFAULT_PASSWORD=
```

- [ ] **Step 7: Aggiornare `CHANGELOG.md`**

Aggiungere sotto l'intestazione, come sezione `## [Unreleased]` (crearla se assente, sopra l'ultima versione rilasciata):

```markdown
## [Unreleased]

### Aggiunte
- Default SMTP domarc seminati al primo avvio (host/porta/utente); la password arriva al deploy via `install.sh --smtp-password` o env `DAPX_SMTP_PASSWORD` e viene cifrata nel DB (`backend/database.py`, `install.sh`).
- Campi `client_code`/`client_name` nella configurazione notifiche; oggetto email sempre `CODCLI - NOMECLI — …` (`backend/services/email_service.py`, `frontend/src/views/Settings.vue`).
- Helper generico di cifratura segreti con Fernet/`DAPX_SECRET_KEY` (`backend/services/secrets.py`).

### Modifiche
- STARTTLS opportunistico sulle porte diverse da 465: usato solo se il server lo annuncia (`backend/services/email_service.py`).
- Mittente derivato `dapx-<codcli>@domarc.it` quando `smtp_from` non è impostato (`backend/services/email_service.py`).

### Correzioni
- La password SMTP è ora cifrata at-rest nel DB (prima era salvata in chiaro); migrazione idempotente cifra le password esistenti (`backend/routers/settings.py`, `backend/update_db_schema.py`).
```

- [ ] **Step 8: Suite completa e commit**

Run: `cd /Users/riccardo/Progetti/DA-PXREPL/dapx-unified/backend && ./venv/bin/python -m pytest tests/ -q`
Expected: PASS (nessun fallimento; se falliscono test NON toccati da questo lavoro, segnalarlo senza "fixarli" — regola del CLAUDE.md di progetto)

```bash
cd /Users/riccardo/Progetti/DA-PXREPL/dapx-unified
git add install.sh backend/config.env.example CHANGELOG.md
git commit -m "feat(install): flag --smtp-password / env DAPX_SMTP_PASSWORD per la password SMTP di default

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Note post-implementazione (non fanno parte dei task)

- **Rilascio**: quando l'utente decide di rilasciare, seguire la procedura obbligatoria del CLAUDE.md di progetto (bump 5 file versione, rebuild `frontend/dist`, CHANGELOG versionato, tag, `gh release create`).
- **Installazioni esistenti (.199, .145)**: dopo l'update, la migrazione cifra le password già presenti. Per seminare la password di default dove non configurata: aggiungere `DAPX_SMTP_DEFAULT_PASSWORD=…` a `/etc/dapx-unified/dapx-unified.env` e riavviare il servizio, oppure inserirla nella tab Notifiche.
- **Verifica end-to-end manuale** (dopo il deploy): tab Notifiche → compila destinatari + codcli/nomecli → abilita → "Test email" → controllare che l'oggetto sia `CODCLI - NOMECLI — [DAPX] 🧪 Email di Test`.
