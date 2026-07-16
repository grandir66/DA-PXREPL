#!/usr/bin/env python3
"""Pulizia DB operativa: job_log orfani e stati running bloccati."""
import sqlite3
import sys
from pathlib import Path

DB = Path("/var/lib/dapx-unified/dapx.db")


def main() -> int:
    if not DB.exists():
        print(f"DB non trovato: {DB}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    orphan_logs = cur.execute(
        """
        SELECT jl.id, jl.job_id, jl.status
        FROM job_logs jl
        LEFT JOIN sync_jobs sj ON sj.id = jl.job_id
        WHERE jl.job_id IS NOT NULL AND sj.id IS NULL
        """
    ).fetchall()
    if orphan_logs:
        print(f"Rimuovo {len(orphan_logs)} job_log orfani: {orphan_logs}")
        cur.execute(
            """
            DELETE FROM job_logs
            WHERE job_id IS NOT NULL
              AND job_id NOT IN (SELECT id FROM sync_jobs)
            """
        )
    else:
        print("Nessun job_log orfano.")

    stale_running = cur.execute(
        "SELECT id, job_id FROM job_logs WHERE status = 'running'"
    ).fetchall()
    if stale_running:
        print(f"Segno failed {len(stale_running)} job_log running: {stale_running}")
        cur.execute(
            """
            UPDATE job_logs
            SET status = 'failed',
                message = COALESCE(message, '') || ' [reset manutenzione]'
            WHERE status = 'running'
            """
        )

    blocked = cur.execute(
        "SELECT id, name FROM sync_jobs WHERE last_status = 'running'"
    ).fetchall()
    for jid, name in blocked:
        print(f"Reset sync_job {jid} ({name}) running -> failed")
        cur.execute(
            """
            UPDATE sync_jobs
            SET last_status = 'failed', current_status = 'idle'
            WHERE id = ?
            """,
            (jid,),
        )

    conn.commit()
    conn.close()
    print("Manutenzione DB completata.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
