#!/usr/bin/env node
// Cancello degli errori del backend: ogni frase fissa di `detail="..."` in
// `backend/routers`, `backend/services` e `backend/main.py` deve avere la sua
// voce in `src/locales/backend-en.json`. Le voci senza più una frase nel
// backend vengono solo elencate (avviso).
import { readFileSync, readdirSync, statSync, existsSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const radice = join(dirname(fileURLToPath(import.meta.url)), '..')
const backend = join(radice, '..', 'backend')
if (!existsSync(backend)) {
  console.log('controlla-backend: cartella backend assente, controllo saltato')
  process.exit(0)
}
const dizionario = JSON.parse(readFileSync(join(radice, 'src', 'locales', 'backend-en.json'), 'utf8'))

function file(dir, out = []) {
  for (const n of readdirSync(dir)) {
    if (n === 'tests' || n === 'venv' || n === '__pycache__') continue
    const p = join(dir, n)
    if (statSync(p).isDirectory()) file(p, out)
    else if (n.endsWith('.py')) out.push(p)
  }
  return out
}
const sorgenti = [...file(join(backend, 'routers')), ...file(join(backend, 'services')), join(backend, 'main.py')]
const frasi = new Set()
for (const p of sorgenti) {
  for (const m of readFileSync(p, 'utf8').matchAll(/detail\s*=\s*\(?\s*"([^"]+)"/g)) frasi.add(m[1])
}

const mancanti = [...frasi].filter((f) => !(f in dizionario)).sort()
const orfane = Object.keys(dizionario).filter((k) => !frasi.has(k)).sort()
if (orfane.length) console.log(`controlla-backend: ${orfane.length} voci senza più una frase nel backend:\n  ${orfane.join('\n  ')}`)
if (mancanti.length) {
  console.error(`controlla-backend: ${mancanti.length} frasi del backend senza traduzione in backend-en.json:\n  ${mancanti.join('\n  ')}`)
  process.exit(1)
}
console.log(`controlla-backend: ${frasi.size} frasi, tutte tradotte`)
