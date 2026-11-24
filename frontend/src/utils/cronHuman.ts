// Converte una espressione cron (5 campi: min hour dom month dow) in una frase
// leggibile nella lingua dell'interfaccia. Copre i preset del ScheduleEditor e i casi comuni;
// se non riconosce il pattern, ritorna il cron grezzo come fallback.

import { i18n } from '../i18n'

const t = i18n.global.t

function hhmm(min: string, hour: string): string | null {
  const m = Number(min)
  const h = Number(hour)
  if (!Number.isInteger(m) || !Number.isInteger(h) || m < 0 || m > 59 || h < 0 || h > 23) return null
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}

function giorniLabel(dow: string): string | null {
  // dow: "1" | "1,3,5" | "1-5"
  if (dow === '*') return null
  let nums: number[] = []
  if (dow.includes('-')) {
    const seg = dow.split('-').map(Number)
    const a = seg[0]
    const b = seg[1]
    if (a === undefined || b === undefined || !Number.isInteger(a) || !Number.isInteger(b)) return null
    for (let i = a; i <= b; i++) nums.push(i % 7)
  } else {
    nums = dow.split(',').map(Number)
  }
  if (nums.some((n) => !Number.isInteger(n) || n < 0 || n > 7)) return null
  const names = nums.map((n) => t(`giorni.lunghi.${n % 7}`))
  if (!names.length) return null
  if (names.length === 1) return names[0] ?? null
  return names.slice(0, -1).join(', ') + t('giorni.e') + names[names.length - 1]
}

export function cronToHuman(cron?: string | null): string {
  if (!cron || !cron.trim()) return t('cron.manuale')
  const parts = cron.trim().split(/\s+/)
  if (parts.length !== 5) return cron // non standard → grezzo
  const [min, hour, dom, month, dow] = parts as [string, string, string, string, string]

  // Ogni N minuti: "*/N * * * *"
  const minEvery = min.match(/^\*\/(\d+)$/)
  if (minEvery && hour === '*' && dom === '*' && month === '*' && dow === '*') {
    return t('cron.ogniNMinuti', { n: minEvery[1] })
  }
  // Ogni ora: "M * * * *"
  if (/^\d+$/.test(min) && hour === '*' && dom === '*' && month === '*' && dow === '*') {
    return Number(min) === 0 ? t('cron.ogniOra') : t('cron.ogniOraAlMinuto', { m: min })
  }
  // Ogni N ore: "M */N * * *"
  const hourEvery = hour.match(/^\*\/(\d+)$/)
  if (/^\d+$/.test(min) && hourEvery && dom === '*' && month === '*' && dow === '*') {
    return t('cron.ogniNOre', { n: hourEvery[1] })
  }

  const time = hhmm(min, hour)
  if (time) {
    // Settimanale: dow specificato
    if (dom === '*' && month === '*' && dow !== '*') {
      const g = giorniLabel(dow)
      if (g) return t('cron.settimanale', { giorni: g, ora: time })
    }
    // Mensile: dom specificato
    if (/^\d+$/.test(dom) && month === '*' && dow === '*') {
      return t('cron.mensile', { giorno: dom, ora: time })
    }
    // Giornaliero
    if (dom === '*' && month === '*' && dow === '*') {
      return t('cron.giornaliero', { ora: time })
    }
  }
  return cron // pattern avanzato → mostra il cron
}
