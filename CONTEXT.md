# CONTEXT.md — DA-PXREPL

> Bozza del 20/10/2026 ricavata dalla scheda del censimento (`docs/scheda-mappa.md`)
> nel lavoro `riorg-contesto-agenti`: chi lavora qui la completa sul modello
> `~/Progetti/_template/CONTEXT-TEMPLATE.md` (architettura, trappole, decisioni).

## 1. Cos'è e perché esiste

cruscotto backup/replica Proxmox (ZFS Sanoid/Syncoid, PBS)

Otto tipologie di attività sotto un solo cruscotto: replica VM, snapshot,
replica dati, sync NAS, backup e recovery PBS, backup host, migrazione live.

**3.24.1 rilasciata il 6 ottobre**: destinatario predefinito delle notifiche
`proxmox@domarc.it` (solo dove è vuoto). In esercizio: **DTS alla 3.26.0 dal 24 novembre** (chiavi SSH del cluster sparite il 06/11, vedi TASKS.md); prima 3.24.0 dal 22
settembre (scheduler con battito, il job segue la VM), Domarc alla 3.26.0 dal 24 novembre.

**Verifica del 24/11** (dettaglio in TASKS.md): l'LXC 124 di DTS è rimasto spento dal 12/11 al 24/11 dopo un riavvio di DTS-PX-04, 12 giorni senza repliche e senza avvisi; Domarc è stata portata alla 3.24.5 (rilasciata il 24/11) e il job 6 ripuntato sul firewall nuovo (VM 699): la prima corsa è da leggere. Anche DTS è alla 3.24.5 dal 24/11; le sue repliche, ferme dal 12/11, ripartono ai loro orari: da leggere.

**3.25.0 (24/11)**: syslog remoto (spento, aspetta indirizzo e porta di Wazuh), «Riallinea identità» (usato sulle 9 repliche di Domarc), avviso sulle repliche con avvio automatico. Il ritorno dalla replica all'originale come funzione del prodotto resta da progettare a livello completo (a DTS è stato fatto a mano il 24/11, vedi sotto). Anche DTS è alla 3.25.0 dal 24/11.

**3.26.0 (24/11)**: recupero all'avvio delle corse saltate (spento di default, acceso sui due siti dal 24/11), cache VM e stato dei nodi, rotazione delle copie in `update.sh`. Domarc e DTS sono alla 3.26.0. Su DA-Zabbix c'è il controllo esterno delle due appliance; in DA-Wazuh il modulo `da-pxrepl` (UDP 5517) è pronto ma non rilasciato, e il syslog è spento.

**3.27.0 (24/11 sera)**: «Ritorno all'originale» (scheda nel dettaglio VM della replica: «Prepara» a replica accesa, «Completa» con fermo breve; disco vecchio rinominato `dapx-vecchio-…` e mai cancellato; se l'originale non parte la replica si riaccende da sola), provato a Domarc su una VM di test; primo pezzo dell'interfaccia in due lingue, selettore nascosto. Domarc è alla 3.27.0, **DTS resta alla 3.26.0** finché Riccardo non dice di aggiornarla. Come funziona: `docs/identita-replica.md`; piano chiuso in `docs/superpowers/plans/2026-11-24-ritorno-all-originale.md`. Trappola: con un ritorno aperto (anche «non riuscito») i job di quella VM restano spenti e la corsa normale non parte; non c'è ancora un «Annulla ritorno».

**Ritorno del 3CX di DTS (24/11, 19:33-19:44)**: la 103 «3CX-V20» è di nuovo in produzione su DTS-PX-UP, ripristinata dal backup da spenta della 9103; la 9103 è spenta su DTS-PX-04 e intatta. Job 2 spento finché non si rifà la replica; disco vecchio da parte in `ZFS/vecchio-3cx-103-disk-0-20261124`. Trappola: la conf della replica porta il bridge della destinazione, al ritorno va rimesso quello dell'originale (dettaglio in TASKS.md).

**Trappola corrente**: il rilascio si fa solo da `main` e finisce alla
release di GitHub (`.claude/rules/rilascio.md`): l'8 settembre una versione
nata su un ramo 35 commit indietro non arrivò mai su `main`.

## 2. Stato — dal censimento, 2026-10-20

- Stato: **manutenzione**.
- Prossimo passo: portare DTS e Domarc alla 3.24.1 dal bottone Aggiorna, poi leggere le corse delle 02:00 e /api/health (battito)
