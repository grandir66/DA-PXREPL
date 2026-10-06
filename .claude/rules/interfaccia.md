---
paths:
  - "frontend/src/**"
  - "frontend/*.ts"
  - "frontend/*.json"
  - "frontend/index.html"
---
# Interfaccia utente e frontend

> Estratto **parola per parola** da `CLAUDE.md` il 2026-10-01: si carica da solo quando si tocca quest'area. Le regole valgono come prima. Versione intera in git fino a `5653138`.

## Interfaccia Utente

### Coerenza grafica (OBBLIGATORIA)
Ogni progetto ha già un proprio linguaggio visivo: **studiarlo prima di disegnare nuove schermate**.

1. **Ispeziona** i template/componenti esistenti per identificare: palette colori, tipografia, spacing, componenti base (bottoni, badge, card, tabelle, form, modali, alert, tab).
2. **Riusa** classi CSS, componenti condivisi e layout esistenti — non introdurre stili ad-hoc.
3. **Per modifiche significative** all'interfaccia di un modulo: prima di scrivere codice, descrivere all'utente **oggetto per oggetto** (header, tabella, filtri, form, modali, badge…) quale componente esistente verrà usato e come, attendendo conferma.
4. **Se manca un componente**, proporre prima di aggiungerlo al sistema condiviso (design system / libreria componenti / file CSS comune), poi usarlo nel modulo.
5. **Tabelle dati con molte righe**: header sticky, paginazione e/o virtual scrolling, evitare layout shift.

### Frontend
- Preferire i pattern del framework in uso (composition API in Vue, hooks in React, ecc.).
- AJAX/fetch centralizzati in service layer.
- WebSocket per aggiornamenti real-time se il framework lo supporta nativamente.
- **Mai** lasciare `console.log()` in produzione.
