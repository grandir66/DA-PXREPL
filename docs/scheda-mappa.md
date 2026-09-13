---
badge: Vivo
tono: ok
famiglia: 01-nucleo
ordine: 100
stato: manutenzione
prossimo: domattina leggere il riepilogo delle 8:00 di DTS e Domarc e i backup config della notte; decidere che fare di DTS2-PBS 192.168.16.99 (porta 22 muta)
---
cruscotto backup/replica Proxmox (ZFS Sanoid/Syncoid, PBS)

Otto tipologie di attività sotto un solo cruscotto: replica VM, snapshot,
replica dati, sync NAS, backup e recovery PBS, backup host, migrazione live.

**Entrambe le appliance (DTS e Domarc) in esercizio con la 3.21.3** (13 settembre): fine della tempesta SSH
verso il nodo di destinazione (quarantena per host, `test -f` fallito non
vale «VM assente»), chiave dell'orchestratore che non sparisce più dal nodo
(`mv` sopra il link `authorized_keys`), backup config host con cron veri,
alert «in ritardo» leggibile per i job non giornalieri.

**Trappola corrente**: il repo ha **tre worktree**, e l'8 settembre ci si è
messi a lavorare per sbaglio su un ramo 35 commit indietro rispetto a `main`.
Prima di toccare il codice: `git log --oneline -1` e `version.json`.
