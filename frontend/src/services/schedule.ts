import apiClient from './api'

export type ScheduleKind =
  | 'manual'
  | 'hourly'
  | 'daily'
  | 'weekly'
  | 'monthly'
  | 'every_n_hours'
  | 'every_n_days'
  | 'advanced'

export type WeekDay = 'sun' | 'mon' | 'tue' | 'wed' | 'thu' | 'fri' | 'sat'

export interface ScheduleConfig {
  kind: ScheduleKind
  time?: string          // 'HH:MM'
  minute?: number        // 0-59
  weekdays?: WeekDay[]   // weekly
  day_of_month?: number  // 1-31
  hours?: number         // 1-23 (every_n_hours)
  days?: number          // 1-30 (every_n_days)
  cron?: string          // advanced
}

export interface TranslateResponse {
  config: ScheduleConfig
  cron: string | null
  human: string
  valid: boolean
  error?: string
  next_runs: string[]
}

export const WEEKDAYS_ORDER: WeekDay[] = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
export const WEEKDAY_LABELS_IT: Record<WeekDay, string> = {
  mon: 'Lun',
  tue: 'Mar',
  wed: 'Mer',
  thu: 'Gio',
  fri: 'Ven',
  sat: 'Sab',
  sun: 'Dom',
}

export default {
  translate(payload: { config?: ScheduleConfig; cron?: string | null }) {
    return apiClient.post<TranslateResponse>('/schedule/translate', payload)
  },
}
