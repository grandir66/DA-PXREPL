/** Normalizzazione nomi pool/dataset/storage ZFS (allineato a backend/services/zfs_naming.py). */

export function collapseDashSegments(name: string): string {
  if (!name) return name
  const parts = name.split('-')
  const out: string[] = []
  for (const part of parts) {
    if (out.length && out[out.length - 1].toLowerCase() === part.toLowerCase()) continue
    out.push(part)
  }
  return out.join('-')
}

export function normalizeZfsDestPath(
  pool: string | null | undefined,
  subfolder: string | null | undefined,
): { pool: string; subfolder: string | null } {
  const cleanPool = (pool || '').trim().replace(/^\/+|\/+$/g, '')
  const cleanSub = (subfolder || '').trim().replace(/^\/+|\/+$/g, '') || null
  if (!cleanPool || !cleanSub) return { pool: cleanPool, subfolder: cleanSub }

  if (!cleanPool.includes('/') && cleanPool.endsWith(`-${cleanSub}`)) {
    const root = cleanPool.slice(0, -(cleanSub.length + 1))
    if (root) return { pool: root, subfolder: cleanSub }
  }
  if (cleanPool.endsWith(`/${cleanSub}`)) {
    const root = cleanPool.slice(0, -(cleanSub.length + 1)).replace(/\/+$/, '')
    if (root) return { pool: root, subfolder: cleanSub }
  }
  return { pool: cleanPool, subfolder: cleanSub }
}

export function zfsDatasetPath(pool: string, subfolder: string | null): string {
  const n = normalizeZfsDestPath(pool, subfolder)
  if (!n.pool) return ''
  return n.subfolder ? `${n.pool}/${n.subfolder}` : n.pool
}

export function deriveZfsStorageName(
  storageName: string | null | undefined,
  zfsPool: string,
): string {
  if (!zfsPool) return collapseDashSegments((storageName || '').trim())

  const parts = zfsPool.split('/')
  const root = parts[0]
  const base = (storageName || root).trim()
  if (parts.length <= 1 || zfsPool === base || zfsPool === root) {
    return collapseDashSegments(base)
  }

  const sub = parts.slice(1).join('-')
  const fromRoot = `${root}-${sub}`
  if (base === fromRoot || base === root) {
    return collapseDashSegments(base === root ? fromRoot : base)
  }
  if (base.endsWith(`-${sub}`)) return collapseDashSegments(base)
  return collapseDashSegments(`${base}-${sub}`)
}

export function normalizeZfsReplicaDest(
  destPool: string | null | undefined,
  destSubfolder: string | null | undefined,
  destStorage?: string | null,
) {
  const { pool, subfolder } = normalizeZfsDestPath(destPool, destSubfolder)
  const zfsPath = zfsDatasetPath(pool, subfolder)
  const storageName = deriveZfsStorageName(destStorage || pool, zfsPath)
  return { pool, subfolder, zfsPath, storageName }
}
