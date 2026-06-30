export type AppMode = 'full' | 'lb'

const STORAGE_KEY = 'dapx_mode'

export function setAppMode(mode: AppMode): void {
  sessionStorage.setItem(STORAGE_KEY, mode)
}

export function getAppMode(): AppMode {
  const v = sessionStorage.getItem(STORAGE_KEY)
  return v === 'lb' ? 'lb' : 'full'
}

export function isFullMode(): boolean {
  return getAppMode() === 'full'
}
