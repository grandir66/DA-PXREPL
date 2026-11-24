---
badge: Vivo
tono: ok
famiglia: 01-nucleo
ordine: 100
stato: manutenzione
prossimo: DTS alla 3.27.0 col sì di Riccardo; rifare la replica 103 → 9103 del 3CX; accendere il syslog verso Wazuh
applicazione: repl
---
cruscotto backup/replica Proxmox (ZFS Sanoid/Syncoid, PBS)

Otto tipologie di attività sotto un solo cruscotto: replica VM, snapshot,
replica dati, sync NAS, backup e recovery PBS, backup host, migrazione live.

**3.27.0**: «Ritorno all'originale», che riporta la produzione dalla replica
accesa alla VM originale con nome e impostazioni suoi (syncoid a ruoli
invertiti, due tempi, disco vecchio messo da parte). In esercizio a Domarc e a DTS.

**Trappola corrente**: il rilascio si fa solo da `main` e finisce alla
release di GitHub (`.claude/rules/rilascio.md`): l'8 settembre una versione
nata su un ramo 35 commit indietro non arrivò mai su `main`.
