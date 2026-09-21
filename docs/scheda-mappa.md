---
badge: Vivo
tono: ok
famiglia: 01-nucleo
ordine: 100
stato: manutenzione
prossimo: installare la 3.23.0 su dts-repl (sessione DTS): uuid delle repliche, poi migrare una VM di prova e vedere il job seguirla
---
cruscotto backup/replica Proxmox (ZFS Sanoid/Syncoid, PBS)

Otto tipologie di attività sotto un solo cruscotto: replica VM, snapshot,
replica dati, sync NAS, backup e recovery PBS, backup host, migrazione live.

**3.23.0 (22 settembre), da installare**: il job segue la VM nel cluster
(`docs/il-job-segue-la-vm.md`); dalla 3.22.0 la replica non porta più l'uuid
SMBIOS della sorgente — Veeam escludeva dal backup 12 VM di DTS — con
«Attiva DR» (`docs/identita-replica.md`). Le appliance sono alla 3.21.3.

**Trappola corrente**: il repo ha **tre worktree** (l'8 settembre si è
lavorato su un ramo 35 commit indietro). Prima di toccare il codice:
`git branch --show-current` e `version.json`.
