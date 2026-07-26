# Restyle UI "business-oriented" — dapx-unified

> Design approvato dall'utente il 2026-07-26. Obiettivo: interfaccia più sobria e
> professionale (software di backup, non consumer), **efficace e veloce**, mantenendo
> il tema scuro. Priorità assoluta del progetto: **non rompere nulla**.

## Decisioni approvate

| Tema | Scelta |
|------|--------|
| Ampiezza | **Restyle del design system** (token, tipografia, densità, componenti), tema **dark** mantenuto |
| Tema colore | **Dark** (resta lo stile GitHub attuale, reso più sobrio) |
| Icone | **libreria `lucide-vue-next`** dietro l'API `<Icon>` esistente |

## Stato di partenza (rilevato)

- `frontend/src/style.css` (536 righe): design token dark già presenti (slate + accent blu `#58a6ff`).
- `components/ui/Icon.vue`: sistema SVG stile Heroicons, usato in **19 file**.
- **157 emoji** usate come icone nei `.vue` (concentrate: Cluster 32, ConfigBackup 26, VMs 17, Nodes 14, Settings 11).
- Morbidezza: ~195 `border-radius`, 35 animazioni/keyframes.
- Tipografia: dominata dal monospace (47 dichiarazioni) → aspetto "terminale".

## Principi

1. **Sobrietà**: colori semantici solo come piccoli accenti (badge/testo/barra), mai grandi campiture o emoji colorate.
2. **Densità**: più informazione sopra la piega, tabelle compatte, meno spazi morti.
3. **Coerenza**: un solo sistema di icone (`<Icon>` → lucide), un solo set di token.
4. **Riuso**: si estende l'infrastruttura esistente, non si reinventa.
5. **Reversibilità**: ogni fase è rilasciabile e verificabile da sola; backup + tag prima di iniziare.

## Design del sistema

### Icone — `lucide-vue-next` dietro `<Icon>`
- `Icon.vue` rifatto: API invariata `<Icon name="server" :size="16" />`, backend = mappa `name → componente lucide` (import statici delle sole icone usate → tree-shaking).
- I 19 usi esistenti continuano a funzionare (stessi nomi mappati a lucide).
- Le 157 emoji → `<Icon>` con mappatura semantica (🖥→`server`, 📦→`box`, 🌉→`network`, 💾→`hard-drive`, 📁→`folder`, 📉/📈→`trending-down`/`trending-up`, 🔌→`plug`, …).
- Stroke 1.75, dimensioni via token (16 default, 20 nei titoli).

### Token colore (più sobri)
- Scala neutra slate mantenuta.
- Nuovi token stato: `--status-ok`, `--status-warn`, `--status-err`, `--status-idle` (+ varianti `-dim`/`-fg`).
- Accent blu contenuto sugli elementi grandi, brillante solo su focus/link.

### Tipografia
- Default **sans di sistema** (`-apple-system, "Segoe UI", Roboto, Inter, sans-serif`) per testo/etichette/titoli.
- **Mono solo per dati tecnici**: ID VM/CT, path, IP, dimensioni, output log.
- Scala: 12 / 13 / 14 / 16 / 20 / 24; pesi 400 / 500 / 600; line-height coerenti.

### Densità
- Griglia spaziatura 4px: `--space-1..8` (4/8/12/16/24/32).
- Tabelle: righe compatte (~7px v), font 13px, header sticky, bordi al posto della zebra.
- Padding di pagina/card ridotti.

### Componenti
- **Bottoni**: raggio 6px, no gradienti/ombre marcate; primario (blu pieno) / secondario (ghost) / pericolo (rosso); altezza 28–32px.
- **Badge stato**: `● Online` (pallino + testo) o pill tenue (`bg = colore-dim`, testo `colore-fg`) al posto di 🟢/⚪/✅/❌.
- **Card**: raggio 6–8px, bordo 1px, ombra minima/assente.
- **Raggio globale**: token `--radius-sm` (6px) / `--radius-md` (8px); ridotti dai 10–12px attuali.

### Motion
- Solo animazione funzionale (spinner, progress, indicatore live).
- Rimozione effetti hover decorativi + `@media (prefers-reduced-motion: reduce)`.

## Rollout a fasi (ognuna = rilascio + deploy solo su .199, con checkpoint)

1. **Fondamenta** — `lucide` + `Icon.vue` rifatto (retro-compatibile) + nuovi token in `style.css` (additivi). **Vista pilota** convertita al look nuovo (Cluster.vue) per approvazione del look reale prima del fan-out. Impatto sul resto: nullo.
2. **Icone** — sostituzione delle 157 emoji → `<Icon>` sui restanti file, dai concentrati in giù.
3. **Componenti** — bottoni/badge/card/tabelle uniformati ai nuovi stili/token.
4. **Motion + rifiniture** — riduzione animazioni, `prefers-reduced-motion`, pass finale.

## Vincoli operativi

- Deploy **solo su .199** (dev); **mai .145** (cliente in produzione, resta a 3.17.36).
- Backup DB prima di ogni deploy; backup sorgente fatto (`_backups-ui-restyle/frontend-src-pre-restyle-20260726-120635.tar.gz`) + anchor `v3.20.4`.
- `vue-tsc` a 0 errori e `npm run build` verde prima di ogni rilascio.
- Nessuna regressione grafica sui moduli non ancora convertiti (i vecchi token restano validi finché non migrati).

## Rischi

- Flip del font default (mono→sans) è visibile app-wide: introdotto in Fase 1 ma validato sulla vista pilota prima del resto.
- Bundle: lucide è tree-shakeable; costo ~1KB per icona effettivamente importata.
- Mappatura emoji→icona: alcune emoji sono decorative/ambigue → in dubbio si rimuove invece di forzare un'icona.
