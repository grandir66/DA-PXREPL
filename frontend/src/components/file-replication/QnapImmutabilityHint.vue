<script setup lang="ts">
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
defineProps<{
  snapshotSchedule?: string
  expirationDays?: number
  maxSnapshots?: number
}>()
</script>

<template>
  <div class="hint-card">
    <h4>{{ t('qnap.titolo') }}</h4>
    <p>
      <i18n-t keypath="qnap.nota" tag="span"><template #cartelle><code>#snapshot</code>, <code>@Snapshot</code></template></i18n-t>
    </p>
    <ol>
      <li>{{ t('qnap.p1') }}</li>
      <li>{{ t('qnap.p2') }}</li>
      <li>{{ t('qnap.p3') }} <strong>Prohibit recycle and delete until expired</strong>.</li>
      <li>{{ t('qnap.p4', { n: maxSnapshots ?? 10 }) }}</li>
      <li>{{ t('qnap.p5') }}</li>
    </ol>
    <p class="hint-meta">
      <i18n-t keypath="qnap.consigliato" tag="span"><template #cron><code>{{ snapshotSchedule ?? '0 3 * * *' }}</code></template><template #giorni>{{ expirationDays ?? 30 }}</template></i18n-t>
    </p>
  </div>
</template>

<style scoped>
.hint-card {
  background: var(--bg-secondary, #1a1a2e);
  border: 1px solid var(--border-color, #333);
  border-radius: 8px;
  padding: 16px;
  font-size: 0.9rem;
}
.hint-card ol { margin: 8px 0 0 1.2rem; }
.hint-meta { margin-top: 12px; opacity: 0.85; }
</style>
