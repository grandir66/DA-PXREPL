<template>
 <div class="settings-page">
 <PageHeader
 title="Impostazioni"
 subtitle="Configurazione sistema, utenti e sicurezza"
 icon="settings"
 />

 <div class="settings-layout">
 <!-- Sidebar Navigation -->
 <div class="settings-sidebar">
 <div class="nav-item" :class="{ active: activeTab === 'general' }" @click="activeTab = 'general'">
 🛠️ Generale
 </div>
 <div class="nav-item" :class="{ active: activeTab === 'notifications' }" @click="activeTab = 'notifications'">
 🔔 Notifiche
 </div>
 <div class="nav-item" :class="{ active: activeTab === 'users' }" @click="activeTab = 'users'" v-if="isAdmin">
 👥 Utenti
 </div>
 <div class="nav-item" :class="{ active: activeTab === 'profile' }" @click="activeTab = 'profile'">
 👤 Profilo
 </div>
 <div class="nav-item" :class="{ active: activeTab === 'certs' }" @click="activeTab = 'certs'" v-if="isAdmin">
 🔒 Certificati SSL
 </div>
 <div class="nav-item" :class="{ active: activeTab === 'ssh' }" @click="activeTab = 'ssh'" v-if="isAdmin">
 🔑 Chiavi SSH
 </div>
 </div>

 <!-- Content Area -->
 <div class="settings-content">
 <!-- GENERAL TAB -->
 <div v-if="activeTab === 'general'" class="card">
 <h3>Autenticazione Sistema</h3>
 <div class="card-body" v-if="authConfig">
 <div class="form-group">
 <label>Metodo Autenticazione</label>
 <select v-model="authConfig.auth_method" class="form-input">
 <option value="proxmox">Proxmox PVE (PAM/PVE)</option>
 <option value="local">Locale</option>
 </select>
 </div>
 <button class="btn btn-primary btn-sm mt-2" @click="saveAuth">Salva Auth</button>
 </div>
 </div>

 <!-- NOTIFICATIONS TAB -->
 <div v-if="activeTab === 'notifications'" class="card">
 <div class="card-header">
 <h3>Configurazione Notifiche</h3>
 <div style="display: flex; gap: 12px; align-items: center;">
 <button class="btn btn-secondary btn-sm" @click="testNotification('email')">Test Email</button>
 <button class="btn btn-primary btn-sm" @click="saveNotifications" :disabled="saving">
 {{ saving ? 'Salvataggio...' : 'Salva Configurazione' }}
 </button>
 </div>
 </div>
 <div class="card-body" v-if="notifications">
 
 <!-- SMTP Section -->
 <div class="form-section">
 <div class="section-title">
 <h4>Configurazione Server SMTP</h4>
 <label class="checkbox-label">
 <input type="checkbox" v-model="notifications.smtp_enabled"> Abilita Notifiche Email
 </label>
 </div>
 
 <div v-if="notifications.smtp_enabled" class="animate-fade">
 <div class="grid-2">
 <div class="form-group">
 <label>Server SMTP</label>
 <input type="text" v-model="notifications.smtp_host" class="form-input" placeholder="smtp.example.com">
 </div>
 <div class="form-group">
 <label>Porta</label>
 <input type="number" v-model.number="notifications.smtp_port" class="form-input" placeholder="587">
 </div>
 </div>
 
 <div class="grid-2">
 <div class="form-group">
 <label>Username SMTP</label>
 <input type="text" v-model="notifications.smtp_user" class="form-input" placeholder="user@example.com">
 </div>
 <div class="form-group">
 <label>Password SMTP</label>
 <input type="password" v-model="notifications.smtp_password" class="form-input" placeholder="••••••••">
 </div>
 </div>

 <div class="form-group">
 <label class="checkbox-label">
 <input type="checkbox" v-model="notifications.smtp_tls"> Usa TLS (STARTTLS)
 </label>
 <div class="help-text">
 • Porta 25: disabilita TLS<br>
 • Porta 465: SSL automatico<br>
 • Porta 587: abilita TLS (STARTTLS)
 </div>
 </div>

 <h4 class="mt-4">Mittente e Destinatari</h4>
 
 <div class="grid-2">
 <div class="form-group">
 <label>Email Mittente (From)</label>
 <input type="text" v-model="notifications.smtp_from" class="form-input" placeholder="noreply@example.com">
 </div>
 <div class="form-group">
 <label>Email Destinatari (To)</label>
 <input type="text" v-model="notifications.smtp_to" class="form-input" placeholder="admin@example.com">
 <span class="help-text">Separare più indirizzi con virgola</span>
 </div>
 </div>

 <div class="form-group">
 <label>Prefisso Oggetto Email</label>
 <input type="text" v-model="notifications.smtp_subject_prefix" class="form-input" placeholder="[DAPX]">
 </div>

 </div>
 </div>

 <hr class="separator">

 <!-- Triggers Section -->
 <div class="form-section">
 <h4 class="trigger-title">⚠️ Quando Notificare</h4>
 <div class="triggers-grid">
 <label class="trigger-option error">
 <input type="checkbox" v-model="notifications.notify_on_failure">
 <span>❌ Notifica su errori</span>
 </label>
 <label class="trigger-option warning">
 <input type="checkbox" v-model="notifications.notify_on_warning">
 <span>⚠️ Notifica su warning</span>
 </label>
 <label class="trigger-option success">
 <input type="checkbox" v-model="notifications.notify_on_success">
 <span>✅ Notifica su successi</span>
 </label>
 </div>
 </div>

 <hr class="separator">

 <!-- Daily Summary Placeholder -->
 <div class="form-section">
 <div style="display: flex; justify-content: space-between; align-items: center;">
 <h4>📧 Riepilogo Giornaliero</h4>
 <button class="btn btn-xs btn-secondary" @click="sendDailySummary">Invia ORA</button>
 </div>
 <p class="text-secondary text-sm mb-2">Ricevi ogni giorno un riepilogo con lo stato di tutti i job.</p>
 </div>
 </div>
 <div v-else class="loading-state">Caricamento impostazioni...</div>
 </div>

 <!-- USERS TAB -->
 <div v-if="activeTab === 'users'" class="card">
 <UserManagement />
 </div>

 <!-- PROFILE TAB -->
 <div v-if="activeTab === 'profile'" class="card">
 <UserProfile />
 </div>

 <!-- CERTS TAB -->
 <div v-if="activeTab === 'certs'" class="card">
 <Certificates />
 </div>

 <!-- SSH KEYS TAB -->
 <div v-if="activeTab === 'ssh'" class="card">
 <SSHKeys />
 </div>
 </div>
 </div>
 </div>
</template>

<script setup lang="ts">
import { useToast, errorMessage } from '../stores/toast';
import { ref, onMounted, computed } from 'vue';
import Icon from '../components/ui/Icon.vue';
import settingsService, { type NotificationConfig, type AuthConfig } from '../services/settings';
import apiClient from '../services/api';
import authService from '../services/auth';
import PageHeader from '../components/ui/PageHeader.vue';
import UserManagement from './settings/UserManagement.vue';
import UserProfile from './settings/UserProfile.vue';
import Certificates from './settings/Certificates.vue';
import SSHKeys from './settings/SSHKeys.vue';

const toast = useToast()

const activeTab = ref('general');
const notifications = ref<NotificationConfig | null>(null);
const authConfig = ref<AuthConfig | null>(null);
const saving = ref(false);
const currentUser = ref<any>(null);

const isAdmin = computed(() => currentUser.value?.role === 'admin');

onMounted(async () => {
 try {
 // Load user info for permissions
 const userRes = await authService.getMe();
 currentUser.value = userRes.data;

 // Load settings
 const [notifRes, authRes] = await Promise.all([
 settingsService.getNotificationConfig(),
 settingsService.getAuthConfig()
 ]);
 notifications.value = notifRes.data;
 authConfig.value = authRes.data;
 } catch (e) {
 toast.error('Errore caricamento impostazioni', errorMessage(e));
 }
});

const saveNotifications = async () => {
 if (!notifications.value) return;
 saving.value = true;
 try {
 await settingsService.updateNotificationConfig(notifications.value);
 toast.success('Impostazioni salvate');
 } catch (e) {
 toast.error('Errore salvataggio');
 } finally {
 saving.value = false;
 }
};

const saveAuth = async () => {
 if (!authConfig.value) return;
 try {
 await settingsService.updateAuthConfig(authConfig.value);
 toast.success('Impostazioni Auth salvate');
 } catch (e) {
 toast.error('Errore salvataggio');
 }
};

const testNotification = async (channel: string) => {
 try {
 await settingsService.testNotification(channel);
 toast.success(`Test ${channel} inviato`);
 } catch (e: any) {
 toast.error('Errore test', errorMessage(e));
 }
}

const sendDailySummary = async () => {
 try {
 await apiClient.post('/settings/notifications/send-daily-summary');
 toast.success("Riepilogo giornaliero inviato");
 } catch (e: any) {
 toast.error("Errore invio riepilogo", errorMessage(e));
 }
};
</script>

<style scoped>
.settings-layout { display: flex; gap: 24px; align-items: flex-start; }
.settings-sidebar { width: 220px; flex-shrink: 0; background: var(--bg-card); border-radius: 8px; border: 1px solid var(--border-color); overflow: hidden; }
.nav-item { padding: 12px 16px; cursor: pointer; transition: background 0.2s; color: var(--text-secondary); border-left: 3px solid transparent; }
.nav-item:hover { background: rgba(255,255,255,0.05); color: var(--text-primary); }
.nav-item.active { background: rgba(0, 184, 148, 0.1); color: #00b894; border-left-color: #00b894; font-weight: 600; }

.settings-content { flex: 1; min-width: 0; }
.form-section { margin-bottom: 24px; }
.section-title { margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center; }
.form-group { margin-bottom: 16px; }
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 16px; }
.loading-state { padding: 40px; text-align: center; color: var(--text-secondary); }
.help-text { font-size: 0.8em; color: var(--text-secondary); margin-top: 4px; line-height: 1.4; }
.checkbox-label { display: flex; align-items: center; gap: 8px; cursor: pointer; user-select: none; }
.separator { border: 0; border-top: 1px solid var(--border-color); margin: 24px 0; }
.mt-4 { margin-top: 24px; }
.mt-2 { margin-top: 8px; }
.btn-xs { padding: 2px 8px; font-size: 0.75em; }

/* Triggers */
.triggers-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-top: 12px; }
.trigger-option { 
 display: flex; align-items: center; gap: 8px; padding: 12px; 
 border-radius: 8px; border: 1px solid var(--border-color);
 cursor: pointer; transition: all 0.2s;
}
.trigger-option:hover { background: rgba(255,255,255,0.05); }
.trigger-option.error span { color: #ff5252; font-weight: 500; }
.trigger-option.warning span { color: #ffb300; font-weight: 500; }
.trigger-option.success span { color: #00b894; font-weight: 500; }

.animate-fade {
 animation: fadeIn 0.3s ease-out;
}
@keyframes fadeIn {
 from { opacity: 0; transform: translateY(-5px); }
 to { opacity: 1; transform: translateY(0); }
}

@media (max-width: 768px) {
 .settings-layout { flex-direction: column; }
 .settings-sidebar { width: 100%; display: flex; overflow-x: auto; gap: 4px; padding-bottom: 8px; border: none; background: transparent; }
 .nav-item { border-radius: 4px; border-left: none; border-bottom: 2px solid transparent; white-space: nowrap; }
 .nav-item.active { border-left: none; border-bottom-color: #00b894; }
 .grid-2 { grid-template-columns: 1fr; }
}
</style>
