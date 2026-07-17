/** Normalizza path assoluto senza trailing slash (tranne root). */
export function normalizeBrowsePath(path: string): string {
  let p = (path || '').trim().replace(/\\/g, '/')
  if (!p || p === '/') return '/'
  if (!p.startsWith('/')) p = `/${p}`
  return p.replace(/\/+$/, '') || '/'
}

/** True se ancestor è uguale o antenato di descendant. */
export function isPathAncestor(ancestor: string, descendant: string): boolean {
  const a = normalizeBrowsePath(ancestor)
  const d = normalizeBrowsePath(descendant)
  if (a === d) return true
  return d.startsWith(`${a}/`)
}

/** Tieni solo i path più alti (padre copre i figli). */
export function compactSourcePaths(paths: string[]): string[] {
  const normalized = [...new Set((paths || []).map(normalizeBrowsePath))].sort(
    (a, b) => a.length - b.length,
  )
  const result: string[] = []
  for (const path of normalized) {
    if (path === '/') continue
    if (result.some((existing) => isPathAncestor(existing, path))) continue
    const filtered = result.filter((existing) => !isPathAncestor(path, existing))
    filtered.push(path)
    result.length = 0
    result.push(...filtered)
  }
  return result.sort()
}

export type PathSelectionState = 'selected' | 'included' | 'none'

/** selected = path esplicito; included = coperto da un antenato selezionato. */
export function pathSelectionState(
  path: string,
  selectedPaths: Iterable<string>,
): PathSelectionState {
  const normalized = normalizeBrowsePath(path)
  const selected = [...selectedPaths].map(normalizeBrowsePath)
  if (selected.includes(normalized)) return 'selected'
  if (selected.some((p) => isPathAncestor(p, normalized))) return 'included'
  return 'none'
}
