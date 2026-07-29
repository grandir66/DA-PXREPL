// Converte una espressione cron (5 campi: min hour dom month dow) in una frase
// leggibile in italiano. Copre i preset del ScheduleEditor e i casi comuni;
// se non riconosce il pattern, ritorna il cron grezzo come fallback.

const GIORNI = ['domenica', 'lunedì', 'martedì', 'mercoledì', 'giovedì', 'venerdì', 'sabato']

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
  const names = nums.map((n) => GIORNI[n % 7]).filter((x): x is string => Boolean(x))
  if (!names.length) return null
  if (names.length === 1) return names[0] ?? null
  return names.slice(0, -1).join(', ') + ' e ' + names[names.length - 1]
}

export function cronToHuman(cron?: string | null): string {
  if (!cron || !cron.trim()) return 'Manuale'
  const parts = cron.trim().split(/\s+/)
  if (parts.length !== 5) return cron // non standard → grezzo
  const [min, hour, dom, month, dow] = parts as [string, string, string, string, string]

  // Ogni N minuti: "*/N * * * *"
  const minEvery = min.match(/^\*\/(\d+)$/)
  if (minEvery && hour === '*' && dom === '*' && month === '*' && dow === '*') {
    return `Ogni ${minEvery[1]} minuti`
  }
  // Ogni ora: "M * * * *"
  if (/^\d+$/.test(min) && hour === '*' && dom === '*' && month === '*' && dow === '*') {
    return Number(min) === 0 ? 'Ogni ora' : `Ogni ora (al minuto ${min})`
  }
  // Ogni N ore: "M */N * * *"
  const hourEvery = hour.match(/^\*\/(\d+)$/)
  if (/^\d+$/.test(min) && hourEvery && dom === '*' && month === '*' && dow === '*') {
    return `Ogni ${hourEvery[1]} ore`
  }

  const time = hhmm(min, hour)
  if (time) {
    // Settimanale: dow specificato
    if (dom === '*' && month === '*' && dow !== '*') {
      const g = giorniLabel(dow)
      if (g) return `Ogni ${g} alle ${time}`
    }
    // Mensile: dom specificato
    if (/^\d+$/.test(dom) && month === '*' && dow === '*') {
      return `Il giorno ${dom} di ogni mese alle ${time}`
    }
    // Giornaliero
    if (dom === '*' && month === '*' && dow === '*') {
      return `Ogni giorno alle ${time}`
    }
  }
  return cron // pattern avanzato → mostra il cron
}
