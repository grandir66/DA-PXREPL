# Gemini Directives & Project Analysis

## 1. Project Directives (Strict)

### 1.1. Integrity & Isolation
*   **Non-Destructive:** The existing codebase (`dapx-backandrepl`) must remain untouched and functional during development.
*   **Isolation:** All new development must occur strictly within the `DA-REPL` directory.
*   **Parallelism:** The new system runs in parallel; it does not replace the existing system until fully verified.

### 1.2. Architecture & Modularity
*   **Framework:** Use **Vue 3** (aligning with current stack) with **Vite** for the build system.
*   **Component-Based:** The monolithic `index.html` must be decomposed into atomic, reusable components.
*   **State Management:** Use **Pinia** for global state management.
*   **Routing:** Use **Vue Router** to map current "pages" or views to distinct routes.
*   **Type Safety:** Use **TypeScript** to ensure robustness and code quality.

### 1.3. Code Quality & Standards
*   **Linter/Formatter:** ESLint + Prettier must be configured.
*   **API Abstraction:** All backend calls must be encapsulated in a dedicated Service Layer (`/services`), mirroring the backend routers.
*   **Structure:**
    *   `src/components`: UI atoms/molecules.
    *   `src/views`: Page-level components.
    *   `src/services`: API clients.
    *   `src/stores`: State management.

## 2. Analysis of Existing System

### 2.1. Frontend (`frontend/dist/index.html`)
*   **Current State:** Monolithic HTML + JS (Vue 3 CDN) + CSS.
*   **Issues:** Hard to maintain, no build step, global scope pollution, lack of type safety.
*   **Migration Strategy:** Extract sections into `views` and `components`.

### 2.2. Backend (`backend/`)
*   **Technology:** Python (FastAPI/Flask?).
*   **API Surface (Routers):**
    *   `auth`: Authentication.
    *   `nodes`, `vms`, `lxc`: Infrastructure resources.
    *   `snapshots`, `backup_jobs`, `recovery_jobs`, `sync_jobs`, `migration_jobs`, `host_backup`: Operations.
    *   `logs`, `settings`, `updates`: System management.

## 3. Implementation Logic

1.  **Initialize `DA-REPL`**: Create the directory and scaffold a Vite + Vue + TS project.
2.  **Infrastructure Setup**: Configure Proxy to existing backend (for dev).
3.  **Modularization Loop**:
    *   Pick a feature (e.g., Auth).
    *   Create Service (`services/auth.ts`).
    *   Create Store (`stores/auth.ts`).
    *   Create View (`views/Login.vue`).
    *   Verify against backend.
4.  **Verification**: Ensure feature parity with legacy `index.html`.

# Istruzioni Agente

Operi all'interno di un'architettura a 3 livelli che separa le responsabilità per massimizzare l'affidabilità. Gli LLM sono probabilistici, mentre la maggior parte della logica di business è deterministica e richiede coerenza. Questo sistema risolve il problema.

## Architettura a 3 Livelli

**Livello 1: Direttiva (Cosa fare)**
- Fondamentalmente SOP scritte in Markdown, che vivono in `directives/`
- Definiscono gli obiettivi, gli input, i tool/script da usare, gli output e i casi limite
- Istruzioni in linguaggio naturale, come le daresti a un dipendente di medio livello

**Livello 2: Orchestrazione (Decisioni)**
- Il tuo lavoro: routing intelligente.
- Leggi le direttive, chiama gli strumenti di esecuzione nell'ordine giusto, gestisci gli errori, chiedi chiarimenti, aggiorna le direttive con ciò che impari
- Sei il collante tra intenzione ed esecuzione. Per esempio, non provi a fare scraping di siti web tu stesso—leggi `directives/scrape_website.md` e definisci input/output e poi esegui `execution/scrape_single_site.py`

**Livello 3: Esecuzione (Fare il lavoro)**
- Script Python deterministici in `execution/`
- Variabili d'ambiente, token API, ecc sono salvati in `.env`
- Gestiscono chiamate API, elaborazione dati, operazioni su file, interazioni con database
- Affidabili, testabili, veloci. Usa script invece di lavoro manuale. Ben commentati.

**Perché funziona:** se fai tutto tu stesso, gli errori si sommano. 90% di accuratezza per step = 59% di successo su 5 step. La soluzione è spingere la complessità in codice deterministico. Così tu ti concentri solo sul decision-making.

## Principi Operativi

**1. Controlla prima i tool esistenti**
Prima di scrivere uno script, controlla `execution/` secondo la tua direttiva. Crea nuovi script solo se non ne esistono.

**2. Auto-correggiti quando qualcosa si rompe**
- Leggi il messaggio di errore e lo stack trace
- Correggi lo script e testalo di nuovo (a meno che non usi token/crediti a pagamento—in quel caso chiedi prima all'utente)
- Aggiorna la direttiva con ciò che hai imparato (limiti API, timing, casi limite)
- Esempio: hai un rate limit API → allora guardi nell'API → trovi un batch endpoint che risolverebbe → riscrivi lo script per adattarlo → testi → aggiorna la direttiva.

**3. Aggiorna le direttive mentre impari**
Le direttive sono documenti vivi. Quando scopri vincoli API, approcci migliori, errori comuni o aspettative di timing—aggiorna la direttiva. Ma non creare o sovrascrivere direttive senza chiedere, a meno che non ti venga esplicitamente detto. Le direttive sono il tuo set di istruzioni e devono essere preservate (e migliorate nel tempo, non usate estemporaneamente e poi scartate).

## Loop di auto-correzione

Gli errori sono opportunità di apprendimento. Quando qualcosa si rompe:
1. Correggilo
2. Aggiorna il tool
3. Testa il tool, assicurati che funzioni
4. Aggiorna la direttiva per includere il nuovo flusso
5. Il sistema ora è più forte

## Sviluppo Applicazioni Web

**Stack tecnologico:**
Quando ti viene chiesto di creare un'app web, usa il seguente stack:
- **Frontend**: Next.js + React + Tailwind CSS
- **Backend**: FastAPI (Python) o Next.js API routes

**Brand Guidelines:**
Prima di iniziare lo sviluppo, controlla se esiste `brand-guidelines.md` nella root del progetto. Se presente, usa i font e i colori specificati per mantenere coerenza con il brand.

**Struttura directory per applicazioni:**
```
project-root/
├── frontend/          # App Next.js
│   ├── app/          # Next.js App Router
│   ├── components/   # Componenti React
│   ├── public/       # Asset statici
│   └── package.json
├── backend/          # API FastAPI (se necessario)
│   ├── main.py      # Entry point
│   ├── requirements.txt
│   └── .env
├── directives/       # SOP in Markdown
├── execution/        # Script Python utility
├── .tmp/            # File intermedi
└── brand-guidelines.md  # (opzionale) Font e colori
```

## Organizzazione File

**Deliverable vs Intermedi:**
- **Deliverable**: Google Sheets, Google Slides o altri output cloud-based a cui l'utente può accedere
- **Intermedi**: File temporanei necessari durante l'elaborazione

**Struttura directory:**
- `.tmp/` - Tutti i file intermedi (dossier, dati scraped, export temporanei). Mai committare, sempre rigenerati.
- `execution/` - Script Python (i tool deterministici)
- `directives/` - SOP in Markdown (il set di istruzioni)
- `.env` - Variabili d'ambiente e chiavi API
- `credentials.json`, `token.json` - Credenziali OAuth Google (file necessari, in `.gitignore`)

**Principio chiave:** I file locali sono solo per l'elaborazione. I deliverable vivono nei servizi cloud (Google Sheets, Slides, ecc.) dove l'utente può accedervi. Tutto in `.tmp/` può essere cancellato e rigenerato.

## Riepilogo

Ti posizioni tra intenzione umana (direttive) ed esecuzione deterministica (script Python). Leggi le istruzioni, prendi decisioni, chiama i tool, gestisci gli errori, migliora continuamente il sistema.

Sii pragmatico. Sii affidabile. Auto-correggiti.
