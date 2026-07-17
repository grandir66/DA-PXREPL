"""Test normalizzazione path Synology."""

from services.file_replication.path_utils import normalize_synology_ssh_path


def test_normalize_datI_to_volume1():
    assert normalize_synology_ssh_path("/DATI/archivio") == "/volume1/DATI/archivio"


def test_keep_volume_path():
    assert normalize_synology_ssh_path("/volume2/DATI/archivio") == "/volume2/DATI/archivio"
