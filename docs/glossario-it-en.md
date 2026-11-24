# Glossario italiano/inglese dell'interfaccia

Approvato da Riccardo il 24/11/2026 («Glossario ok, continua»). Vale per i file
`frontend/src/locales/{it,en}.json`, per i messaggi del backend e per le e-mail.
La colonna «italiano» è la forma unica anche in italiano: le varianti a destra si
tolgono quando si traduce la vista che le contiene. Una voce nuova si aggiunge qui
prima di usarla.

| Italiano (forma unica) | Inglese | Varianti da togliere |
|---|---|---|
| replica | replication (l'attività), replica (la VM copiata) | |
| job | job | |
| esecuzione | run | «run», «corsa», «Ultimo run», «Ultima run» |
| ultima / prossima esecuzione | last run / next run | |
| pianificazione | schedule | «schedule», «schedulare» |
| conservazione | retention | «retention» |
| ripristino | restore | «restore» |
| origine | source | «sorgente» |
| destinazione | destination | «target» |
| nodo | node | |
| snapshot | snapshot | |
| storage | storage | |
| datastore | datastore | |
| endpoint | endpoint | |
| attiva / disattiva (un job) | enable / disable | «Disattiva schedule» |
| avvia / ferma | start / stop | |
| avvio automatico | start at boot | «Start on Boot» |
| Riallinea identità | Realign identity | |
| Da riallineare | Needs realignment | |
| Ritorna all'originale | Fail back to original | |
| Prepara / Completa (il ritorno) | Prepare / Complete | |
| Recupera all'avvio le esecuzioni saltate | Catch up missed runs at startup | «corse saltate» |
| Syslog remoto | Remote syslog | |
| collettore | collector | |
| riuscito / fallito | succeeded / failed | «Success», «Successo», «OK» |
| in corso | running | «In lavorazione», «in esecuzione» |
| Impostazioni | Settings | |
| Registri di sistema | System logs | «System Logs» |
| Macchine virtuali | Virtual machines | «Virtual Machines» |
| Backup della configurazione | Configuration backup | «Backup config» |

## Regole di scrittura

- Inglese: maiuscola solo alla prima parola di etichette e titoli («Virtual machines»,
  non «Virtual Machines»); i nomi di prodotto restano come sono (Proxmox, PBS, Sanoid).
- Nel menu laterale la voce è «Backup configurazione» (senza «della») perché la colonna
  è stretta.
- Le chiavi dei file di lingua sono in italiano, raggruppate per vista o per pezzo
  condiviso (`menu.*`, `login.*`, `comune.*`, `pianificazione.*`).
- Date e numeri passano da `frontend/src/utils/formato.ts`: italiano `it-IT`, inglese
  `en-GB` (giorno prima del mese, 24 ore).
