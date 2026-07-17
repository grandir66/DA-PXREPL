"""Browse cartelle Windows/SMB via smbclient."""

from __future__ import annotations

import asyncio
import logging
import re
import shlex
from typing import Optional

from services.file_replication.path_utils import is_excluded_name, sanitize_path
from services.file_replication_schemas import BrowseEntryOut, ConnectionTestResult

logger = logging.getLogger(__name__)

DEFAULT_EXCLUDE_PRESETS = ["nas_snapshots", "system_files", "windows_vss"]

_SHARE_LINE = re.compile(r"^\s*([A-Za-z0-9_\-$]+)\s+(Disk|IPC)", re.MULTILINE)
_DIR_LINE = re.compile(r"^\s+(.+?)\s+(D|\s)\s+(\d+)\s", re.MULTILINE)


class SmbBrowser:
    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        domain: Optional[str] = None,
        base_path: Optional[str] = None,
    ):
        self.host = host
        self.port = port or 445
        self.username = username
        self.password = password
        self.domain = domain
        self.base_path = (base_path or "").strip("\\/")

    def _auth_args(self) -> list[str]:
        user = self.username
        if self.domain:
            user = f"{self.domain}/{self.username}"
        return ["-U", f"{user}%{self.password}"]

    async def _run_smbclient(self, args: list[str]) -> tuple[int, str, str]:
        cmd = ["smbclient", "-L", f"//{self.host}", *self._auth_args(), "-p", str(self.port), *args]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_b, stderr_b = await proc.communicate()
        return proc.returncode or 0, stdout_b.decode(errors="replace"), stderr_b.decode(errors="replace")

    async def test_connection(self) -> ConnectionTestResult:
        try:
            code, out, err = await self._run_smbclient([])
            if code == 0:
                shares = _SHARE_LINE.findall(out)
                return ConnectionTestResult(
                    success=True,
                    message=f"Connessione SMB OK — {len(shares)} share",
                    details={"share_count": len(shares)},
                )
            return ConnectionTestResult(success=False, message=err or out or "SMB fallito")
        except FileNotFoundError:
            return ConnectionTestResult(
                success=False,
                message="smbclient non installato sul host dapx",
            )
        except Exception as exc:
            logger.warning("SMB test failed: %s", exc)
            return ConnectionTestResult(success=False, message=str(exc))

    async def list_children(
        self,
        path: str,
        exclude_presets: Optional[list[str]] = None,
    ) -> list[BrowseEntryOut]:
        presets = exclude_presets or DEFAULT_EXCLUDE_PRESETS
        path = sanitize_path(path)

        if path in ("/", ""):
            code, out, err = await self._run_smbclient([])
            if code != 0:
                raise RuntimeError(err or out or "Impossibile elencare share SMB")
            entries: list[BrowseEntryOut] = []
            for name, _kind in _SHARE_LINE.findall(out):
                if name.endswith("$"):
                    continue
                share_path = f"/{name}"
                excluded = is_excluded_name(name, presets)
                entries.append(
                    BrowseEntryOut(
                        name=name,
                        path=share_path,
                        is_dir=True,
                        is_excluded=excluded,
                        selectable=not excluded,
                    )
                )
            return sorted(entries, key=lambda e: e.name.lower())

        parts = [p for p in path.strip("/").split("/") if p]
        if not parts:
            return await self.list_children("/", exclude_presets)
        share = parts[0]
        subpath = "/".join(parts[1:]) if len(parts) > 1 else ""

        smb_cmds = "cd " + (shlex.quote(subpath) if subpath else ".") + "; ls"
        cmd = [
            "//{}/{}".format(self.host, share),
            *self._auth_args(),
            "-p",
            str(self.port),
            "-c",
            smb_cmds,
        ]
        proc = await asyncio.create_subprocess_exec(
            "smbclient",
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_b, stderr_b = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(stderr_b.decode(errors="replace") or "ls SMB fallito")

        out = stdout_b.decode(errors="replace")
        entries = []
        for line in out.splitlines():
            line = line.rstrip()
            if not line or line.startswith("NT_STATUS") or "blocks available" in line:
                continue
            if line.startswith(".") and (line.strip() in (".", "..")):
                continue
            is_dir = line.strip().endswith(" D") or "  D  " in line
            name = line.split()[0] if line.split() else ""
            if not name or name in (".", ".."):
                continue
            item_path = f"/{share}" + (f"/{subpath}" if subpath else "") + f"/{name}"
            item_path = sanitize_path(item_path.replace("//", "/"))
            excluded = is_excluded_name(name, presets)
            entries.append(
                BrowseEntryOut(
                    name=name,
                    is_dir=is_dir or line.strip().endswith(" D"),
                    path=item_path,
                    is_excluded=excluded,
                    selectable=not excluded,
                )
            )
        return sorted(entries, key=lambda e: (not e.is_dir, e.name.lower()))
