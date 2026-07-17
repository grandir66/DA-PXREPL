import { normalizeQnapDestShare, synologyToQnapDestPath } from './qnapPath'

export interface FileReplMappingRow {
  sourcePath: string
  sourceSegments: string[]
  destPath: string
  destSegments: string[]
}

/** Segmenti path Synology (/Comune/AArchivio → Comune, AArchivio). */
export function parseSynologyPathSegments(path: string): string[] {
  const parts = path.replace(/^\/+/, '').split('/').filter(Boolean)
  if (!parts.length) return []
  if (parts[0].startsWith('volume') && parts.length >= 2) return parts.slice(1)
  return parts
}

/** Segmenti path QNAP destinazione (/share/DATI/Comune/foo → DATI, Comune, foo). */
export function parseQnapDestSegments(path: string): string[] {
  const p = path.trim().replace(/\\/g, '/').replace(/\/+$/, '')
  const parts = p.replace(/^\/+/, '').split('/').filter(Boolean)
  if (parts[0] === 'share') return parts.slice(1)
  return parts
}

/** Etichetta share QNAP (es. DATI). */
export function formatDestShareLabel(destSharePath: string): string {
  const segments = parseQnapDestSegments(destSharePath)
  return segments[0] || destSharePath
}

export function buildFileReplMappings(
  sourcePaths: string[],
  destSharePath: string,
): FileReplMappingRow[] {
  const share = normalizeQnapDestShare(destSharePath)
  return (sourcePaths || []).map((sourcePath) => {
    const destPath = synologyToQnapDestPath(sourcePath, share)
    return {
      sourcePath,
      sourceSegments: parseSynologyPathSegments(sourcePath),
      destPath,
      destSegments: parseQnapDestSegments(destPath),
    }
  })
}
