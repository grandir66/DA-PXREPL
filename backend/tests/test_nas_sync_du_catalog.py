"""Test parser catalogo du nas_sync."""

from services.nas_sync.du_catalog import build_du_script, parse_du_output


def test_build_du_script_excludes_system_dirs():
    script = build_du_script("/volume1/Condivisa/")
    assert "du -sb" in script
    assert "! -name '@*'" in script
    assert "! -name '#*'" in script
    assert "maxdepth 1" in script


def test_parse_du_output_maps_fs_to_logical_paths():
    text = (
        "524288000\t/volume1/Condivisa\n"
        "104857600\t/volume1/Condivisa/Progetti\n"
        "209715200\t/volume1/Condivisa/Archivio\n"
    )
    folders, total = parse_du_output(text, "/volume1/Condivisa/", "/Condivisa")
    assert total == 524288000
    assert folders == [
        {"path": "/Condivisa/Progetti", "name": "Progetti", "bytes": 104857600},
        {"path": "/Condivisa/Archivio", "name": "Archivio", "bytes": 209715200},
    ]


def test_parse_du_output_ignores_malformed_lines():
    folders, total = parse_du_output("garbage\n123\n", "/volume1/X/", "/X")
    assert folders == []
    assert total == 0
