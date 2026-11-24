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
const CHIAVE_ANTEPRIMA = 'dapx.lang.anteprima'

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

/**
 * Il selettore resta nascosto finché le viste non sono tradotte: si vede in
 * sviluppo, oppure con `localStorage['dapx.lang.anteprima'] = '1'`.
 */
export const SELETTORE_VISIBILE: boolean = import.meta.env.DEV || leggi(CHIAVE_ANTEPRIMA) === '1'

// Senza selettore la lingua è sempre la predefinita, anche se nel browser è
// rimasta una scelta fatta in anteprima.
const iniziale: Lingua = SELETTORE_VISIBILE ? linguaSalvata() : LINGUA_PREDEFINITA

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
