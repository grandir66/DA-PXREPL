"""Come si costruisce il piano di replica file Synology → QNAP.

Questo file conteneva un test che si contraddiceva da solo: pretendeva una
tappa `rsync` e, tre righe più sotto, che il piano fosse `rclone_sync`. È il
segno di un aggiornamento lasciato a metà quando è entrato rclone — chi ha
aggiunto l'asserzione nuova non ha tolto quella vecchia, e il test è rimasto
rosso senza che nessuno lo leggesse. Preteneva anche l'utente `domarc@` sulla
destinazione, mentre da tempo si usa quello dichiarato sull'endpoint.

Le due strade esistono davvero, e adesso hanno un test ciascuna:

* **la predefinita** — Synology → QNAP passa da rclone: nessun comando rsync;
* **quella con `rsync_module`** — se sulla sorgente è configurato un modulo
  rsync si torna alle due tappe, pull dal modulo e push in ssh sul QNAP.
"""

from database import FileEndpoint, FileEndpointRole, FileEndpointType, FileReplicationJob
from services.file_replication.endpoint_crypto import encrypt_password
from services.file_replication.file_sync_service import build_rsync_legs, build_sync_plan


def _scenario(db, *, extra_sorgente=None):
    """Synology → QNAP, con password vere.

    `password_enc="enc"` non è un segnaposto innocuo: `_ssh_transport` prova a
    decifrarlo e alza `ValueError`. Qui si cifra sul serio con la chiave di
    prova del `conftest`.
    """
    segreto = encrypt_password("pw")
    src = FileEndpoint(
        name="syn",
        endpoint_type=FileEndpointType.SYNOLOGY,
        role=FileEndpointRole.SOURCE,
        host="172.16.1.120",
        port=5001,
        protocol="api",
        username="qnap",
        password_enc=segreto,
        extra_config=extra_sorgente,
    )
    dest = FileEndpoint(
        name="qnap",
        endpoint_type=FileEndpointType.QNAP,
        role=FileEndpointRole.DESTINATION,
        host="172.16.1.125",
        port=443,
        protocol="api",
        username="replica",
        password_enc=segreto,
    )
    job = FileReplicationJob(
        name="t",
        source_endpoint_id=1,
        dest_endpoint_id=2,
        source_paths=["/DATI/archivio"],
        dest_staging_path="/share/DATI/archivio",
    )
    db.add_all([src, dest, job])
    db.commit()
    return job, src, dest


def test_synology_verso_qnap_passa_da_rclone(db):
    """La strada predefinita: un solo passo, e nessun rsync da eseguire."""
    job, src, dest = _scenario(db)

    plan = build_sync_plan(job, src, dest, "/tmp/exclude.txt", "/tmp/staging")
    assert [p["type"] for p in plan] == ["rclone_sync"]
    assert plan[0]["src_path"] == "/DATI/archivio"
    # La struttura Synology si ricrea sotto la share QNAP: la share di
    # partenza si chiama «DATI», quindi il doppio DATI è corretto.
    assert plan[0]["dest_dir"] == "/share/DATI/DATI/archivio/"

    assert build_rsync_legs(job, src, dest, "/tmp/exclude.txt", "/tmp/staging") == []


def test_con_un_modulo_rsync_si_torna_alle_due_tappe(db):
    """Con `rsync_module` sulla sorgente rclone si fa da parte.

    Pull dal modulo rsync del Synology (nessuna password in `argv`: il modulo
    è un endpoint `rsync://`), push in ssh sul QNAP con l'utente dichiarato
    sull'endpoint — non uno cablato nel codice.
    """
    job, src, dest = _scenario(db, extra_sorgente={"rsync_module": "NetBackup"})

    legs = build_rsync_legs(job, src, dest, "/tmp/exclude.txt", "/tmp/staging")
    assert len(legs) == 2
    pull, push = legs

    assert "rsync://qnap@172.16.1.120/NetBackup/DATI/archivio/" in pull
    assert "-e" not in pull, "il modulo rsync non passa da ssh"

    trasporto = push[push.index("-e") + 1]
    assert "ssh -p 22" in trasporto
    assert "sshpass -e" in trasporto, "la password non deve finire in argv"
    assert "replica@172.16.1.125:/share/DATI/DATI/archivio/" in push
