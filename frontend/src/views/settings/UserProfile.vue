<template>
    <div class="user-profile">
        <h3>👤 Il Tuo Profilo</h3>
        
        <div class="card-section mt-4">
            <h4>Cambia Password</h4>
            <div class="form-group">
                <label>Password Attuale</label>
                <input v-model="form.current_password" type="password" class="form-input">
            </div>
            <div class="form-group">
                <label>Nuova Password</label>
                <input v-model="form.new_password" type="password" class="form-input">
            </div>
            <div class="form-group">
                <label>Conferma Nuova Password</label>
                <input v-model="form.confirm_password" type="password" class="form-input">
            </div>
            
            <div class="mt-4">
                <button class="btn btn-primary" @click="updatePassword" :disabled="loading">
                    {{ loading ? 'Updating...' : 'Aggiorna Password' }}
                </button>
            </div>
        </div>
    </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue';
import authService from '../../services/auth';

const loading = ref(false);
const form = reactive({
    current_password: '',
    new_password: '',
    confirm_password: ''
});

const updatePassword = async () => {
    if (form.new_password !== form.confirm_password) {
        alert("Le nuove password non coincidono");
        return;
    }
    
    loading.value = true;
    try {
        await authService.changePassword({
            current_password: form.current_password,
            new_password: form.new_password
        });
        alert("Password aggiornata con successo");
        form.current_password = '';
        form.new_password = '';
        form.confirm_password = '';
    } catch (e: any) {
        alert('Errore: ' + (e.response?.data?.detail || e.message));
    } finally {
        loading.value = false;
    }
};
</script>

<style scoped>
.mt-4 { margin-top: 16px; }
.form-group { margin-bottom: 12px; display: flex; flex-direction: column; gap: 6px; }
.form-input { padding: 8px; border-radius: 4px; background: var(--bg-input); border: 1px solid var(--border-color); color: var(--text-primary); width: 100%; max-width: 400px; }
.card-section { padding: 16px; background: rgba(255,255,255,0.05); border-radius: 8px; }
</style>
