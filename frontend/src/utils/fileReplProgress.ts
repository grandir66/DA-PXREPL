export interface FileReplFolderItem {
  path: string
  name?: string | null
  bytes?: number
  size_human?: string
  status: 'pending' | 'in_progress' | 'done' | 'skipped' | string
  session_human?: string
  progress_pct?: number
  status_hint?: string
  files_skipped?: number
}

export interface FileReplProgress {
  status?: string
  phase?: 'starting' | 'scanning' | 'copying' | 'done'
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
  excluded_folder_names?: string[]
  folder_activity_label?: string
  show_last_file?: boolean
  files_new?: number
  files_replaced?: number
}

export function formatFileReplProgress(p: FileReplProgress | null | undefined): string {
  if (!p) return ''
  if (p.display_summary) return p.display_summary
  if (p.summary) return p.summary
  if (p.phase_label && p.detail_lines?.length) {
    return `${p.phase_label} — ${p.detail_lines[0]}`
  }
  if (p.phase_label) return p.phase_label
  return ''
}

export function fileReplProgressPercent(p: FileReplProgress | null | undefined): number | null {
  if (!p) return null
  const raw = p.progress_percent || p.checks_percent || p.percent
  if (!raw || raw === '-' || raw === '-%') return null
  const n = parseInt(raw.replace('%', ''), 10)
  return Number.isFinite(n) ? Math.min(100, Math.max(0, n)) : null
}
