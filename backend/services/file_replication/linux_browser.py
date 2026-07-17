"""Browse cartelle Linux via SSH."""

from __future__ import annotations

import asyncio
import logging
import shlex
from typing import Optional

import paramiko

from services.file_replication.path_utils import is_excluded_name, sanitize_path
from services.file_replication_schemas import BrowseEntryOut, ConnectionTestResult
from services.ssh_service import SSHResult, ssh_service

logger = logging.getLogger(__name__)

DEFAULT_EXCLUDE_PRESETS = ["nas_snapshots", "system_files"]


class LinuxSshBrowser:
    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        ssh_key_path: Optional[str] = None,
    ):
        self.host = host
        self.port = port or 22
        self.username = username
        self.password = password
        self.ssh_key_path = ssh_key_path

    async def _execute(self, command: str) -> SSHResult:
        if self.ssh_key_path:
            return await ssh_service.execute(
                self.host,
                command,
                port=self.port,
                username=self.username,
                key_path=self.ssh_key_path,
            )

        def _run_password():
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            try:
                client.connect(
                    self.host,
                    port=self.port,
                    username=self.username,
                    password=self.password or None,
                    timeout=30,
                    allow_agent=False,
                    look_for_keys=False,
                )
                _stdin, stdout, stderr = client.exec_command(command, timeout=120)
                exit_code = stdout.channel.recv_exit_status()
                return SSHResult(
                    success=exit_code == 0,
                    stdout=stdout.read().decode("utf-8", errors="replace"),
                    stderr=stderr.read().decode("utf-8", errors="replace"),
                    exit_code=exit_code,
                )
            except Exception as exc:
                return SSHResult(success=False, stdout="", stderr=str(exc), exit_code=-1)
            finally:
                client.close()

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _run_password)

    async def test_connection(self) -> ConnectionTestResult:
        try:
            result = await self._execute("echo ok")
            if result.success and "ok" in result.stdout:
                return ConnectionTestResult(success=True, message="Connessione SSH OK")
            return ConnectionTestResult(
                success=False,
                message=result.stderr or "Test SSH fallito",
            )
        except Exception as exc:
            logger.warning("Linux SSH test failed: %s", exc)
            return ConnectionTestResult(success=False, message=str(exc))

    async def list_children(
        self,
        path: str,
        exclude_presets: Optional[list[str]] = None,
    ) -> list[BrowseEntryOut]:
        presets = exclude_presets or DEFAULT_EXCLUDE_PRESETS
        path = sanitize_path(path)
        quoted = shlex.quote(path)
        cmd = (
            f"find {quoted} -mindepth 1 -maxdepth 1 -printf '%y\\t%f\\t%s\\n' 2>/dev/null "
            f"|| ls -1 {quoted} 2>/dev/null"
        )
        result = await self._execute(cmd)
        if not result.success:
            raise RuntimeError(result.stderr or "Impossibile elencare directory")

        entries: list[BrowseEntryOut] = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            if "\t" in line:
                kind, name, size_str = (line.split("\t") + ["0", "0"])[:3]
                is_dir = kind == "d"
                try:
                    size = int(size_str) if not is_dir else None
                except ValueError:
                    size = None
            else:
                name = line
                is_dir = True
                size = None
            if name in (".", ".."):
                continue
            item_path = f"{path.rstrip('/')}/{name}"
            excluded = is_excluded_name(name, presets)
            entries.append(
                BrowseEntryOut(
                    name=name,
                    path=item_path,
                    is_dir=is_dir,
                    is_excluded=excluded,
                    selectable=not excluded,
                    size=size,
                )
            )
        return sorted(entries, key=lambda e: (not e.is_dir, e.name.lower()))
