---
badge: Vivo
tono: ok
famiglia: 01-nucleo
ordine: 100
stato: manutenzione
prossimo: portare la 3.21.3 anche sull'appliance Domarc (DTS è già a 3.21.3); domattina leggere il riepilogo di DTS e i backup config dei tre nodi (01:00/01:10/01:20)
---
cruscotto backup/replica Proxmox (ZFS Sanoid/Syncoid, PBS)

Otto tipologie di attività sotto un solo cruscotto: replica VM, snapshot,
replica dati, sync NAS, backup e recovery PBS, backup host, migrazione live.

Su **DTS in esercizio la 3.21.3** (13 settembre): fine della tempesta SSH
verso il nodo di destinazione (quarantena per host, `test -f` fallito non
vale «VM assente»), chiave dell'orchestratore che non sparisce più dal nodo
(`mv` sopra il link `authorized_keys`), backup config host con cron veri,
alert «in ritardo» leggibile per i job non giornalieri. L'appliance Domarc
è ferma alla 3.21.0: ci arriva col bottone Aggiorna.

**Trappola corrente**: il repo ha **tre worktree**, e l'8 settembre ci si è
messi a lavorare per sbaglio su un ramo 35 commit indietro rispetto a `main`.
Prima di toccare il codice: `git log --oneline -1` e `version.json`.
