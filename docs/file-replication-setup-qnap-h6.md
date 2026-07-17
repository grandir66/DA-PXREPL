# Setup replica file → QNAP QuTS hero h6.0

Guida operativa per abbinare i job dapx-unified alla protezione immutabile nativa QNAP.

## Prerequisiti

- QNAP con **QuTS hero h6.0.x**
- Host **dapx-unified** con `rsync`, `openssh-client`; per Windows SMB anche `smbclient`
- Rete: porte SSH (22), QNAP API (8080), SMB (445), rsync (873) secondo protocollo scelto

## 1. Share staging (mutabile)

1. Storage Manager → crea share **thin**, compressione ON, **WORM disabilitato**
2. Path es. `/staging/archivio-produzione`
3. Abilita accesso da dapx (rsync over SSH o SMB)

## 2. Endpoint in dapx

| Ruolo | Tipi supportati |
|---|---|
| Sorgente | Synology, QNAP, Linux (SSH), Windows (SMB) |
| Destinazione | Solo QNAP |

Registra credenziali in **Replica file NAS → Endpoint**, poi **Test connessione**.

## 3. Job dapx

1. Wizard: sorgente → cartelle (exclude snapshot automatici) → path staging QNAP → schedule cron
2. Sync consigliato: es. `0 2 * * *` (02:00)

## 4. Snapshot immutabili (QNAP)

Snapshot Manager → share staging → Schedule:

| Impostazione | Valore consigliato |
|---|---|
| Orario | ≥ 1h dopo sync dapx (es. 03:00) |
| Protection policy | Prohibit recycle and delete until expired |
| Retention | Smart Versioning o max N snapshot |
| Only if modified | ON |
| Guaranteed snapshot space | ON |

## 5. Verifica

- Browse mirror live su QNAP (stessa struttura cartelle della sorgente)
- Snapshot Manager → timeline snapshot post-sync
- Log job in dapx: `/api/file-replication/{id}/logs`

## Riferimenti

- [QuTS hero h6.0 What's New](https://docs.qnap.com/operating-system/quts-hero/6.0.x/en-us/what-s-new-in-quts-hero-385FEC8.html)
- Spec design: `docs/superpowers/specs/2026-07-17-nas-worm-replication-design.md`
