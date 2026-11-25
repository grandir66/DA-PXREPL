// Errori del backend in inglese (P6a, 25/11/2026).
// Il backend scrive le frasi in italiano; quelle fisse si traducono qui per
// corrispondenza esatta, in un punto solo (l'intercettore di `services/api.ts`).
// Una frase che non è nel dizionario si vede com'è: mai un testo vuoto.
// `scripts/controlla-backend.mjs` (dentro `npm run lint`) fallisce se nel
// backend c'è una frase fissa senza la sua voce.
import en from '../locales/backend-en.json'
import { linguaCorrente } from './index'

const EN = en as Record<string, string>

export function traduciBackend(testo: string): string {
  if (linguaCorrente() !== 'en') return testo
  return EN[testo] ?? EN[testo.trim()] ?? testo
}

/** Traduce sul posto `response.data.detail` di un errore axios, se è una frase nota. */
export function traduciErrore(errore: unknown): void {
  const dati = (errore as { response?: { data?: unknown } } | null)?.response?.data
  if (!dati || typeof dati !== 'object') return
  const d = dati as { detail?: unknown }
  if (typeof d.detail === 'string') d.detail = traduciBackend(d.detail)
}
