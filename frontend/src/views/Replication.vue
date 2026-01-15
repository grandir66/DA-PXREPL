<template>
  <div class="replication-view">
    <div class="header-section">
      <div>
        <h1>Gestione Repliche</h1>
        <p class="subtitle">Sistema unificato per Syncoid, PVE Native e PBS Recovery</p>
      </div>
      <div class="actions">
        <button class="btn-primary" @click="openNewReplication">
          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/></svg>
          Nuova Replica
        </button>
      </div>
    </div>

    <!-- Stats Cards -->
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-label">Job Attivi</div>
        <div class="stat-value">{{ activeJobsCount }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Successi (24h)</div>
        <div class="stat-value text-success">{{ successCount }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Fallimenti (24h)</div>
        <div class="stat-value text-danger">{{ failureCount }}</div>
      </div>
    </div>

    <!-- Tabs for different job types -->
    <div class="tabs">
      <button 
        v-for="tab in tabs" 
        :key="tab.id"
        class="tab-btn"
        :class="{ active: activeTab === tab.id }"
        @click="activeTab = tab.id"
      >
        {{ tab.label }}
      </button>
    </div>

    <!-- Content based on tab -->
    <div class="tab-content">
      <SyncJobs v-if="activeTab === 'syncoid'" ref="syncJobsRef" @edit="openEditWizard" />
      <RecoveryJobs v-else-if="activeTab === 'pbs'" ref="pbsJobsRef" />
      <PVEReplicationJobs v-else-if="activeTab === 'pve'" ref="pveJobsRef" />
    </div>

    <!-- Replication Wizard Modal -->
    <ReplicationWizard 
      v-if="showWizard" 
      :editing-job="selectedEditingJob"
      @close="closeWizard" 
      @created="onJobCreated"
    />

    <SyncJobEdit
      v-if="showEditModal && selectedEditingJob"
      :job="selectedEditingJob"
      @close="closeEditModal"
      @saved="onJobSaved"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import SyncJobs from './replication/SyncoidJobs.vue';
import RecoveryJobs from './replication/PBSJobs.vue';
import PVEReplicationJobs from './replication/PVEReplicationJobs.vue';
import ReplicationWizard from './replication/ReplicationWizard.vue';
import SyncJobEdit from './replication/SyncJobEdit.vue';

const activeTab = ref('syncoid');

const showWizard = ref(false);
const showEditModal = ref(false);
const selectedEditingJob = ref(null);

const syncJobsRef = ref();
const pbsJobsRef = ref();
const pveJobsRef = ref();

const tabs = [
  { id: 'syncoid', label: 'Syncoid (ZFS)' },
  { id: 'pve', label: 'PVE Native' },
  { id: 'pbs', label: 'PBS Replication' }
];

const activeJobsCount = ref(0);
const successCount = ref(0);
const failureCount = ref(0);

const openNewReplication = () => {
    selectedEditingJob.value = null;
    showWizard.value = true;
};

const openEditWizard = (job: any) => {
    selectedEditingJob.value = job;
    if (activeTab.value === 'syncoid') {
        showEditModal.value = true;
    } else {
        // For other types, potentially use wizard or their own edit modals
        // Currently fallback to Wizard or nothing if Wizard doesn't support edit
        // For now, let's assume Wizard is only for Create
        alert("Modifica non ancora implementata per questo tipo di job");
    }
};

const closeWizard = () => {
    showWizard.value = false;
    selectedEditingJob.value = null;
};

const closeEditModal = () => {
    showEditModal.value = false;
    selectedEditingJob.value = null;
};

const onJobCreated = () => {
    closeWizard();
    refreshJobs();
};

const onJobSaved = () => {
  closeEditModal();
  refreshJobs();
};

const refreshJobs = () => {
    if (activeTab.value === 'syncoid' && syncJobsRef.value) syncJobsRef.value.loadJobs();
    else if (activeTab.value === 'pve' && pveJobsRef.value) pveJobsRef.value.loadJobs();
    else if (activeTab.value === 'pbs' && pbsJobsRef.value) pbsJobsRef.value.loadJobs();
}

onMounted(() => {
  // Load summary stats logic here
});
</script>

<style scoped>
.replication-view {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.header-section {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.subtitle {
  color: var(--text-secondary);
  font-size: 0.9rem;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 16px;
}

.stat-card {
  background: var(--bg-secondary);
  padding: 20px;
  border-radius: 12px;
  border: 1px solid var(--border-color);
}

.stat-label {
  font-size: 0.8rem;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 8px;
}

.stat-value {
  font-size: 2rem;
  font-weight: 700;
}

.tabs {
  display: flex;
  gap: 8px;
  border-bottom: 1px solid var(--border-color);
  padding-bottom: 0;
}

.tab-btn {
  padding: 12px 24px;
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--text-secondary);
  cursor: pointer;
  font-weight: 600;
  transition: all 0.2s;
}

.tab-btn:hover {
  color: var(--text-primary);
}

.tab-btn.active {
  color: var(--accent-primary);
  border-bottom-color: var(--accent-primary);
}

.tab-content {
  background: var(--bg-secondary);
  border-radius: 12px;
  border: 1px solid var(--border-color);
  padding: 0; /* Let children handle padding or provide it if needed */
  min-height: 400px;
}

.actions .btn-primary {
  display: flex;
  align-items: center;
  gap: 8px;
}

.actions svg {
  width: 20px;
  height: 20px;
}
</style>
