"""Destinatario notifiche predefinito (decisione 05/10/2026).

Ogni installazione parte con smtp_to = proxmox@domarc.it; un valore gia'
impostato non viene mai sovrascritto dal seed.
"""
import pytest

from database import NotificationConfig, init_default_config, DEFAULT_SMTP_TO


def test_costante():
    assert DEFAULT_SMTP_TO == "proxmox@domarc.it"


def test_db_nuovo_riceve_il_default(db):
    init_default_config(db)
    assert db.query(NotificationConfig).first().smtp_to == "proxmox@domarc.it"


@pytest.mark.parametrize("vuoto", [None, "", "   "])
def test_riga_esistente_vuota_viene_riempita(db, vuoto):
    db.add(NotificationConfig(smtp_to=vuoto))
    db.commit()
    db.query(NotificationConfig).update({"smtp_to": vuoto})
    db.commit()
    init_default_config(db)
    assert db.query(NotificationConfig).first().smtp_to == "proxmox@domarc.it"


def test_valore_esistente_non_si_tocca(db):
    db.add(NotificationConfig(smtp_to="helpdesk@domarc.it"))
    db.commit()
    init_default_config(db)
    init_default_config(db)
    assert db.query(NotificationConfig).first().smtp_to == "helpdesk@domarc.it"
