<script setup lang="ts">
defineProps<{
  snapshotSchedule?: string
  expirationDays?: number
  maxSnapshots?: number
}>()
</script>

<template>
  <div class="hint-card">
    <h4>Protezione immutabilità — QuTS hero h6.0</h4>
    <p>
      dapx esegue il sync sulla share <strong>staging mutabile</strong>. Configura su QNAP
      (Snapshot Manager) snapshot immutabili con retention.
    </p>
    <ol>
      <li>Crea share staging <em>thin</em>, compressione ON, <strong>senza WORM</strong>.</li>
      <li>Abilita rsync/SSH/SMB per l'host dapx.</li>
      <li>Snapshot schedule: almeno <strong>1h dopo</strong> il cron sync dapx.</li>
      <li>Protection policy: <strong>Prohibit recycle and delete until expired</strong>.</li>
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
