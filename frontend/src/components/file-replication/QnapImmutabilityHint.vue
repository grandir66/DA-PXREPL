<script setup lang="ts">
defineProps<{
  snapshotSchedule?: string
  expirationDays?: number
  maxSnapshots?: number
}>()
</script>

<template>
  <div class="hint-card">
    <h4>Snapshot QNAP (unico storico)</h4>
    <p>
      dapx replica solo i <strong>file correnti</strong> da Synology. Cartelle snapshot e di sistema
      (<code>#snapshot</code>, <code>@Snapshot</code>, …) non vengono mai copiate.
      Lo storico si gestisce <strong>solo su QNAP</strong> con Snapshot Manager.
    </p>
    <ol>
      <li>Share destinazione <em>thin</em>, compressione ON.</li>
      <li>Snapshot schedule: almeno <strong>1h dopo</strong> il cron sync dapx.</li>
      <li>Protection: <strong>Prohibit recycle and delete until expired</strong>.</li>
      <li>Retention: Smart Versioning o max snapshot (es. {{ maxSnapshots ?? 10 }}).</li>
      <li>Abilita <strong>Only if modified</strong> e guaranteed snapshot space.</li>
    </ol>
    <p class="hint-meta">
      Snapshot consigliato: <code>{{ snapshotSchedule ?? '0 3 * * *' }}</code> —
      retention {{ expirationDays ?? 30 }} giorni.
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
