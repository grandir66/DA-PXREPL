#!/usr/bin/env python3
"""Migrate alert() calls to toast in Vue SFC files under frontend/src/views."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEWS = ROOT / "frontend" / "src" / "views"


def toast_import_path(file_path: Path) -> str:
    rel = file_path.relative_to(ROOT / "frontend" / "src")
    depth = len(rel.parts) - 1
    return ("../" * depth) + "stores/toast"


def migrate_file(fp: Path) -> bool:
    content = fp.read_text(encoding="utf-8")
    if "alert(" not in content:
        return False

    original = content

    if "useToast" not in content and "<script setup" in content:
        imp = toast_import_path(fp)
        import_stmt = f"import {{ useToast, errorMessage }} from '{imp}';\n"
        content = re.sub(
            r"(<script setup lang=\"ts\">\n)",
            r"\1" + import_stmt,
            content,
            count=1,
        )
        if "const toast = useToast()" not in content:
            content = re.sub(
                r"(<script setup lang=\"ts\">\n(?:import[^\n]+\n)+)",
                lambda m: m.group(0) + "\nconst toast = useToast()\n",
                content,
                count=1,
            )

    subs = [
        (r"alert\('Errore azione: '\s*\+\s*e\)", "toast.error('Errore azione', errorMessage(e))"),
        (r"alert\('Errore restore: '\s*\+\s*e\)", "toast.error('Errore restore', errorMessage(e))"),
        (r"alert\('❌ Errore durante lo snapshot: '\s*\+\s*e\)", "toast.error('Errore snapshot', errorMessage(e))"),
        (r"alert\('Errore salvataggio nodo: '\s*\+\s*errorMsg\)", "toast.error('Errore salvataggio nodo', errorMsg)"),
        (r'alert\("Errore creazione: "\s*\+\s*\(e\.response\?\.data\?\.detail \|\| e\.message\)\)',
         "toast.error('Errore creazione', errorMessage(e))"),
        (r'alert\("Errore esecuzione: "\s*\+\s*\(e\.response\?\.data\?\.detail \|\| e\.message\)\)',
         "toast.error('Errore esecuzione', errorMessage(e))"),
        (r'alert\("Errore backup manuale: "\s*\+\s*\(e\.response\?\.data\?\.detail \|\| e\.message\)\)',
         "toast.error('Errore backup manuale', errorMessage(e))"),
        (r'alert\("Errore eliminazione: "\s*\+\s*\(e\.response\?\.data\?\.detail \|\| e\.message\)\)',
         "toast.error('Errore eliminazione', errorMessage(e))"),
        (r'alert\("Errore download: "\s*\+\s*\(e\.response\?\.data\?\.detail \|\| e\.message\)\)',
         "toast.error('Errore download', errorMessage(e))"),
        (r"alert\('Errore: '\s*\+\s*e\)", "toast.error('Errore', errorMessage(e))"),
        (r'alert\("Errore: "\s*\+\s*e\)', 'toast.error("Errore", errorMessage(e))'),
        (r"alert\('Errore: '\s*\+\s*\(e\.response\?\.data\?\.detail \|\| e\.message\)\)",
         "toast.error('Errore', errorMessage(e))"),
        (r'alert\("Errore: "\s*\+\s*\(e\.response\?\.data\?\.detail \|\| e\.message\)\)',
         'toast.error("Errore", errorMessage(e))'),
        (r"alert\('Errore nel salvataggio della configurazione'\)",
         "toast.error('Errore nel salvataggio della configurazione')"),
        (r"alert\('Error during bulk unlock'\)", "toast.error('Errore sblocco massivo')"),
        (r"alert\('Error removing resource from HA'\)", "toast.error('Errore rimozione risorsa HA')"),
        (r"alert\('Error removing HA group'\)", "toast.error('Errore rimozione gruppo HA')"),
        (r"alert\('Please enter a group name'\)", "toast.warning('Inserire un nome gruppo')"),
        (r"alert\('Failed to create HA group'\)", "toast.error('Creazione gruppo HA fallita')"),
        (r"alert\('Error removing node from cluster'\)", "toast.error('Errore rimozione nodo dal cluster')"),
        (r"alert\('Error cleaning node references'\)", "toast.error('Errore pulizia riferimenti nodo')"),
        (r"alert\('Error adding node to cluster'\)", "toast.error('Errore aggiunta nodo al cluster')"),
        (r'alert\("Failed to save cluster: "\s*\+\s*msg\)', 'toast.error("Salvataggio cluster fallito", msg)'),
        (r"alert\('Rollback avviato\.'\)", "toast.success('Rollback avviato')"),
        (r"alert\('Rollback ZFS eseguito\.'\)", "toast.success('Rollback ZFS eseguito')"),
        (r"alert\('Snapshot eliminato\.'\)", "toast.success('Snapshot eliminato')"),
        (r"alert\('Configurazione salvata!'\)", "toast.success('Configurazione salvata')"),
        (r"alert\('Configurazione salvata!'\)", "toast.success('Configurazione salvata')"),
        (r"alert\('Restore avviato!'\)", "toast.success('Restore avviato')"),
        (r"alert\('✅ Snapshot Manuale eseguito! Verifica la lista ZFS Snapshots qui sopra\.'\)",
         "toast.success('Snapshot manuale eseguito', 'Verifica la lista ZFS Snapshots')"),
        (r'alert\("Nome e Hostname richiesti"\)', 'toast.warning("Nome e Hostname richiesti")'),
        (r'alert\("Devi specificare un Nuovo VMID per il clone\."\)',
         'toast.warning("Devi specificare un Nuovo VMID per il clone.")'),
        (r'alert\("Job creato con successo"\)', 'toast.success("Job creato con successo")'),
        (r'alert\("Errore eliminazione"\)', 'toast.error("Errore eliminazione")'),
        (r"alert\('Impostazioni salvate'\)", "toast.success('Impostazioni salvate')"),
        (r"alert\('Errore salvataggio'\)", "toast.error('Errore salvataggio')"),
        (r"alert\('Impostazioni Auth salvate'\)", "toast.success('Impostazioni Auth salvate')"),
        (r"alert\(`Test \$\{channel\} inviato`\)", "toast.success(`Test ${channel} inviato`)"),
        (r"alert\('Errore test: '\s*\+\s*\(e\.response\?\.data\?\.detail \|\| e\.message\)\)",
         "toast.error('Errore test', errorMessage(e))"),
        (r'alert\("Riepilogo giornaliero inviato ai canali configurati\."\)',
         'toast.success("Riepilogo giornaliero inviato")'),
        (r'alert\("Errore invio riepilogo: "\s*\+\s*\(e\.response\?\.data\?\.detail \|\| e\.message\)\)',
         'toast.error("Errore invio riepilogo", errorMessage(e))'),
        (r'alert\("Le nuove password non coincidono"\)', 'toast.warning("Le nuove password non coincidono")'),
        (r'alert\("Password aggiornata con successo"\)', 'toast.success("Password aggiornata")'),
        (r"alert\('Errore avvio job'\)", "toast.error('Errore avvio job')"),
        (r"alert\('Errore eliminazione job'\)", "toast.error('Errore eliminazione job')"),
        (r"alert\('Errore modifica stato job'\)", "toast.error('Errore modifica stato job')"),
        (r"alert\('Errore avvio migrazione'\)", "toast.error('Errore avvio migrazione')"),
        (r"alert\('Replica completata con successo'\)", "toast.success('Replica completata')"),
        (r"alert\('Errore durante la replica: '\s*\+\s*\(e\.response\?\.data\?\.detail \|\| e\.message\)\)",
         "toast.error('Errore replica', errorMessage(e))"),
        (r"alert\('Errore eliminazione job'\)", "toast.error('Errore eliminazione job')"),
        (r"alert\('Errore durante la creazione del backup'\)",
         "toast.error('Errore creazione backup')"),
        (r"alert\('Errore durante il download del backup'\)",
         "toast.error('Errore download backup')"),
        (r"alert\('Errore durante l\\'eliminazione'\)",
         "toast.error('Errore eliminazione backup')"),
        (r'alert\(`Backup creato: \$\{res\.data\.filename\}\\nDimensione: \$\{formatSize\(res\.data\.size\)\}`\)',
         'toast.success("Backup creato", `${res.data.filename} — ${formatSize(res.data.size)}`)'),
        (r'alert\("Configurazione salvata\. Riavvio richiesto per applicare le modifiche\."\)',
         'toast.success("Configurazione salvata", "Riavvio richiesto per applicare le modifiche")'),
        (r'alert\("Errore salvataggio: "\s*\+\s*\(e\.response\?\.data\?\.detail \|\| e\.message\)\)',
         'toast.error("Errore salvataggio", errorMessage(e))'),
        (r'alert\("Certificato generato con successo!"\)', 'toast.success("Certificato generato")'),
        (r'alert\("Errore generazione: "\s*\+\s*\(e\.response\?\.data\?\.detail \|\| e\.message\)\)',
         'toast.error("Errore generazione", errorMessage(e))'),
        (r'alert\("Inserire certificato e chiave privata"\)', 'toast.warning("Inserire certificato e chiave privata")'),
        (r'alert\("Certificato caricato con successo!"\)', 'toast.success("Certificato caricato")'),
        (r'alert\("Errore caricamento: "\s*\+\s*\(e\.response\?\.data\?\.detail \|\| e\.message\)\)',
         'toast.error("Errore caricamento", errorMessage(e))'),
        (r'alert\("Certificato eliminato"\)', 'toast.success("Certificato eliminato")'),
        (r'alert\("Errore eliminazione"\)', 'toast.error("Errore eliminazione")'),
        (r"alert\('Errore creazione utente: '\s*\+\s*\(e\.response\?\.data\?\.detail \|\| e\.message\)\)",
         "toast.error('Errore creazione utente', errorMessage(e))"),
        (r"alert\('Errore eliminazione'\)", "toast.error('Errore eliminazione')"),
        (r"alert\('Compila tutti i campi obbligatori'\)", "toast.warning('Compila tutti i campi obbligatori')"),
        (r"alert\('Errore creazione job: '\s*\+\s*\(e\.response\?\.data\?\.detail \|\| e\.message\)\)",
         "toast.error('Errore creazione job', errorMessage(e))"),
        (r"alert\('Errore salvataggio modifiche'\)", "toast.error('Errore salvataggio modifiche')"),
        (r"alert\('Node added!'\)", "toast.success('Nodo aggiunto')"),
        (r"alert\('Removed\.'\)", "toast.success('Rimosso')"),
        (r"alert\('Cleaned\.'\)", "toast.success('Pulizia completata')"),
        (r"alert\('Error: '\s*\+\s*d\.message\)", "toast.error('Errore', d.message)"),
        (r"alert\('Error: '\s*\+\s*e\)", "toast.error('Errore', errorMessage(e))"),
        (r"alert\('Error: '\s*\+\s*data\.detail\)", "toast.error('Errore', data.detail)"),
        (r"alert\(`Error: \$\{data\.message\}`\)", "toast.error('Errore', data.message)"),
        (r"alert\('Configurazione salvata!'\)", "toast.success('Configurazione salvata')"),
        (r"alert\(data\.message \|\| 'Resource removed'\)",
         "toast.success(data.message || 'Risorsa rimossa')"),
        (r"alert\(data\.message \|\| 'Group removed'\)",
         "toast.success(data.message || 'Gruppo rimosso')"),
        (r"alert\(data\.message \|\| 'HA Group created'\)",
         "toast.success(data.message || 'Gruppo HA creato')"),
        (r"alert\(`Unlocked \$\{totalSuccess\} guests\$\{totalFailed > 0 \? `, \$\{totalFailed\} failed` : ''\}`\)",
         "toast.success('Sblocco completato', `Sbloccati ${totalSuccess} guest${totalFailed > 0 ? `, ${totalFailed} falliti` : ''}`)"),
        (r"alert\(`Failed to unlock \$\{totalFailed\} guests`\)",
         "toast.error('Sblocco fallito', `${totalFailed} guest non sbloccati`)"),
        (r"alert\(`Process complete\. Added \$\{successCount\} guests\.`\)",
         "toast.success('Operazione completata', `Aggiunti ${successCount} guest`)"),
        (r"alert\(`Node \$\{nodeName\} removed successfully`\)",
         "toast.success('Nodo rimosso', nodeName)"),
        (r"alert\(`Cleanup complete for \$\{nodeName\}`\)",
         "toast.success('Pulizia completata', nodeName)"),
        (r"alert\(`Node \$\{newNodeIP\.value\} added successfully!`\)",
         "toast.success('Nodo aggiunto', newNodeIP.value)"),
        (r"alert\(`Clone ZFS avviato per VM \$\{newId\}\. La nuova VM apparirà nella lista\.`\)",
         "toast.success('Clone ZFS avviato', `VM ${newId} in creazione`)"),
        (r"alert\(`Backup \$\{job\.name\} avviato e completato!`\)",
         "toast.success('Backup completato', job.name)"),
        (r"alert\(\"Backup manuale completato!\"\)", "toast.success('Backup manuale completato')"),
        (r"alert\(\"Seleziona un nodo\"\)", "toast.warning('Seleziona un nodo')"),
        (r"alert\('Errore: '\s*\+\s*\(e\.response\?\.data\?\.detail \|\| e\.message\)\)",
         "toast.error('Errore', errorMessage(e))"),
    ]

    for pattern, repl in subs:
        content = re.sub(pattern, repl, content)

    if content != original:
        fp.write_text(content, encoding="utf-8")
        return True
    return False


def main() -> int:
    changed = []
    for fp in sorted(VIEWS.rglob("*.vue")):
        if migrate_file(fp):
            changed.append(fp.relative_to(ROOT))
    print(f"Migrated {len(changed)} files:")
    for p in changed:
        print(f"  - {p}")
    remaining = sum(1 for fp in VIEWS.rglob("*.vue") if "alert(" in fp.read_text())
    print(f"Files still containing alert(): {remaining}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
