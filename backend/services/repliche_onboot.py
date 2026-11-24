"""Guardia: una replica registrata non deve avere l'avvio automatico (3.25.0).

Funzioni pure, provate da tests/test_repliche_onboot.py. Conta solo la sezione
principale del `.conf`: le sezioni `[snapshot]` portano l'onboot di allora.
Una replica con «DR ATTIVATO» sta al posto della produzione e non si segnala.
"""
import re
from typing import Iterable, List

_AWK = (
    "awk '/^\\[/{exit} /^onboot: *1/{o=1} /DR ATTIVATO/{d=1} "
    "END{if(o&&!d) print FILENAME}'"
)


def comando_onboot(vmids: Iterable[int]) -> str:
    ids = " ".join(str(int(v)) for v in sorted(set(vmids)))
    return (
        f"for i in {ids}; do for f in /etc/pve/qemu-server/$i.conf /etc/pve/lxc/$i.conf; do "
        f"[ -f $f ] && {_AWK} $f; done; done; true"
    )


def repliche_con_onboot(stdout: str) -> List[int]:
    out = []
    for riga in (stdout or "").splitlines():
        m = re.search(r"/(\d+)\.conf\s*$", riga.strip())
        if m:
            out.append(int(m.group(1)))
    return sorted(set(out))
