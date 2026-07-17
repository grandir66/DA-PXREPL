"""Test normalizzazione path Synology."""

from services.file_replication.path_utils import normalize_synology_ssh_path


def test_parse_share_path():
    from services.file_replication.path_utils import parse_synology_share_path

    assert parse_synology_share_path("/DATI/archivio") == ("DATI", "archivio")
    assert parse_synology_share_path("/volume1/DATI/archivio") == ("DATI", "archivio")
