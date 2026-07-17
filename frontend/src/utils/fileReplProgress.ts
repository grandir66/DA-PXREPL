export interface FileReplProgress {
  status?: string
  percent?: string
  transferred_human?: string
  transferred_total_human?: string
  files_done?: number
  files_copied?: number
  files_skipped?: number
  files_deleted?: number
  files_checked?: number
  files_checked_total?: number
  files_total?: number
  speed?: string
  eta?: string
  message?: string
  last_file?: string
  summary?: string
  report?: string
  error?: string
}
export function formatFileReplProgress(p: FileReplProgress | null | undefined): string {
  if (!p) return ''
  if (p.summary) return p.summary

  const parts: string[] = []

  const copied = p.files_copied ?? p.files_done ?? 0
  const skipped = p.files_skipped ?? 0
  const deleted = p.files_deleted ?? 0
  const checked = p.files_checked_total ?? p.files_checked

  if (copied > 0) {
    let line = `${copied.toLocaleString('it-IT')} copiati`
    if (p.files_total != null && p.files_total > 0) {
      line += ` / ${p.files_total.toLocaleString('it-IT')}`
    }
    parts.push(line)
  }

  if (skipped > 0) {
    parts.push(`${skipped.toLocaleString('it-IT')} saltati`)
  }

  if (deleted > 0) {
    parts.push(`${deleted.toLocaleString('it-IT')} eliminati`)
  }

  if (checked != null && checked > 0 && copied === 0 && skipped === 0) {
    parts.push(`${Number(checked).toLocaleString('it-IT')} controllati`)
  } else if (checked != null && checked > 0 && (copied > 0 || skipped > 0)) {
    parts.push(`${Number(checked).toLocaleString('it-IT')} controllati`)
  }

  if (p.transferred_human) {
    let size = p.transferred_human
    if (p.transferred_total_human) {
      size += ` / ${p.transferred_total_human}`
    }
    parts.push(size)
  }

  if (p.percent && p.percent !== '-' && p.percent !== '-%') {
    parts.push(p.percent)
  }

  if (p.speed && p.speed !== '0 B/s') {
    parts.push(p.speed)
  }

  if (p.eta && p.eta !== '-') {
    parts.push(`ETA ${p.eta}`)
  }

  return parts.join(' · ')
}
