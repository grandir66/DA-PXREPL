<template>
    <div class="user-management">
        <div class="header-actions">
            <h3>👥 Gestione Utenti</h3>
            <button class="btn btn-primary btn-sm" @click="openCreateModal">
                + Nuovo Utente
            </button>
        </div>

        <div class="table-container mt-4">
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Username</th>
                        <th>Nome</th>
                        <th>Email</th>
                        <th>Ruolo</th>
                        <th>Auth</th>
                        <th>Azioni</th>
                    </tr>
                </thead>
                <tbody>
                    <tr v-for="user in users" :key="user.id">
                        <td>{{ user.username }}</td>
                        <td>{{ user.full_name || '-' }}</td>
                        <td>{{ user.email || '-' }}</td>
                        <td>
                            <span class="badge" :class="getRoleClass(user.role)">{{ user.role }}</span>
                        </td>
                        <td>
                            <span class="badge badge-secondary">{{ user.auth_method }}</span>
                        </td>
                        <td>
                             <div class="btn-group">
                                <button class="btn btn-danger btn-xs" @click="deleteUser(user)" v-if="user.id !== currentUserId" title="Elimina">
                                    🗑️
                                </button>
                            </div>
                        </td>
                    </tr>
                </tbody>
            </table>
        </div>

        <!-- Create Modal -->
        <div v-if="showModal" class="modal-overlay">
            <div class="modal">
                <div class="modal-header">
                    <h3>Nuovo Utente</h3>
                    <button class="close-btn" @click="showModal = false">×</button>
                </div>
                <div class="modal-body">
                    <div class="form-group">
                        <label>Username</label>
                        <input v-model="form.username" type="text" class="form-input" required>
                    </div>
                    <div class="form-group">
                        <label>Password</label>
                        <input v-model="form.password" type="password" class="form-input" required>
                    </div>
                    <div class="form-group">
                        <label>Nome Completo</label>
                        <input v-model="form.full_name" type="text" class="form-input">
                    </div>
                    <div class="form-group">
                        <label>Email</label>
                        <input v-model="form.email" type="email" class="form-input">
                    </div>
                    <div class="form-group">
                        <label>Ruolo</label>
                        <select v-model="form.role" class="form-input">
                            <option value="viewer">Viewer</option>
                            <option value="operator">Operator</option>
                            <option value="admin">Admin</option>
                        </select>
                    </div>
                    <div class="form-group">
                         <label>Metodo Auth</label>
                         <select v-model="form.auth_method" class="form-input">
                             <option value="local">Locale</option>
                             <option value="proxmox">Proxmox</option>
                         </select>
                    </div>
                </div>
                <div class="modal-footer">
                    <button class="btn btn-secondary" @click="showModal = false">Annulla</button>
                    <button class="btn btn-primary" @click="submitUser" :disabled="saving">
                        {{ saving ? 'Salvataggio...' : 'Crea Utente' }}
                    </button>
                </div>
            </div>
        </div>
    </div>
</template>

<script setup lang="ts">
import { ref, onMounted, reactive } from 'vue';
import authService from '../../services/auth';

const users = ref<any[]>([]);
const showModal = ref(false);
const saving = ref(false);
const currentUserId = ref<number | null>(null);

const form = reactive({
    username: '',
    password: '',
    full_name: '',
    email: '',
    role: 'operator',
    auth_method: 'local'
});

onMounted(async () => {
    loadUsers();
    try {
        const me = await authService.getMe();
        currentUserId.value = me.data.id;
    } catch (e) {}
});

const loadUsers = async () => {
    try {
        const res = await authService.getUsers();
        users.value = res.data;
    } catch (e) {
        console.error("Error loading users", e);
    }
};

const openCreateModal = () => {
    Object.assign(form, {
        username: '',
        password: '',
        full_name: '',
        email: '',
        role: 'operator',
        auth_method: 'local'
    });
    showModal.value = true;
};

const submitUser = async () => {
    saving.value = true;
    try {
        await authService.createUser(form);
        showModal.value = false;
        loadUsers();
    } catch (e: any) {
        alert('Errore creazione utente: ' + (e.response?.data?.detail || e.message));
    } finally {
        saving.value = false;
    }
};

const deleteUser = async (user: any) => {
    if (!confirm(`Eliminare utente ${user.username}?`)) return;
    try {
        await authService.deleteUser(user.id);
        loadUsers();
    } catch (e) {
        alert('Errore eliminazione');
    }
};

const getRoleClass = (role: string) => {
    if (role === 'admin') return 'badge-danger';
    if (role === 'operator') return 'badge-warning';
    return 'badge-info';
};
</script>

<style scoped>
.header-actions { display: flex; justify-content: space-between; align-items: center; }
.mt-4 { margin-top: 16px; }
.badge-danger { background: rgba(255, 82, 82, 0.15); color: #ff5252; }
.badge-warning { background: rgba(255, 179, 0, 0.15); color: #ffb300; }
.badge-info { background: rgba(0, 212, 255, 0.15); color: #00d4ff; }
.badge-secondary { background: rgba(255, 255, 255, 0.1); color: var(--text-secondary); }

/* Modal Styles */
.modal-overlay {
    position: fixed; top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(0, 0, 0, 0.5);
    display: flex; justify-content: center; align-items: center; z-index: 1000;
}
.modal {
    background: var(--bg-card); padding: 24px; border-radius: 12px;
    width: 100%; max-width: 500px; border: 1px solid var(--border-color);
}
.modal-header { display: flex; justify-content: space-between; margin-bottom: 20px; }
.modal-body { display: flex; flex-direction: column; gap: 16px; }
.modal-footer { display: flex; justify-content: flex-end; gap: 12px; margin-top: 24px; }
.form-group { display: flex; flex-direction: column; gap: 6px; }
.form-input { padding: 8px; border-radius: 4px; background: var(--bg-input); border: 1px solid var(--border-color); color: var(--text-primary); }
.close-btn { background: none; border: none; font-size: 24px; cursor: pointer; color: var(--text-secondary); }
</style>
