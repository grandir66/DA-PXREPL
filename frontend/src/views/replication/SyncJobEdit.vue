<template>
  <div class="modal-overlay" @click.self="$emit('close')">
    <div class="modal large-modal">
      <div class="modal-header">
        <div class="header-left">
            <h3>Modifica Replica: {{ job.job_name }}</h3>
            <span class="job-id-badge">{{ job.id }}</span>
        </div>
        <button class="btn-icon" @click="$emit('close')">✕</button>
      </div>
      
      <div class="modal-body">
        
        <!-- Info Read-Only Section -->
        <div class="section-title">📍 Origine & Destinazione</div>
        <div class="grid-2 mb-6">
             <div class="info-card">
                <div class="label">Sorgente</div>
                <div class="value highlight">{{ job.source_node_name }}</div>
                <div class="sub-value">{{ job.source_dataset }}</div>
                <div class="sub-label" v-if="job.vm_id">VM ID: {{ job.vm_id }}</div>
             </div>
             
             <div class="info-card">
                <div class="label">Destinazione (Nodo)</div>
                <div class="value">{{ job.dest_node_name }}</div>
                <div class="form-group mt-2">
                    <label class="text-xs">Dataset Destinazione</label>
                    <input type="text" v-model="form.dest_dataset" class="form-input text-xs" :placeholder="job.dest_dataset">
                </div>
             </div>
        </div>

        <!-- Settings Section -->
        <div class="section-title">⚙️ Configurazione</div>
        <div class="form-container">
            <!-- Row 1 -->
            <div class="grid-3">
                 <div class="form-group">
                    <label>Schedule</label>
                    <select v-model="cronPreset" @change="onCronPreset" class="form-input">
                        <option value="manual">🔒 Manuale</option>
                        <option value="hourly">⏰ Ogni ora</option>
                        <option value="daily">📅 Giornaliero</option>
                        <option value="custom">✏️ Personalizzato</option>
                    </select>
                </div>
                <div class="form-group" v-if="cronPreset === 'custom'">
                     <label>Custom Cron</label>
                     <input type="text" v-model="form.schedule" class="form-input">
                </div>
                 <div class="form-group">
                    <label>Compressione</label>
                    <select v-model="form.compress" class="form-input">
                        <option value="lz4">LZ4 (Veloce)</option>
                        <option value="zstd">ZSTD (Bilanciato)</option>
                        <option value="gzip">GZIP</option>
                        <option value="none">Nessuna</option>
                    </select>
                </div>
            </div>

            <!-- Row 2 -->
             <div class="grid-3 mt-4">
                 <div class="form-group checkbox-group">
                     <label class="checkbox-label">
                         <input type="checkbox" v-model="form.recursive">
                         <span class="check-text">Ricorsivo (-r)</span>
                     </label>
                     <div class="help-text">Include snapshot e descendent</div>
                 </div>
                 
                 <div class="form-group checkbox-group">
                     <label class="checkbox-label">
                        <input type="checkbox" v-model="form.enabled">
                        <span class="check-text">Abilitato</span>
                     </label>
                      <div class="help-text">Attiva/Disattiva esecuzione automatica</div>
                 </div>
            </div>
            
            <div class="separator mt-4 mb-4"></div>

            <!-- VM Registration -->
            <div class="section-title">🖥️ Registrazione VM</div>
            <div class="grid-2">
                 <div class="form-group checkbox-group centered">
                     <label class="checkbox-label">
                        <input type="checkbox" v-model="form.register_vm">
                        <span class="check-text">Registra VM su destinazione</span>
                     </label>
                 </div>
                 <div class="form-group">
                     <label>ID VM Destinazione (Opzionale)</label>
                     <input type="number" v-model="form.dest_vm_id" class="form-input" placeholder="Auto">
                     <div class="help-text">Lascia vuoto per auto-assegnazione</div>
                 </div>
            </div>
        </div>

      </div>
      
      <div class="modal-footer">
        <button class="btn btn-secondary" @click="$emit('close')">Annulla</button>
        <button class="btn btn-primary" @click="save" :disabled="saving">
            {{ saving ? 'Salvataggio...' : 'Salva Modifiche' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue';
import syncJobsService, { type SyncJob } from '../../services/syncJobs';

const props = defineProps<{
    job: SyncJob
}>();

const emit = defineEmits(['close', 'saved']);

const saving = ref(false);
const cronPreset = ref('manual');

const form = reactive({
    dest_dataset: '',
    schedule: '',
    compress: 'lz4',
    recursive: false,
    enabled: true,
    register_vm: false,
    dest_vm_id: null as number | null
});

onMounted(() => {
    // Init form with job data
    form.dest_dataset = props.job.dest_dataset;
    form.schedule = props.job.schedule || '';
    form.compress = props.job.compress || 'lz4';
    form.recursive = props.job.recursive;
    form.enabled = props.job.enabled !== false;
    
    // Check preset
    if (!form.schedule) cronPreset.value = 'manual';
    else if (form.schedule === '0 * * * *') cronPreset.value = 'hourly';
    else if (form.schedule === '0 0 * * *') cronPreset.value = 'daily';
    else cronPreset.value = 'custom';

    // VM fields - SyncJob might not have register_vm if it's a raw job, 
    // but the backend handles it via update if supported.
    // If props.job doesn't have these, we default.
    // Assuming backend returns these fields if present in DB column or extra_props
});

const onCronPreset = () => {
    if (cronPreset.value === 'manual') form.schedule = '';
    else if (cronPreset.value === 'hourly') form.schedule = '0 * * * *';
    else if (cronPreset.value === 'daily') form.schedule = '0 0 * * *';
};

const save = async () => {
    saving.value = true;
    try {
        await syncJobsService.updateJob(props.job.id, {
            dest_dataset: form.dest_dataset,
            schedule: form.schedule,
            compress: form.compress,
            recursive: form.recursive,
            enabled: form.enabled,
            // Only send VM props if applicable/changed? Backend will handle partial updates.
        });
        emit('saved');
        emit('close');
    } catch (e: any) {
        alert('Errore salvataggio: ' + (e.response?.data?.detail || e.message));
    } finally {
        saving.value = false;
    }
};
</script>

<style scoped>
.modal-overlay {
    position: fixed; top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(0,0,0,0.7);
    display: flex; align-items: center; justify-content: center;
    z-index: 1000;
 backdrop-filter: blur(2px);
}
.modal {
    background: var(--bg-card);
    background-color: #1a1a2e;
    padding: 0;
    border-radius: 12px;
    width: 90%; max-width: 800px; /* Wider modal */
    border: 1px solid var(--border-color);
    display: flex;
    flex-direction: column;
    max-height: 90vh;
}
.modal-header { 
    display: flex; justify-content: space-between; align-items: center; 
    padding: 20px 24px;
    border-bottom: 1px solid var(--border-color);
    background: rgba(0,0,0,0.2);
}
.header-left { display: flex; align-items: center; gap: 12px; }
.job-id-badge { background: rgba(255,255,255,0.1); padding: 2px 6px; border-radius: 4px; font-size: 0.75rem; font-family: monospace; }
.modal-body { padding: 24px; overflow-y: auto; }
.modal-footer {
    display: flex; justify-content: flex-end; gap: 12px; 
    padding: 20px 24px;
    border-top: 1px solid var(--border-color);
    background: rgba(0,0,0,0.2);
}

.section-title {
    font-size: 0.9rem; font-weight: 600; color: var(--accent-primary);
    margin-bottom: 12px; text-transform: uppercase; letter-spacing: 0.5px;
}

.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
.grid-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 20px; }

.info-card {
    background: rgba(255,255,255,0.03);
    padding: 16px; border-radius: 8px; border: 1px solid var(--border-color);
}
.info-card .label { font-size: 0.75rem; color: var(--text-secondary); margin-bottom: 4px; text-transform: uppercase; }
.info-card .value { font-size: 1.1rem; font-weight: 600; color: white; margin-bottom: 2px; }
.info-card .value.highlight { color: var(--accent-primary); }
.info-card .sub-value { font-size: 0.9rem; color: #ccc; font-family: monospace; }
.info-card .sub-label { font-size: 0.8rem; color: #888; margin-top: 4px; }

.form-group { display: flex; flex-direction: column; gap: 6px; }
.form-group label { font-size: 0.85rem; color: var(--text-secondary); }
.form-input { 
    padding: 10px; border-radius: 6px; border: 1px solid var(--border-color); 
    background: rgba(0,0,0,0.2); color: white; font-family: inherit;
}
.form-input:focus { border-color: var(--accent-primary); outline: none; }
.help-text { font-size: 0.75rem; color: var(--text-secondary); }
.text-xs { font-size: 0.8rem; }

.checkbox-group { justify-content: center; }
.checkbox-label { display: flex; align-items: center; gap: 8px; cursor: pointer; }
.checkbox-label input[type="checkbox"] { width: 16px; height: 16px; accent-color: var(--accent-primary); }
.check-text { font-weight: 500; }
.centered { align-items: flex-start; }

.separator { height: 1px; background: var(--border-color); opacity: 0.5; }

.btn { padding: 10px 20px; border-radius: 6px; border: none; cursor: pointer; font-weight: 600; transition: all 0.2s; }
.btn-primary { background: var(--accent-primary); color: black; }
.btn-primary:hover { filter: brightness(1.1); transform: translateY(-1px); }
.btn-secondary { background: transparent; border: 1px solid var(--border-color); color: white; }
.btn-secondary:hover { background: rgba(255,255,255,0.05); }

.btn-icon { background: none; border: none; color: #888; font-size: 1.5rem; cursor: pointer; }
.btn-icon:hover { color: white; }
</style>
      

