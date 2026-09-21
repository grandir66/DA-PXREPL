---
badge: Vivo
tono: ok
famiglia: 01-nucleo
ordine: 100
stato: manutenzione
prossimo: installare la 3.22.0 su dts-repl (sessione DTS) e verificare che le 12 repliche non vengano ri-registrate con l'uuid vecchio
---
cruscotto backup/replica Proxmox (ZFS Sanoid/Syncoid, PBS)

Otto tipologie di attività sotto un solo cruscotto: replica VM, snapshot,
replica dati, sync NAS, backup e recovery PBS, backup host, migrazione live.

**3.22.0 (21 settembre), da installare**: la replica non porta più l'uuid
SMBIOS della sorgente — Veeam escludeva dal backup 12 VM di produzione di
DTS —, «Attiva DR» e controllo «UUID duplicati» (`docs/identita-replica.md`).
Le appliance (DTS e Domarc) sono alla 3.21.3 del 13 settembre.

**Trappola corrente**: il repo ha **tre worktree** (l'8 settembre si è
lavorato su un ramo 35 commit indietro). Prima di toccare il codice:
`git branch --show-current` e `version.json`.
