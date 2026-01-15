<template>
  <div class="login-wrapper">
    <div class="login-box card">
      <div class="brand-header">
        <img src="/images/domarc-logo.png" alt="Domarc" class="logo-img">
        <h1>DA-PXREPL</h1>
      </div>
      
      <p class="subtitle" v-if="setupRequired">Setup Iniziale</p>
      <p class="subtitle" v-else>Backup & Replica per Proxmox</p>

      <div v-if="loginError" class="alert alert-danger">
        {{ loginError }}
      </div>
      
      <!-- SETUP FORM -->
      <form v-if="setupRequired" @submit.prevent="doSetup">
        <div class="form-group">
            <label>Username Admin</label>
            <input type="text" class="form-input" v-model="setupForm.username" placeholder="admin" required>
        </div>
        <div class="form-group">
            <label>Email</label>
            <input type="email" class="form-input" v-model="setupForm.email" placeholder="admin@example.com" required>
        </div>
        <div class="form-group">
            <label>Password</label>
            <input type="password" class="form-input" v-model="setupForm.password" placeholder="••••••••" required>
        </div>
        <div class="form-group">
            <label>Nome Completo</label>
            <input type="text" class="form-input" v-model="setupForm.full_name" placeholder="Administrator">
        </div>
        <button type="submit" class="btn btn-primary w-full" :disabled="loading">
          {{ loading ? 'Configurazione in corso...' : 'Crea Account' }}
        </button>
      </form>

      <!-- LOGIN FORM -->
      <form v-else @submit.prevent="doLogin">
        <div class="form-group">
            <label>Username</label>
            <input type="text" class="form-input" v-model="loginForm.username" placeholder="admin" required>
        </div>
        <div class="form-group">
            <label>Password</label>
            <input type="password" class="form-input" v-model="loginForm.password" placeholder="••••••••" required>
        </div>
        
        <div class="form-group" v-if="realms.length > 1">
            <label>Autenticazione</label>
            <select class="form-input" v-model="loginForm.realm">
                <option v-for="r in realms" :key="r.realm" :value="r.realm">
                    {{ r.comment || r.realm }}
                </option>
            </select>
        </div>

        <button type="submit" class="btn btn-primary w-full" :disabled="loading">
            {{ loading ? 'Accesso in corso...' : 'Accedi' }}
        </button>
      </form>
      
      <div class="footer-info">
        v{{ appVersion }}
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { useRouter } from 'vue-router';
import { useAuthStore } from '../stores/auth';

// State
const setupRequired = ref(false);
const loginError = ref('');
const loading = ref(false);
const appVersion = ref('3.5.0');
const realms = ref([{ realm: 'pam', comment: 'Linux PAM' }]);

const setupForm = ref({ username: '', email: '', password: '', full_name: '' });
const loginForm = ref({ username: '', password: '', realm: 'pam' });

const router = useRouter();
const authStore = useAuthStore();

onMounted(async () => {
    // Check auth, maybe redirect if already logged in?
    if (authStore.isAuthenticated) {
        router.push({ name: 'dashboard' });
        return;
    }

  try {
      await authStore.fetchRealms();
      if (authStore.realms.length > 0) {
          realms.value = authStore.realms;
          const pam = realms.value.find(r => r.realm === 'pam');
          loginForm.value.realm = pam ? pam.realm : (realms.value[0]?.realm || 'pam');
      }
  } catch (e) {
      console.warn("Could not fetch realms", e);
  }
});

// Actions
const doLogin = async () => {
    loading.value = true;
    loginError.value = '';
    try {
        await authStore.login(loginForm.value);
        router.push({ name: 'dashboard' });
    } catch (e: any) {
        console.error(e);
        loginError.value = e.response?.data?.detail || 'Credenziali non valide o errore server.';
    } finally {
        loading.value = false;
    }
};

const doSetup = async () => {
    // Placeholder
    alert("Setup non ancora implementato");
};
</script>

<style scoped>
.login-wrapper {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
    background-color: var(--color-bg-body);
    background-image: 
        radial-gradient(at 0% 0%, rgba(88, 166, 255, 0.1) 0px, transparent 50%), 
        radial-gradient(at 100% 100%, rgba(35, 134, 54, 0.05) 0px, transparent 50%);
}

.login-box {
    width: 100%;
    max-width: 400px;
    padding: 3rem 2.5rem;
    border-color: var(--color-border);
    background: rgba(22, 27, 34, 0.95); /* surface color with opacity */
    backdrop-filter: blur(10px);
}

.brand-header {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 12px;
    margin-bottom: 0.5rem;
}

.logo-img {
    height: 48px;
    width: auto;
    border-radius: 4px;
}

.brand-header h1 {
    font-size: 1.5rem;
    margin: 0;
    color: var(--color-text-primary);
}

.subtitle {
    text-align: center;
    color: var(--color-text-secondary);
    margin-bottom: 2rem;
    font-size: 0.875rem;
}

.form-group {
    margin-bottom: 1.25rem;
}

.form-group label {
    display: block;
    margin-bottom: 0.5rem;
    font-size: 0.875rem;
    font-weight: 500;
    color: var(--color-text-secondary);
}

.footer-info {
    margin-top: 2rem;
    text-align: center;
    font-size: 0.75rem;
    color: var(--color-text-tertiary);
}

.alert {
    padding: 12px;
    border-radius: var(--radius-md);
    margin-bottom: 1.5rem;
    font-size: 0.875rem;
}
.alert-danger {
    background: var(--color-danger-dim);
    color: var(--color-danger-fg);
    border: 1px solid rgba(248, 81, 73, 0.2);
}
</style>
