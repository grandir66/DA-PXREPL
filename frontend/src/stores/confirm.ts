/**
 * Confirm store — dialog di conferma promise-based.
 *
 * Sostituisce `confirm()` nativo con un modale stilato.
 * Usage:
 *   import { useConfirm } from '../stores/confirm'
 *   const ok = await useConfirm().ask({
 *     title: 'Eliminare il job?',
 *     message: 'L'operazione e' irreversibile.',
 *     confirmText: 'Elimina',
 *     danger: true,
 *   })
 *   if (!ok) return
 */
import { defineStore } from 'pinia'

export interface ConfirmOptions {
  title: string
  message?: string
  confirmText?: string
  cancelText?: string
  danger?: boolean
}

interface State {
  visible: boolean
  options: ConfirmOptions | null
  resolver: ((v: boolean) => void) | null
}

export const useConfirmStore = defineStore('confirm', {
  state: (): State => ({
    visible: false,
    options: null,
    resolver: null,
  }),
  actions: {
    ask(opts: ConfirmOptions): Promise<boolean> {
      // Risolvi la promise pendente come "false" (cancel) prima di sovrascrivere
      if (this.resolver) {
        try { this.resolver(false) } catch { /* ignore */ }
      }
      this.options = {
        confirmText: 'Conferma',
        cancelText: 'Annulla',
        danger: false,
        ...opts,
      }
      this.visible = true
      return new Promise<boolean>(resolve => {
        this.resolver = resolve
      })
    },
    resolve(value: boolean) {
      const r = this.resolver
      this.resolver = null
      this.visible = false
      this.options = null
      if (r) r(value)
    },
  },
})

export function useConfirm() {
  return useConfirmStore()
}

/** Helper rapido: conferma di eliminazione con stile danger. */
export function confirmDelete(name: string, what: string = 'elemento'): Promise<boolean> {
  return useConfirmStore().ask({
    title: `Eliminare ${what}?`,
    message: `"${name}" sarà rimosso. L'operazione è irreversibile.`,
    confirmText: 'Elimina',
    cancelText: 'Annulla',
    danger: true,
  })
}

/** Helper: conferma di operazione potenzialmente distruttiva non-delete. */
export function confirmDangerous(
  title: string,
  message?: string,
  confirmText: string = 'Procedi'
): Promise<boolean> {
  return useConfirmStore().ask({
    title,
    message,
    confirmText,
    cancelText: 'Annulla',
    danger: true,
  })
}
