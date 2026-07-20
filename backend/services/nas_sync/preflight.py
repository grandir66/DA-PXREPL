"""Verifica prerequisiti prima del run: SSH, rsync, porta/modulo destinazione."""

from __future__ import annotations

import asyncio
import os
import shutil

from database import FileEndpoint
from services.file_replication.endpoint_crypto import decrypt_password
from services.nas_sync.capabilities import ENGINE_DIRECT, resolve_engine
from services.nas_sync.engine_direct_rsync import build_ssh_argv


async def _default_ssh_runner(
    argv: list[str],
    env: dict,
    script: str,
    timeout: int,
    stdin_data: str | None = None,
) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *argv,
        script,
        stdin=asyncio.subprocess.PIPE if stdin_data is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env={**os.environ, **env},
    )
    try:
        out_b, _ = await asyncio.wait_for(
            proc.communicate(input=stdin_data.encode() if stdin_data is not None else None),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        proc.kill()
        return 124, "timeout"
    return proc.returncode or 0, out_b.decode(errors="replace")


async def run_preflight(
    job,
    source: FileEndpoint,
    dest: FileEndpoint,
    *,
    ssh_runner=None,
) -> list[dict]:
    checks: list[dict] = []
    runner = ssh_runner or _default_ssh_runner

    try:
        engine, reason = resolve_engine(job.sync_method or "auto", source, dest)
    except ValueError as exc:
        checks.append({"check": "engine", "ok": False, "message": str(exc), "hint": None})
        return checks
    checks.append({"check": "engine", "ok": True, "message": f"Motore: {engine} — {reason}", "hint": None})

    if engine != ENGINE_DIRECT:
        has_rclone = bool(shutil.which("rclone"))
        checks.append({
            "check": "rclone_binary",
            "ok": has_rclone,
            "message": "rclone presente sul server dapx" if has_rclone else "rclone non installato",
            "hint": None if has_rclone else "Installare con: apt install rclone",
        })
        return checks

    argv, env = build_ssh_argv(source)

    code, out = await runner(argv, env, "echo dapx-ok", 20)
    ok = code == 0 and "dapx-ok" in out
    checks.append({
        "check": "ssh_source",
        "ok": ok,
        "message": "SSH sorgente raggiungibile" if ok else f"SSH sorgente fallito: {out.strip()[:200]}",
        "hint": None if ok else "Verifica servizio SSH attivo sul NAS sorgente, porta e credenziali (o installa la chiave dapx).",
    })
    if not ok:
        return checks

    code, out = await runner(argv, env, "rsync --version 2>&1 | head -1", 20)
    ok = code == 0 and "rsync" in out.lower()
    checks.append({
        "check": "rsync_source",
        "ok": ok,
        "message": out.strip()[:120] if ok else "rsync non trovato sulla sorgente",
        "hint": None if ok else "Il NAS sorgente deve avere il binario rsync (di serie su Synology/QNAP).",
    })
    if not ok:
        return checks

    extra = dest.extra_config or {}
    port = int(extra.get("rsync_port") or 873)
    probe = (
        f"(command -v nc >/dev/null && nc -z -w 5 {dest.host} {port} && echo open) "
        f"|| (timeout 5 bash -c 'cat < /dev/null > /dev/tcp/{dest.host}/{port}' && echo open) "
        "|| echo closed"
    )
    code, out = await runner(argv, env, probe, 25)
    ok = "open" in out
    checks.append({
        "check": "dest_port",
        "ok": ok,
        "message": (
            f"Porta rsync {port} della destinazione raggiungibile dalla sorgente"
            if ok else f"Porta {port} non raggiungibile dalla sorgente"
        ),
        "hint": None if ok else "Attiva il servizio rsync sul NAS di destinazione e verifica firewall tra le due NAS.",
    })
    if not ok:
        return checks

    module = str(extra.get("rsync_module") or "")
    user = str(extra.get("rsync_user") or dest.username)
    list_cmd = (
        "IFS= read -r RSYNC_PASSWORD; export RSYNC_PASSWORD; "
        f"rsync --timeout=15 rsync://{user}@{dest.host}:{port}/{module}/ >/dev/null 2>&1 "
        "&& echo module-ok || echo module-fail"
    )
    module_password = decrypt_password(extra.get("rsync_password_enc") or "")
    if ssh_runner is None:
        code, out = await _default_ssh_runner(argv, env, list_cmd, 30, stdin_data=module_password + "\n")
    else:
        code, out = await runner(argv, env, list_cmd, 30)
    ok = "module-ok" in out
    checks.append({
        "check": "dest_module",
        "ok": ok,
        "message": f"Modulo rsync «{module}» accessibile" if ok else f"Accesso al modulo «{module}» fallito",
        "hint": None if ok else "Verifica nome modulo, utente e password del servizio rsync sulla destinazione.",
    })
    return checks
