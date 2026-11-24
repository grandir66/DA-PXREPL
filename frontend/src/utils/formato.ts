// Date e numeri nella lingua dell'interfaccia: una funzione sola al posto dei
// `toLocaleString()` sparsi (alcuni fissi su 'it-IT', altri sulla lingua del
// browser). Ogni vista passa di qui quando viene tradotta.
import { LOCALE_FORMATI, linguaCorrente } from '../i18n'

type Ingresso = string | number | Date | null | undefined

function locale(): string {
  return LOCALE_FORMATI[linguaCorrente()]
}

function aData(v: Ingresso): Date | null {
  if (v === null || v === undefined || v === '') return null
  const d = v instanceof Date ? v : new Date(v)
  return Number.isNaN(d.getTime()) ? null : d
}

/** Data e ora, es. «24/11/26, 19:33». Valore assente o illeggibile: `vuoto`. */
export function dataOra(
  v: Ingresso,
  opzioni: Intl.DateTimeFormatOptions = { dateStyle: 'short', timeStyle: 'short' },
  vuoto = '—',
): string {
  const d = aData(v)
  return d ? d.toLocaleString(locale(), opzioni) : vuoto
}

/** Solo la data. */
export function data(v: Ingresso, vuoto = '—'): string {
  const d = aData(v)
  return d ? d.toLocaleDateString(locale(), { dateStyle: 'short' }) : vuoto
}

/** Solo l'ora. */
export function ora(v: Ingresso, vuoto = '—'): string {
  const d = aData(v)
  return d ? d.toLocaleTimeString(locale(), { timeStyle: 'medium' }) : vuoto
}

/** Numero con i separatori della lingua. */
export function numero(v: number | null | undefined, opzioni?: Intl.NumberFormatOptions, vuoto = '—'): string {
  return typeof v === 'number' && Number.isFinite(v) ? v.toLocaleString(locale(), opzioni) : vuoto
}
