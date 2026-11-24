<template>
 <div>
 <div class="card-header">
 <h3>Syslog remoto</h3>
 <div style="display: flex; gap: 12px; align-items: center;">
 <button class="btn btn-secondary btn-sm" @click="prova" :disabled="busy || !cfg.host">Invia riga di prova</button>
 <button class="btn btn-primary btn-sm" @click="salva" :disabled="busy">{{ busy ? 'Salvataggio...' : 'Salva' }}</button>
 </div>
 </div>
 <div class="card-body" v-if="caricato">
 <p class="text-secondary text-sm mb-2">
 Manda tutto il log tecnico dell'appliance a un collettore (Wazuh, Graylog, rsyslog), una riga JSON per evento.
 Sul collettore va abilitata la ricezione syslog dall'indirizzo di questa appliance.
 </p>
 <div class="form-group">
 <label style="display: flex; gap: 8px; align-items: center;">
 <input type="checkbox" v-model="cfg.enabled" /> Invio attivo
 </label>
 </div>
 <div class="form-group">
 <label>Indirizzo del collettore</label>
 <input v-model.trim="cfg.host" class="form-input" placeholder="es. 192.168.4.44" />
 </div>
 <div style="display: flex; gap: 16px;">
 <div class="form-group" style="flex: 1;">
 <label>Porta</label>
 <input v-model.number="cfg.port" type="number" min="1" max="65535" class="form-input" />
 </div>
 <div class="form-group" style="flex: 1;">
 <label>Protocollo</label>
 <select v-model="cfg.protocol" class="form-input">
 <option value="udp">UDP</option>
 <option value="tcp">TCP</option>
 </select>
 </div>
 </div>
 <div class="form-group" v-if="stato">
 <label>Stato</label>
 <div class="text-sm">
 <strong>{{ stato.attivo ? 'Attivo' : 'Spento' }}</strong>
 <span v-if="stato.attivo"> — righe inviate: {{ stato.inviati }}, errori: {{ stato.errori }}</span>
 </div>
 <div class="text-sm text-danger" v-if="stato.ultimo_errore">
 Ultimo errore ({{ stato.ultimo_errore_quando }}): {{ stato.ultimo_errore }}
 </div>
 </div>
 </div>
 <div v-else class="loading-state">Caricamento...</div>
 </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import apiClient from '../../services/api';
import { useToast, errorMessage } from '../../stores/toast';

const toast = useToast();
const cfg = ref({ enabled: false, host: '', port: 514, protocol: 'udp' });
const stato = ref<any>(null);
const caricato = ref(false);
const busy = ref(false);

const applica = (d: any) => {
 cfg.value = { enabled: d.enabled, host: d.host, port: d.port, protocol: d.protocol };
 stato.value = d.stato;
};

onMounted(async () => {
 try {
 applica((await apiClient.get('/settings/syslog')).data);
 } catch (e) {
 toast.error('Errore caricamento syslog', errorMessage(e));
 } finally {
 caricato.value = true;
 }
});

const salva = async () => {
 busy.value = true;
 try {
 applica((await apiClient.put('/settings/syslog', cfg.value)).data);
 toast.success(cfg.value.enabled ? 'Syslog remoto acceso' : 'Syslog remoto spento');
 } catch (e) {
 toast.error('Errore salvataggio', errorMessage(e));
 } finally {
 busy.value = false;
 }
};

const prova = async () => {
 busy.value = true;
 try {
 const r = await apiClient.post('/settings/syslog/test', cfg.value);
 toast.success('Prova syslog', r.data.message);
 } catch (e) {
 toast.error('Prova fallita', errorMessage(e));
 } finally {
 busy.value = false;
 }
};
</script>
