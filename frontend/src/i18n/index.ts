// Localizzazione dell'interfaccia (dal 24/11/2026).
// Italiano predefinito e di ripiego: una chiave che manca in inglese si vede
// in italiano, mai come chiave nuda. La scelta è dell'utente e vive nel
// browser (`dapx.lang`); la colonna sul profilo arriva con una tappa a parte.
import { createI18n } from 'vue-i18n'
import it from '../locales/it.json'
import en from '../locales/en.json'

export const LINGUE = ['it', 'en'] as const
export type Lingua = (typeof LINGUE)[number]
export const LINGUA_PREDEFINITA: Lingua = 'it'

const CHIAVE = 'dapx.lang'

/** Locale BCP 47 per date e numeri. */
export const LOCALE_FORMATI: Record<Lingua, string> = { it: 'it-IT', en: 'en-GB' }

function leggi(chiave: string): string | null {
  try {
    return localStorage.getItem(chiave)
  } catch {
    return null
  }
}

function linguaSalvata(): Lingua {
  const v = leggi(CHIAVE)
  return (LINGUE as readonly string[]).includes(v ?? '') ? (v as Lingua) : LINGUA_PREDEFINITA
}

/** Il selettore di lingua è visibile a tutti dalla 3.28.0 (tutte le viste del menu sono tradotte). */
export const SELETTORE_VISIBILE = true

const iniziale: Lingua = linguaSalvata()

export const i18n = createI18n({
  legacy: false,
  locale: iniziale,
  fallbackLocale: LINGUA_PREDEFINITA,
  messages: { it, en },
})

export function linguaCorrente(): Lingua {
  return i18n.global.locale.value as Lingua
}

export function impostaLingua(lingua: Lingua): void {
  i18n.global.locale.value = lingua
  document.documentElement.lang = lingua
  try {
    localStorage.setItem(CHIAVE, lingua)
  } catch {
    /* browser senza localStorage: la scelta vale per la sessione */
  }
}

document.documentElement.lang = iniziale

export default i18n
