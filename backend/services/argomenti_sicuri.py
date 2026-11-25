"""Controllo dei valori che arrivano da fuori prima di metterli in un comando ssh.

Rilievo A1 della valutazione di sicurezza del 25/11/2026: più rotte per
«operator» componevano una riga di comando (`zfs rollback`, `zfs destroy`,
`qmrestore`, `pvesh delete`) con un testo scelto dall'utente; un nome con `;`
aggiungeva un secondo comando, eseguito da root sul nodo.

Ogni funzione restituisce il valore se è nella forma attesa, altrimenti
risponde 400. Si accetta per elenco di caratteri ammessi, non per elenco di
caratteri vietati: ciò che non è previsto è rifiutato.
"""

from __future__ import annotations

import re

from fastapi import HTTPException

# Può cominciare con `_` (gli snapshot `__replicate_*` di pvesr), mai con `-`.
_PEZZO = r"[A-Za-z0-9_][A-Za-z0-9_.:\-]*"
_SNAPSHOT = re.compile(rf"^{_PEZZO}$")
_DATASET = re.compile(rf"^{_PEZZO}(/{_PEZZO})*$")
_STORAGE = re.compile(r"^[A-Za-z][A-Za-z0-9_.\-]*$")
_VOLUME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./:\-]*$")
_JOB_PVESR = re.compile(r"^[0-9]{1,9}-[0-9]{1,4}$")
_NODO = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9\-]{0,61}[A-Za-z0-9])?$")

_MAX = 255


def _controlla(valore, modello: re.Pattern, messaggio: str) -> str:
    if not isinstance(valore, str) or not valore or len(valore) > _MAX or not modello.match(valore):
        raise HTTPException(status_code=400, detail=messaggio)
    return valore


def nome_snapshot(valore) -> str:
    """Il solo nome dello snapshot, senza dataset e senza `@`."""
    return _controlla(valore, _SNAPSHOT, "Nome snapshot non valido")


def nome_dataset(valore) -> str:
    return _controlla(valore, _DATASET, "Nome dataset non valido")


def snapshot_completo(valore) -> str:
    """`pool/dataset@snapshot`."""
    if not isinstance(valore, str) or valore.count("@") != 1:
        raise HTTPException(status_code=400, detail="Nome snapshot non valido")
    dataset, snap = valore.split("@")
    nome_dataset(dataset)
    nome_snapshot(snap)
    return valore


def id_storage(valore) -> str:
    return _controlla(valore, _STORAGE, "Storage non valido")


def volume_backup(valore) -> str:
    v = _controlla(valore, _VOLUME, "Identificativo del backup non valido")
    if ".." in v:
        raise HTTPException(status_code=400, detail="Identificativo del backup non valido")
    return v


def id_job_pvesr(valore) -> str:
    """`<vmid>-<numero>`, come li numera Proxmox."""
    return _controlla(valore, _JOB_PVESR, "Identificativo del job non valido")


def nome_nodo(valore) -> str:
    return _controlla(valore, _NODO, "Nome nodo non valido")
