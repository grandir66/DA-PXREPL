# CONTEXT.md — DA-PXREPL

> Bozza del 20/10/2026 ricavata dalla scheda del censimento (`docs/scheda-mappa.md`)
> nel lavoro `riorg-contesto-agenti`: chi lavora qui la completa sul modello
> `~/Progetti/_template/CONTEXT-TEMPLATE.md` (architettura, trappole, decisioni).

## 1. Cos'è e perché esiste

cruscotto backup/replica Proxmox (ZFS Sanoid/Syncoid, PBS)

Otto tipologie di attività sotto un solo cruscotto: replica VM, snapshot,
replica dati, sync NAS, backup e recovery PBS, backup host, migrazione live.

**3.24.1 rilasciata il 6 ottobre**: destinatario predefinito delle notifiche
`proxmox@domarc.it` (solo dove è vuoto). In esercizio: **DTS alla 3.25.0 dal 24 novembre** (chiavi SSH del cluster sparite il 06/11, vedi TASKS.md); prima 3.24.0 dal 22
settembre (scheduler con battito, il job segue la VM), Domarc alla 3.25.0 dal 24 novembre.

**Verifica del 24/11** (dettaglio in TASKS.md): l'LXC 124 di DTS è rimasto spento dal 12/11 al 24/11 dopo un riavvio di DTS-PX-04, 12 giorni senza repliche e senza avvisi; Domarc è stata portata alla 3.24.5 (rilasciata il 24/11) e il job 6 ripuntato sul firewall nuovo (VM 699): la prima corsa è da leggere. Anche DTS è alla 3.24.5 dal 24/11; le sue repliche, ferme dal 12/11, ripartono ai loro orari: da leggere.

**3.25.0 (24/11)**: syslog remoto (spento, aspetta indirizzo e porta di Wazuh), «Riallinea identità» (usato sulle 9 repliche di Domarc), avviso sulle repliche con avvio automatico. Da progettare a livello completo: il ritorno dalla replica all'originale (3CX di DTS: 9103 accesa su DTS-PX-04, 103 danneggiata su DTS-PX-UP) e il controllo su DA-Zabbix. Anche DTS è alla 3.25.0 dal 24/11.

**Trappola corrente**: il rilascio si fa solo da `main` e finisce alla
release di GitHub (`.claude/rules/rilascio.md`): l'8 settembre una versione
nata su un ramo 35 commit indietro non arrivò mai su `main`.

## 2. Stato — dal censimento, 2026-10-20

- Stato: **manutenzione**.
- Prossimo passo: portare DTS e Domarc alla 3.24.1 dal bottone Aggiorna, poi leggere le corse delle 02:00 e /api/health (battito)
