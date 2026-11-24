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
import { i18n } from '../i18n'

const t = i18n.global.t

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
        confirmText: t('comune.conferma'),
        cancelText: t('comune.annulla'),
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
export function confirmDelete(name: string, what: string = t('conferma.elemento')): Promise<boolean> {
  return useConfirmStore().ask({
    title: t('conferma.eliminareTitolo', { cosa: what }),
    message: t('conferma.eliminareMessaggio', { nome: name }),
    confirmText: t('comune.elimina'),
    cancelText: t('comune.annulla'),
    danger: true,
  })
}

/** Helper: conferma di operazione potenzialmente distruttiva non-delete. */
export function confirmDangerous(
  title: string,
  message?: string,
  confirmText: string = t('comune.procedi')
): Promise<boolean> {
  return useConfirmStore().ask({
    title,
    message,
    confirmText,
    cancelText: t('comune.annulla'),
    danger: true,
  })
}
