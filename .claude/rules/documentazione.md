---
paths:
  - "CHANGELOG.md"
  - "README.md"
  - "docs/**"
  - "scripts/README.md"
---
# CHANGELOG e documentazione

> Estratto **parola per parola** da `CLAUDE.md` il 2026-10-01: si carica da solo quando si tocca quest'area. Le regole valgono come prima. Versione intera in git fino a `5653138`.

## Gestione `CHANGELOG.md`

**REGOLA OBBLIGATORIA**: ogni modifica rilevante deve essere registrata in `CHANGELOG.md` nella root del progetto. Se il file non esiste, crearlo al primo aggiornamento.

### Quando aggiornare
Aggiornare `CHANGELOG.md` **prima del commit** per:
- **Aggiunte**: nuovi moduli, route, componenti, funzionalità, tabelle/colonne DB.
- **Modifiche**: cambiamenti di comportamento, refactoring visibili, aggiornamenti config, modifiche a permessi/menu.
- **Ottimizzazioni**: miglioramenti performance, query più efficienti, riduzione carico, caching.
- **Correzioni**: bug fix, fix di sicurezza, regressioni, correzioni documentazione.

Modifiche puramente cosmetiche (commenti, spazi bianchi) **non** richiedono voce.

### Formato
Standard [Keep a Changelog](https://keepachangelog.com/it/1.1.0/) con date `YYYY-MM-DD`, raggruppamento per data/versione, lingua coerente con il resto della documentazione del progetto.

```markdown
# Changelog

Tutte le modifiche rilevanti a questo progetto vengono documentate in questo file.
Il formato è basato su [Keep a Changelog](https://keepachangelog.com/it/1.1.0/).

## [Unreleased]

### Aggiunte
- Breve descrizione di cosa è stato aggiunto (`path/al/file`).

### Modifiche
- Cosa è cambiato e perché (riferimento a file/route).

### Ottimizzazioni
- Miglioramento performance X (`path/al/file`).

### Correzioni
- Fix bug Z che causava W (`path/al/file`).
```

### Regole di scrittura
1. Una riga per voce, frase completa.
2. **Citare sempre** i file/moduli coinvolti tra parentesi quando utile.
3. **Non citare** credenziali, IP interni sensibili, dettagli non pubblicabili.
4. **Raggruppare** le voci della stessa data sotto un'unica sezione.
5. **Cronologia**: sezioni più recenti in alto.
6. Se la modifica è documentata altrove, aggiungere il link relativo.

### Workflow operativo
A fine task:
1. Aprire `CHANGELOG.md` (o crearlo).
2. Aggiungere voci nelle categorie appropriate sotto la data odierna.
3. Includere `CHANGELOG.md` nello stesso commit.

## Documentazione

### Posizione
Adatta alle convenzioni del progetto:

| Tipo | Posizione tipica |
|------|------------------|
| Documentazione tecnica/architetturale | `docs/`, `docs/handbook/`, `docs/architecture/` |
| Procedure operative (deploy, sync, rollback) | `docs/materiale/`, `docs/operations/`, `runbooks/` |
| Manuale utente | `docs/manuale_utente/`, `docs/user/` |
| Indice / sito statico | `docs/index.md` + generatore (MkDocs, Docusaurus, …) |

### Regole per generazione documenti Markdown
1. **Lingua**: coerente col resto della documentazione del progetto. Termini tecnici (URL, route, tabelle) in forma letterale.
2. **Tono**: chiaro, frasi complete, evitare elenchi telegrafici senza contesto.
3. **Link**: percorsi relativi tra file in `docs/`. URL completi per riferimenti esterni.
4. **Codice**: blocchi fenced con linguaggio (`bash`, `python`, `yaml`, `typescript`). Comandi completi e copiabili.
5. **Segreti**: **mai** password, token, stringhe di connessione reali; usare placeholder o riferimenti ai file di configurazione (senza valori).
6. **Riferimenti al codice**: citare path reali e verificabili nel repo.
7. **Tabelle e titoli**: Markdown standard, gerarchia logica.

### Cosa non fare
- **No** duplicare interi capitoli: meglio un capitolo breve che linka un manuale lungo.
- **No** documentare credenziali o IP/host come "valori fissi" se sono configurabili — riferire la chiave di configurazione.
- **No** suggerire comandi distruttivi (sovrascritture in produzione, `rm -rf`, `git reset --hard` non motivati) senza warning espliciti.

### Checklist nuovo documento
- [ ] Posizione corretta secondo le convenzioni del progetto.
- [ ] Lingua e pubblico definiti (utente finale vs sistemista vs sviluppatore).
- [ ] Link relativi e assenza di segreti.
- [ ] Aggiornamento di indici/`mkdocs.yml`/`sidebar.json` se necessario.
- [ ] Riferimento incrociato dai documenti correlati.
