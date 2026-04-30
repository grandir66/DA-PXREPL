/**
 * Toast store — notifiche non bloccanti.
 *
 * Sostituisce `alert()` con un layer visuale globale.
 * Usage:
 *   import { useToast } from '../stores/toast'
 *   const toast = useToast()
 *   toast.success('Salvato')
 *   toast.error('Errore', 'Dettagli...')
 */
import { defineStore } from 'pinia'

export type ToastKind = 'success' | 'error' | 'warning' | 'info'

export interface Toast {
  id: number
  kind: ToastKind
  title: string
  message?: string
  ttl: number   // ms; 0 = sticky
  createdAt: number
}

let _seq = 0

export const useToastStore = defineStore('toast', {
  state: () => ({
    toasts: [] as Toast[],
  }),
  actions: {
    push(t: Omit<Toast, 'id' | 'createdAt'>): number {
      const id = ++_seq
      const toast: Toast = { id, createdAt: Date.now(), ...t }
      this.toasts.push(toast)
      if (toast.ttl > 0) {
        setTimeout(() => this.dismiss(id), toast.ttl)
      }
      return id
    },
    dismiss(id: number) {
      this.toasts = this.toasts.filter(t => t.id !== id)
    },
    clear() {
      this.toasts = []
    },
    success(title: string, message?: string, ttl = 3500) {
      return this.push({ kind: 'success', title, message, ttl })
    },
    error(title: string, message?: string, ttl = 7000) {
      return this.push({ kind: 'error', title, message, ttl })
    },
    warning(title: string, message?: string, ttl = 5000) {
      return this.push({ kind: 'warning', title, message, ttl })
    },
    info(title: string, message?: string, ttl = 4000) {
      return this.push({ kind: 'info', title, message, ttl })
    },
  },
})

// Wrapper comodo per import a livello di file.
export function useToast() {
  return useToastStore()
}

/**
 * Estrae un messaggio di errore leggibile da un'eccezione axios o JS.
 */
export function errorMessage(e: unknown, fallback = 'Errore imprevisto'): string {
  const any = e as any
  return (
    any?.response?.data?.detail ||
    any?.response?.data?.message ||
    any?.message ||
    String(e || fallback) ||
    fallback
  )
}
