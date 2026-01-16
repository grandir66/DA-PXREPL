<template>
  <div class="app-layout">
    <!-- Sidebar -->
    <aside class="sidebar">
      <div class="logo">
        <img src="/images/domarc-logo.png" alt="Domarc" class="logo-img">
        <div class="logo-text">DA-PXREPL</div>
      </div>

      <nav class="nav-menu">
        <div class="nav-section">
          <div class="nav-section-title">Principale</div>
          <router-link :to="{ name: 'dashboard' }" class="nav-item" active-class="active">
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zM16 13a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z"/></svg>
            Dashboard
          </router-link>
          <router-link :to="{ name: 'nodes' }" class="nav-item" active-class="active">
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2m-2-4h.01M17 16h.01"/></svg>
            Nodi
          </router-link>
          <router-link v-if="systemMode === 'full'" :to="{ name: 'vms' }" class="nav-item" active-class="active">
             <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/></svg>
             Virtual Machines
          </router-link>
          <router-link :to="{ name: 'load-balancer' }" class="nav-item" active-class="active">
             <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 6l3 11 11-3-3-11L3 6zm0 0l3 1m11 14l-3-1m0 0l-8-3m8 3l3 1-3-1m14-3l-3 1-3-1m0 0l-3-1"/></svg>
             Load Balancer
          </router-link>
        </div>

        <div class="nav-section" v-if="systemMode === 'full'">
          <div class="nav-section-title">Storage & Backup</div>
          <router-link :to="{ name: 'replication' }" class="nav-item" active-class="active">
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4"/></svg>
            Gestione Repliche
          </router-link>
          <router-link :to="{ name: 'backup-jobs' }" class="nav-item" active-class="active">
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"/></svg>
            Backup PBS (PVE)
          </router-link>
          <router-link :to="{ name: 'migration-jobs' }" class="nav-item" active-class="active">
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4"/></svg>
            Migrazioni
          </router-link>
          <router-link :to="{ name: 'host-backup' }" class="nav-item" active-class="active">
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 8h14M5 8a2 2 0 110-4h14a2 2 0 110 4M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8m-9 4h4"/></svg>
            Host Backup
          </router-link>
        </div>

        <div class="nav-section">
          <div class="nav-section-title">System</div>
          <div class="nav-item" @click="refreshData">
             <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" :class="{ 'spin': refreshing }"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" /></svg>
             {{ refreshing ? 'Aggiornamento...' : 'Aggiorna Dati' }}
          </div>
          <router-link :to="{ name: 'logs' }" class="nav-item" active-class="active">
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
            System Logs
          </router-link>
          <router-link :to="{ name: 'settings' }" class="nav-item" active-class="active">
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/></svg>
            Impostazioni
          </router-link>
          <router-link :to="{ name: 'updates' }" class="nav-item" active-class="active">
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"/></svg>
            Aggiornamenti
          </router-link>
          <router-link :to="{ name: 'config-backup' }" class="nav-item" active-class="active">
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-3m-1 4l-3 3m0 0l-3-3m3 3V4"/></svg>
            Backup Config
          </router-link>
        </div>
        
        <div class="nav-section">
           <div class="nav-section-title">Account</div>
           <div class="nav-item" @click="logout">
             <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" /></svg>
             Logout
           </div>
        </div>
      </nav>
    </aside>

    <!-- Main Content -->
    <main class="main-content">
      <router-view></router-view>
    </main>
  </div>
</template>

<script setup lang="ts">
import { useAuthStore } from '../stores/auth';
import { useRouter } from 'vue-router';
import { ref, onMounted } from 'vue';
import nodesService from '../services/nodes';
import api from '../services/api'; // Assuming generic api client or import axios directly

const authStore = useAuthStore();
const router = useRouter();
const refreshing = ref(false);
const systemMode = ref('full'); // Default to full to avoid flashing hidden items

const refreshData = async () => {
    refreshing.value = true;
    try {
        await nodesService.fetchNodes();
        // Add other refreshes if needed, but gracefully fail if endpoint doesn't exist
    } finally {
        refreshing.value = false;
    }
};

const fetchSystemMode = async () => {
  try {
    const res = await api.get('/health'); // Use public health endpoint
    if (res.data && res.data.mode) {
      systemMode.value = res.data.mode;
    }
  } catch (e) {
    console.warn("Could not fetch system mode, defaulting to full", e);
  }
};

onMounted(() => {
  fetchSystemMode();
});

const logout = () => {
  authStore.logout();
  router.push('/login');
};
</script>

<style scoped>
/* Basic layout styles to match legacy structure */
.app-layout {
  display: flex;
  min-height: 100vh;
}

.sidebar {
  width: 260px;
  background: var(--bg-secondary); /* From legacy.css */
  border-right: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
  position: fixed;
  height: 100vh;
  z-index: 100;
}

.logo {
  padding: 24px;
  display: flex;
  align-items: center;
  gap: 12px;
  border-bottom: 1px solid var(--border-color);
}

.logo-img {
  height: 32px;
  width: auto;
  border-radius: 4px;
}

.logo-text {
  font-weight: 700;
  font-size: 1.1rem;
  letter-spacing: -0.5px;
}

.nav-menu {
  flex: 1;
  overflow-y: auto;
  padding: 24px 16px;
}

.nav-section {
  margin-bottom: 24px;
}

.nav-section-title {
  text-transform: uppercase;
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 12px;
  padding-left: 12px;
  letter-spacing: 1px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  border-radius: 8px;
  color: var(--text-secondary);
  transition: all 0.2s ease;
  cursor: pointer;
  text-decoration: none;
  font-weight: 500;
}

.nav-item:hover {
  background: rgba(255, 255, 255, 0.03);
  color: var(--text-primary);
}

.nav-item.active {
  background: rgba(0, 255, 157, 0.1);
  color: var(--accent-primary);
}

.nav-item svg {
  width: 20px; height: 20px;
}

.main-content {
  flex: 1;
  margin-left: 260px;
  padding: 32px;
}

.spin {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
