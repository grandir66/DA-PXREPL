#!/usr/bin/env python3
"""Chi manda ancora mail, e chi è uscito dalle notifiche. Sola lettura.

Dopo il cambio dell'8 settembre 2026 l'impostazione predefinita dei job
(`daily`) non manda più nessuna mail immediata: le esecuzioni compaiono solo
nel riepilogo giornaliero. Restano rumorosi i job impostati a mano su
**«Mail a ogni esecuzione»** (`always`), che nessuna migrazione tocca — è una
scelta di chi ha configurato quel job, e non sta a noi ribaltarla in silenzio.

Questo script dice quali sono, così la si può confermare o cambiare sapendo
di che numeri si parla. Dice anche chi è su `never`, che dal riepilogo esce
del tutto: silenzioso non deve voler dire dimenticato.

Uso, sull'appliance:

    python3 backend/scripts/notifiche_stato.py
    DAPX_DB=/percorso/altro.db python3 backend/scripts/notifiche_stato.py

Non scrive niente: si può lanciare su un impianto in esercizio.
"""

import os
import sqlite3
import sys

# Le tabelle che hanno una colonna `notify_mode`, con la sigla della loro
# tipologia (le stesse di `services/notification_summary.py`). `recovery_jobs`
# e `backup_jobs` non compaiono: usano `notify_on_each_run`, gestito sotto.
TABELLE = (
    ("sync_jobs", "REPL-VM", "Replica VM (ZFS/BTRFS)"),
    ("vm_snapshot_jobs", "SNAPSHOT", "Snapshot VM pianificati"),
    ("file_replication_jobs", "DATI", "Replica file e cartelle"),
    ("nas_sync_jobs", "NAS", "Sincronizzazione verso NAS"),
    ("host_backup_jobs", "HOST", "Backup configurazione host"),
    ("migration_jobs", "MIGRAZIONE", "Migrazione live"),
)

SPIEGA = {
    "daily": "solo nel riepilogo giornaliero (predefinito)",
    "failure": "riepilogo + mail subito se fallisce",
    "always": "MAIL A OGNI ESECUZIONE",
    "never": "escluso da tutto, riepilogo compreso",
}


def percorso_db() -> str:
    for var in ("DAPX_DB", "SANOID_MANAGER_DB"):
        valore = os.environ.get(var)
        if valore and valore != ":memory:":
            return valore
    for candidato in (
        "/opt/dapx-backandrepl/backend/sanoid_manager.db",
        "/opt/sanoid-manager/backend/sanoid_manager.db",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sanoid_manager.db"),
    ):
        if os.path.isfile(candidato):
            return candidato
    return ""


def tabella_esiste(cur, nome: str) -> bool:
    cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (nome,))
    return cur.fetchone() is not None


def main() -> int:
    db = percorso_db()
    if not db:
        print("Database non trovato. Indicalo con DAPX_DB=/percorso/al.db", file=sys.stderr)
        return 2
    print(f"Database: {db}\n")

    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    conti: dict[str, int] = {}
    rumorosi: list[str] = []
    silenziati: list[str] = []

    for tabella, sigla, descrizione in TABELLE:
        if not tabella_esiste(cur, tabella):
            continue
        cur.execute(
            f"SELECT name, COALESCE(notify_mode, 'daily') AS m, is_active FROM {tabella}"  # noqa: S608
        )
        righe = cur.fetchall()
        if not righe:
            continue
        per_modo: dict[str, int] = {}
        for r in righe:
            if not r["is_active"]:
                continue
            per_modo[r["m"]] = per_modo.get(r["m"], 0) + 1
            conti[r["m"]] = conti.get(r["m"], 0) + 1
            if r["m"] == "always":
                rumorosi.append(f"{sigla} · {r['name']}")
            elif r["m"] == "never":
                silenziati.append(f"{sigla} · {r['name']}")
        if per_modo:
            dettaglio = ", ".join(f"{m}: {n}" for m, n in sorted(per_modo.items()))
            print(f"{sigla:12} {descrizione:38} {dettaglio}")

    # Recovery e Backup PBS non hanno `notify_mode`: hanno un interruttore
    # booleano, che il codice traduce in «always».
    for tabella, sigla in (("recovery_jobs", "RECOVERY"), ("backup_jobs", "BACKUP")):
        if not tabella_esiste(cur, tabella):
            continue
        cur.execute(
            f"SELECT name FROM {tabella} WHERE is_active = 1 AND notify_on_each_run = 1"  # noqa: S608
        )
        for r in cur.fetchall():
            rumorosi.append(f"{sigla} · {r['name']} (notify_on_each_run)")
            conti["always"] = conti.get("always", 0) + 1

    print("\n--- riepilogo ---")
    for modo in ("daily", "failure", "always", "never"):
        if conti.get(modo):
            print(f"  {conti[modo]:4}  {modo:8} {SPIEGA[modo]}")

    if rumorosi:
        print(f"\nMandano ancora una mail a OGNI esecuzione ({len(rumorosi)}):")
        for nome in rumorosi:
            print(f"  · {nome}")
        print("\n  Per zittirli senza perdere niente: portarli su «Solo nel riepilogo")
        print("  giornaliero», oppure su «Riepilogo + mail subito se fallisce» se si")
        print("  vuole comunque l'avviso immediato sui guasti.")
    else:
        print("\nNessun job manda mail a ogni esecuzione: arriva solo il riepilogo.")

    if silenziati:
        print(f"\nEsclusi da tutto, riepilogo compreso ({len(silenziati)}):")
        for nome in silenziati:
            print(f"  · {nome}")
        print("\n  Un guasto su questi job non lo dice nessuno. Voluto?")

    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
