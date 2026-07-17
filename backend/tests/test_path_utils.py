"""Test normalizzazione path Synology."""

from services.file_replication.path_utils import normalize_synology_ssh_path


def test_parse_share_path():
    from services.file_replication.path_utils import parse_synology_share_path

    assert parse_synology_share_path("/DATI/archivio") == ("DATI", "archivio")
    assert parse_synology_share_path("/volume1/DATI/archivio") == ("DATI", "archivio")


def test_normalize_qnap_dest_share():
    from services.file_replication.path_utils import normalize_qnap_dest_share

    assert normalize_qnap_dest_share("/share/DATI/Comune") == "/share/DATI"
    assert normalize_qnap_dest_share("/DATI/Comune/AArchivio") == "/share/DATI"


def test_synology_to_qnap_dest_path():
    from services.file_replication.path_utils import synology_to_qnap_dest_path

    assert synology_to_qnap_dest_path("/Comune/AArchivio", "/share/DATI/Comune") == (
        "/share/DATI/Comune/AArchivio/"
    )
    assert synology_to_qnap_dest_path("/Duerre", "/share/DATI/Comune") == "/share/DATI/Duerre/"
    assert synology_to_qnap_dest_path("/Duerre/progetti", "/share/DATI") == (
        "/share/DATI/Duerre/progetti/"
    )


def test_qnap_rclone_dest_path():
    from services.file_replication.path_utils import qnap_rclone_dest_path

    assert qnap_rclone_dest_path("/share/DATI/Comune") == "DATI/Comune"
    assert qnap_rclone_dest_path("/share/DATI/Comune/AArchivio/") == "DATI/Comune/AArchivio"


def test_compact_source_paths():
    from services.file_replication.path_utils import compact_source_paths, is_path_ancestor

    assert compact_source_paths(["/Comune/AArchivio", "/Comune"]) == ["/Comune"]
    assert compact_source_paths(["/Comune", "/Duerre"]) == ["/Comune", "/Duerre"]
    assert is_path_ancestor("/Comune", "/Comune/AArchivio") is True


def test_normalize_qnap_staging_path():
    from services.file_replication.path_utils import normalize_qnap_staging_path

    assert normalize_qnap_staging_path("/DATI/Comune") == "/share/DATI/Comune"
    assert normalize_qnap_staging_path("/share/DATI/Comune") == "/share/DATI/Comune"
