<template>
  <div class="app-layout">
    <aside class="sidebar">
      <div class="brand">
        <img src="/images/domarc-logo.png" alt="Domarc" class="brand-logo" />
        <div class="brand-text">
          <span class="brand-name">DA-PXREPL</span>
          <span class="brand-tag" v-if="systemMode === 'lb'">load-balancer</span>
        </div>
      </div>

      <nav class="nav">
        <div class="nav-group">
          <div class="nav-group-title">Operativo</div>
          <router-link :to="{ name: 'dashboard' }" class="nav-item" active-class="active">
            <Icon name="home" :size="16" />
            <span>Dashboard</span>
          </router-link>
          <router-link :to="{ name: 'nodes' }" class="nav-item" active-class="active">
            <Icon name="server" :size="16" />
            <span>Nodi</span>
          </router-link>
          <router-link v-if="systemMode === 'full'" :to="{ name: 'vms' }" class="nav-item" active-class="active">
            <Icon name="monitor" :size="16" />
            <span>Virtual Machines</span>
          </router-link>
        </div>

        <div class="nav-group" v-if="systemMode === 'full'">
          <div class="nav-group-title">Cluster</div>
          <router-link :to="{ name: 'cluster' }" class="nav-item" active-class="active">
            <Icon name="cluster" :size="16" />
            <span>Cluster &amp; HA</span>
          </router-link>
          <router-link :to="{ name: 'load-balancer' }" class="nav-item" active-class="active">
            <Icon name="scale" :size="16" />
            <span>Load Balancer</span>
          </router-link>
        </div>

        <div class="nav-group" v-if="systemMode === 'full'">
          <div class="nav-group-title">Repliche &amp; Backup</div>
          <router-link :to="{ name: 'replication' }" class="nav-item" active-class="active">
            <Icon name="archive" :size="16" />
            <span>Repliche</span>
          </router-link>
          <router-link :to="{ name: 'backup-jobs' }" class="nav-item" active-class="active">
            <Icon name="database" :size="16" />
            <span>Backup PBS</span>
          </router-link>
          <router-link :to="{ name: 'migration-jobs' }" class="nav-item" active-class="active">
            <Icon name="arrow-right-left" :size="16" />
            <span>Migrazioni</span>
          </router-link>
          <router-link :to="{ name: 'host-backup' }" class="nav-item" active-class="active">
            <Icon name="shield" :size="16" />
            <span>Host Backup</span>
          </router-link>
        </div>

        <div class="nav-group">
          <div class="nav-group-title">Sistema</div>
          <button type="button" class="nav-item" @click="refreshData" :disabled="refreshing">
            <Icon name="refresh" :size="16" :class="{ 'spin': refreshing }" />
            <span>{{ refreshing ? 'Aggiornamento…' : 'Aggiorna dati' }}</span>
          </button>
          <router-link :to="{ name: 'logs' }" class="nav-item" active-class="active">
            <Icon name="file-text" :size="16" />
            <span>System Logs</span>
          </router-link>
          <router-link :to="{ name: 'settings' }" class="nav-item" active-class="active">
            <Icon name="settings" :size="16" />
            <span>Impostazioni</span>
          </router-link>
          <router-link :to="{ name: 'updates' }" class="nav-item" active-class="active">
            <Icon name="package" :size="16" />
            <span>Aggiornamenti</span>
          </router-link>
          <router-link :to="{ name: 'config-backup' }" class="nav-item" active-class="active">
            <Icon name="download" :size="16" />
            <span>Backup config</span>
          </router-link>
        </div>
      </nav>

      <div class="sidebar-foot">
        <div class="user-chip" v-if="authStore.user">
          <div class="user-avatar">
            <Icon name="user" :size="14" />
          </div>
          <div class="user-meta">
            <span class="user-name">{{ authStore.user.username }}</span>
            <span class="user-role">{{ authStore.user.role || '' }}</span>
          </div>
          <button class="user-logout" @click="logout" title="Logout">
            <Icon name="log-out" :size="14" />
          </button>
        </div>
      </div>
    </aside>

    <main class="main-content">
      <router-view />
    </main>

    <ToastContainer />
    <ConfirmDialog />
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import nodesService from '../services/nodes'
import api from '../services/api'
import Icon from '../components/ui/Icon.vue'
import ToastContainer from '../components/ui/ToastContainer.vue'
import ConfirmDialog from '../components/ui/ConfirmDialog.vue'

const authStore = useAuthStore()
const router = useRouter()
const refreshing = ref(false)
const systemMode = ref<'full' | 'lb'>('full')

async function refreshData() {
  if (refreshing.value) return
  refreshing.value = true
  try {
    await nodesService.fetchNodes?.()
  } catch {
    /* best-effort */
  } finally {
    refreshing.value = false
  }
}

async function fetchSystemMode() {
  try {
    const res = await api.get('/health')
    if (res.data?.mode === 'lb') systemMode.value = 'lb'
  } catch {
    /* default full */
  }
}

function logout() {
  authStore.logout()
  router.push('/login')
}

onMounted(fetchSystemMode)
</script>

<style scoped>
.app-layout {
  display: flex;
  min-height: 100vh;
  background: var(--color-bg-body);
}

.sidebar {
  width: 240px;
  background: var(--color-bg-surface);
  border-right: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  position: fixed;
  height: 100vh;
  z-index: 100;
}

.brand {
  padding: var(--space-4) var(--space-4);
  display: flex;
  align-items: center;
  gap: var(--space-2);
  border-bottom: 1px solid var(--color-border);
}
.brand-logo {
  height: 28px;
  width: auto;
  border-radius: var(--radius-sm);
}
.brand-text {
  display: flex;
  flex-direction: column;
}
.brand-name {
  font-weight: 700;
  font-size: 0.95rem;
  letter-spacing: -0.01em;
  color: var(--color-text-primary);
}
.brand-tag {
  font-size: 0.65rem;
  color: var(--color-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.nav {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-3) var(--space-2);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.nav-group {
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.nav-group-title {
  text-transform: uppercase;
  font-size: 0.65rem;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: var(--color-text-tertiary);
  padding: var(--space-2) var(--space-2) 6px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 10px;
  border: 0;
  background: none;
  border-radius: var(--radius-sm);
  color: var(--color-text-secondary);
  cursor: pointer;
  font-weight: 500;
  font-size: 0.84rem;
  text-decoration: none;
  text-align: left;
  width: 100%;
  transition: background 0.12s, color 0.12s;
}
.nav-item:hover:not(:disabled) {
  background: var(--color-bg-hover);
  color: var(--color-text-primary);
}
.nav-item.active {
  background: var(--color-primary-dim);
  color: var(--color-primary);
  font-weight: 600;
}
.nav-item :deep(svg) {
  flex-shrink: 0;
}
.nav-item:disabled {
  opacity: 0.6;
  cursor: progress;
}

.sidebar-foot {
  padding: var(--space-2);
  border-top: 1px solid var(--color-border);
}
.user-chip {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 6px;
  background: var(--color-bg-element);
  border-radius: var(--radius-sm);
}
.user-avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--color-bg-hover);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-text-secondary);
  flex-shrink: 0;
}
.user-meta {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.user-name {
  font-size: 0.82rem;
  color: var(--color-text-primary);
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.user-role {
  font-size: 0.68rem;
  color: var(--color-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}
.user-logout {
  background: none;
  border: 0;
  color: var(--color-text-secondary);
  cursor: pointer;
  padding: 4px;
  border-radius: var(--radius-sm);
}
.user-logout:hover {
  color: var(--color-danger-fg);
  background: var(--color-bg-hover);
}

.main-content {
  flex: 1;
  margin-left: 240px;
  padding: var(--space-5);
  min-height: 100vh;
}

.spin {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

@media (max-width: 768px) {
  .sidebar {
    width: 220px;
  }
  .main-content {
    margin-left: 220px;
    padding: var(--space-4);
  }
}
</style>
