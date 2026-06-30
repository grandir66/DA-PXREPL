<template>
  <div v-if="allowed">
    <slot />
  </div>
  <div v-else class="admin-gate">
    <div class="admin-gate-card">
      <Icon name="shield" :size="32" />
      <h2>Accesso riservato agli amministratori</h2>
      <p>Non hai i permessi per accedere a questa sezione.</p>
      <router-link :to="{ name: 'dashboard' }" class="btn btn-primary btn-sm">Torna alla Dashboard</router-link>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useAuthStore } from '../../stores/auth'
import Icon from './Icon.vue'

const auth = useAuthStore()

const allowed = computed(() => auth.isAdmin)

onMounted(async () => {
  if (auth.isAuthenticated && !auth.user?.role) {
    await auth.fetchUser()
  }
})
</script>

<style scoped>
.admin-gate {
  display: flex;
  justify-content: center;
  padding: 48px 16px;
}
.admin-gate-card {
  text-align: center;
  max-width: 420px;
  padding: 32px;
  background: var(--color-bg-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
}
.admin-gate-card h2 {
  margin: 16px 0 8px;
  font-size: 1.1rem;
}
.admin-gate-card p {
  color: var(--color-text-secondary);
  margin-bottom: 20px;
}
</style>
