#!/usr/bin/env node
// Cancello delle lingue: fallisce se
//  - una chiave c'è in una lingua e manca nell'altra;
//  - i segnaposto ({nome}) di una chiave non coincidono fra le lingue;
//  - il codice usa t('chiave') / $t('chiave') e la chiave non è in it.json.
// Le chiavi presenti nei file ma mai usate vengono solo elencate (avviso).
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, dirname, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const radice = join(dirname(fileURLToPath(import.meta.url)), '..')
const src = join(radice, 'src')
const LINGUE = ['it', 'en']

function piatto(o, pre = '', out = {}) {
  for (const [k, v] of Object.entries(o)) {
    const c = pre ? `${pre}.${k}` : k
    if (v && typeof v === 'object') piatto(v, c, out)
    else out[c] = String(v)
  }
  return out
}
const lingue = Object.fromEntries(
  LINGUE.map((l) => [l, piatto(JSON.parse(readFileSync(join(src, 'locales', `${l}.json`), 'utf8')))]),
)
const segnaposto = (s) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort().join(',')

const errori = []
const tutte = new Set(LINGUE.flatMap((l) => Object.keys(lingue[l])))
for (const k of [...tutte].sort()) {
  const mancanti = LINGUE.filter((l) => !(k in lingue[l]))
  if (mancanti.length) {
    errori.push(`chiave «${k}» manca in: ${mancanti.join(', ')}`)
    continue
  }
  const [a, b] = LINGUE.map((l) => segnaposto(lingue[l][k]))
  if (a !== b) errori.push(`chiave «${k}»: segnaposto diversi (it: ${a || '-'} · en: ${b || '-'})`)
  for (const l of LINGUE) if (!lingue[l][k].trim()) errori.push(`chiave «${k}» vuota in ${l}`)
}

function file(dir, out = []) {
  for (const n of readdirSync(dir)) {
    const p = join(dir, n)
    if (statSync(p).isDirectory()) file(p, out)
    else if (/\.(vue|ts)$/.test(n)) out.push(p)
  }
  return out
}
const usate = new Set()
const USO = /(?<![\w$])\$?t\(\s*(['"`])([A-Za-z0-9_.-]+)\1/g
// Chiavi composte, t(`giorni.brevi.${d}`): vale come usato tutto il prefisso.
const USO_PREFISSO = /(?<![\w$])\$?t\(\s*`([A-Za-z0-9_.-]+\.)\$\{/g
const prefissi = new Set()
for (const p of file(src)) {
  const testo = readFileSync(p, 'utf8')
  for (const m of testo.matchAll(USO)) {
    usate.add(m[2])
    if (!(m[2] in lingue.it)) {
      const riga = testo.slice(0, m.index).split('\n').length
      errori.push(`${relative(radice, p)}:${riga} usa «${m[2]}», che non è in it.json`)
    }
  }
  for (const m of testo.matchAll(/keypath="([A-Za-z0-9_.-]+)"/g)) {
    usate.add(m[1])
    if (!(m[1] in lingue.it)) errori.push(`${relative(radice, p)} usa keypath «${m[1]}», che non è in it.json`)
  }
  for (const m of testo.matchAll(USO_PREFISSO)) {
    prefissi.add(m[1])
    if (!Object.keys(lingue.it).some((k) => k.startsWith(m[1]))) {
      const riga = testo.slice(0, m.index).split('\n').length
      errori.push(`${relative(radice, p)}:${riga} usa il prefisso «${m[1]}», che non ha chiavi in it.json`)
    }
  }
}
const orfane = Object.keys(lingue.it).filter((k) => !usate.has(k) && ![...prefissi].some((pre) => k.startsWith(pre)))

console.log(`lingue: ${Object.keys(lingue.it).length} chiavi in it, ${Object.keys(lingue.en).length} in en, ${usate.size} usate nel codice`)
if (orfane.length) console.log(`avviso: ${orfane.length} chiavi mai usate: ${orfane.slice(0, 20).join(', ')}${orfane.length > 20 ? ', …' : ''}`)
if (errori.length) {
  console.error(`\n${errori.length} errori:`)
  for (const e of errori) console.error(`  - ${e}`)
  process.exit(1)
}
