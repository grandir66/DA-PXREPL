import { createApp } from 'vue'
import './style.css'

import App from './App.vue'

import router from './router'
import { createPinia } from 'pinia'
import { useToastStore } from './stores/toast'
import { useConfirmStore } from './stores/confirm'

const app = createApp(App)

const pinia = createPinia()
app.use(pinia)
app.use(router)

// Override globale di window.alert/confirm con il sistema di notifiche
// stilato. Le viste legacy che usano ancora alert()/confirm() ne
// beneficiano senza modifiche.
//
// confirm() resta SINCRONO (deve ritornare boolean immediatamente per
// non rompere il flusso) — usa la versione nativa. Per nuove viste
// preferire `useConfirm().ask({...})` che e' promise-based.
const nativeAlert = window.alert.bind(window)

try {
  window.alert = (msg?: any) => {
    try {
      const text = String(msg ?? '')
      const toast = useToastStore()
      // Heuristica: se contiene parole "errore"/"error"/"failed" lo
      // mostriamo come error, altrimenti info.
      const isError = /errore|error|failed|impossibile|exception/i.test(text)
      if (isError) toast.error('Avviso', text)
      else toast.info('Notifica', text)
    } catch {
      nativeAlert(msg)
    }
  }
} catch {
  /* ignore — environment may not allow override */
}

// Esponi gli store per rapidi check da console (DEV only)
if (import.meta.env.DEV) {
  ;(window as any).__dapx = { useToastStore, useConfirmStore }
}

app.mount('#app')
