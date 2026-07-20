export interface FileReplFolderItem {
  path: string
  name?: string | null
  root?: string | null
  bytes?: number
  size_human?: string
  status: 'pending' | 'in_progress' | 'done' | 'skipped' | 'catalogued' | string
  session_human?: string
  progress_pct?: number
  status_hint?: string
  files_skipped?: number
}

export interface FileReplProgress {
  status?: string
  phase?: 'starting' | 'scanning' | 'copying' | 'done' | string
  phase_label?: string
  detail_lines?: string[]
  hint?: string
  display_summary?: string
  progress_percent?: string
  percent?: string
  checks_percent?: string
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
  eta_human?: string
  message?: string
  last_file?: string
  summary?: string
  report?: string
  error?: string
  current_folder_name?: string
  current_folder_path?: string
  current_folder_index?: number
  current_folder_total?: number
  current_folder_progress_pct?: number
  current_folder_session_human?: string
  current_folder_size_human?: string
  folders_done?: number
  folders_pending?: number
  folder_catalog?: FileReplFolderItem[]
  folder_activity_label?: string
  catalog_view_mode?: 'catalog' | 'sync'
  catalog_roots?: string[]
  catalog_parent_path?: string | null
  show_last_file?: boolean
  files_new?: number
  files_replaced?: number
  catalog_bytes_est?: number
}

export function formatFileReplProgress(p: FileReplProgress | null | undefined): string {
  if (!p) return ''
  if (p.display_summary) return p.display_summary
  if (p.summary) return p.summary
  if (p.phase_label && p.detail_lines?.length) {
    return `${p.phase_label} — ${p.detail_lines[0]}`
  }
  if (p.phase_label) return p.phase_label
  if (p.message) return p.message

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

  const pct = p.progress_percent || p.percent
  if (pct && pct !== '-' && pct !== '-%') {
    parts.push(pct)
  }

  if (p.speed && p.speed !== '0 B/s') {
    parts.push(p.speed)
  }

  const eta = p.eta || p.eta_human
  if (eta && eta !== '-') {
    parts.push(`ETA ${eta}`)
  }

  return parts.join(' · ')
}

export function fileReplProgressPercent(p: FileReplProgress | null | undefined): number | null {
  if (!p) return null
  const raw = p.progress_percent || p.checks_percent || p.percent
  if (!raw || raw === '-' || raw === '-%') return null
  const n = parseInt(String(raw).replace('%', ''), 10)
  return Number.isFinite(n) ? Math.min(100, Math.max(0, n)) : null
}
