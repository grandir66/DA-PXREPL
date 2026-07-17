/** File Station QNAP usa /DATI/...; lo staging job usa /share/DATI/... */
export function normalizeQnapStagingPath(path: string): string {
  let p = (path || '').trim().replace(/\\/g, '/')
  if (!p || p === '/') return '/share'
  if (!p.startsWith('/')) p = `/${p}`
  p = p.replace(/\/+$/, '') || '/'
  if (p.startsWith('/share/') || p === '/share') return p
  return `/share${p}`
}

/** Solo share QNAP di destinazione, senza sottocartelle (/share/DATI). */
export function normalizeQnapDestShare(path: string): string {
  const p = normalizeQnapStagingPath(path)
  const parts = p.replace(/\/+$/, '').split('/').filter(Boolean)
  if (parts[0] === 'share' && parts.length >= 2) return `/share/${parts[1]}`
  return p
}

/** Anteprima destinazione: replica struttura Synology sotto la share QNAP. */
export function synologyToQnapDestPath(srcPath: string, destSharePath: string): string {
  const parts = srcPath.replace(/^\/+/, '').split('/').filter(Boolean)
  if (!parts.length) return `${normalizeQnapDestShare(destSharePath)}/`
  let i = 0
  if (parts[0].startsWith('volume') && parts.length >= 2) i = 1
  const share = parts[i]
  const sub = parts.slice(i + 1).join('/')
  const root = normalizeQnapDestShare(destSharePath).replace(/\/+$/, '')
  return sub ? `${root}/${share}/${sub}/` : `${root}/${share}/`
}
