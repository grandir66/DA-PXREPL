"""Test builder e parser del motore diretto rsync."""

import re

from database import FileEndpoint, FileEndpointType
from services.nas_sync.engine_direct_rsync import (
    RSYNC_WARNING_EXITS,
    build_dest_rsync_url,
    build_remote_rsync_script,
    build_source_fs_path,
    build_ssh_argv,
    parse_rsync_line,
)


def _src(ep_type=FileEndpointType.SYNOLOGY, **kw):
    defaults = dict(name="s", endpoint_type=ep_type, host="10.0.0.1", port=5001,
                    protocol="api", username="admin", password_enc="enc",
                    extra_config={})
    defaults.update(kw)
    return FileEndpoint(**defaults)


def _dst(**kw):
    defaults = dict(name="d", endpoint_type=FileEndpointType.QNAP, host="10.0.0.2",
                    port=8080, protocol="api", username="admin", password_enc="enc",
                    extra_config={"rsync_module": "DATI", "rsync_user": "backup",
                                  "rsync_port": 873})
    defaults.update(kw)
    return FileEndpoint(**defaults)


def test_source_fs_path_synology_volume():
    assert build_source_fs_path(_src(), "/Condivisa/docs") == "/volume1/Condivisa/docs/"


def test_source_fs_path_qnap_share_prefix():
    ep = _src(ep_type=FileEndpointType.QNAP)
    assert build_source_fs_path(ep, "/Public/foto") == "/share/Public/foto/"


def test_dest_rsync_url_includes_module_and_subpath():
    url = build_dest_rsync_url(_dst(), "/Condivisa/docs", "")
    assert url == "rsync://backup@10.0.0.2:873/DATI/Condivisa/docs/"


def test_dest_rsync_url_with_base_subpath():
    url = build_dest_rsync_url(_dst(), "/Condivisa/docs", "backup-syno")
    assert url == "rsync://backup@10.0.0.2:873/DATI/backup-syno/Condivisa/docs/"


def test_dest_rsync_url_strips_share_and_module_prefix():
    """dest_base_path UI `/share/DATI` non deve ripetersi sotto il modulo DATI."""
    url = build_dest_rsync_url(_dst(), "/Piegatubi", "/share/DATI")
    assert url == "rsync://backup@10.0.0.2:873/DATI/Piegatubi/"
    url2 = build_dest_rsync_url(_dst(), "/Piegatubi", "/share/DATI/archivio")
    assert url2 == "rsync://backup@10.0.0.2:873/DATI/archivio/Piegatubi/"


def test_remote_script_never_contains_password_and_exports_env():
    script = build_remote_rsync_script(
        "/volume1/Condivisa/docs/",
        "rsync://backup@10.0.0.2:873/DATI/Condivisa/docs/",
        exclude_lines=["@eaDir", "#recycle"],
        delete_on_dest=True,
        bandwidth_limit_kb=5000,
    )
    assert "IFS= read -r RSYNC_PASSWORD" in script
    assert "export RSYNC_PASSWORD" in script
    assert "__DAPX_PID__$$" in script
    assert "--delete-after" in script
    assert "--bwlimit=5000" in script
    assert "--exclude '@eaDir'" in script
    assert "--partial-dir=.dapx-partial" in script
    assert "--info=progress2" in script
    assert "--out-format='%i %n'" in script
    assert "DAPX_MKPATH" in script
    assert "--mkpath" in script
    # Nessun token %n lasciato come argomento path separato (bug shell-split)
    assert re.search(r"(?<!')%n(?!')", script) is None


def test_remote_script_ensure_dest_only_excludes_all_content():
    script = build_remote_rsync_script(
        "/volume1/FTP_BACKUP/",
        "rsync://backup@10.0.0.2:873/DATI/FTP_BACKUP/",
        exclude_lines=[],
        delete_on_dest=True,
        bandwidth_limit_kb=1000,
        ensure_dest_only=True,
    )
    assert "--exclude '*'" in script
    assert "--delete-after" not in script
    assert "--bwlimit" not in script


def test_ssh_argv_with_key_uses_batchmode(monkeypatch):
    ep = _src(ssh_key_path="/root/.ssh/id_rsa", password_enc=None)
    argv, env = build_ssh_argv(ep)
    assert argv[0] == "ssh"
    assert "-i" in argv and "/root/.ssh/id_rsa" in argv
    assert "BatchMode=yes" in " ".join(argv)
    assert env == {}
    assert argv[-1] == "admin@10.0.0.1"


def test_ssh_argv_with_password_uses_sshpass_env(monkeypatch):
    monkeypatch.setattr(
        "services.nas_sync.engine_direct_rsync.decrypt_password", lambda _: "segreta"
    )
    argv, env = build_ssh_argv(_src())
    assert argv[0] == "sshpass"
    assert argv[1] == "-e"
    assert "segreta" not in " ".join(argv)
    assert env == {"SSHPASS": "segreta"}


def test_parse_progress2_line():
    ev = parse_rsync_line("  1,234,567  12%  3.21MB/s    0:01:23 (xfr#5, to-chk=100/500)")
    assert ev.bytes_done == 1234567
    assert ev.percent == 12
    assert ev.speed == "3.21MB/s"
    assert ev.eta_seconds == 83
    assert ev.phase == "copying"


def test_parse_itemize_new_file():
    ev = parse_rsync_line(">f+++++++++ docs/report.pdf")
    assert ev.files_new == 1
    assert ev.last_file == "docs/report.pdf"


def test_parse_itemize_updated_file():
    ev = parse_rsync_line(">f.st...... docs/old.xlsx")
    assert ev.files_replaced == 1


def test_parse_itemize_directory_ignored():
    assert parse_rsync_line("cd+++++++++ docs/") is None


def test_parse_deleting():
    ev = parse_rsync_line("*deleting   docs/gone.txt")
    assert ev.files_deleted == 1
    assert ev.last_file == "docs/gone.txt"


def test_parse_garbage_returns_none():
    assert parse_rsync_line("sending incremental file list") is None


def test_warning_exits():
    assert 23 in RSYNC_WARNING_EXITS and 24 in RSYNC_WARNING_EXITS
