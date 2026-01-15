import { createRouter, createWebHistory } from 'vue-router'
import Dashboard from '../views/Dashboard.vue'
import Nodes from '../views/Nodes.vue'
import VMs from '../views/VMs.vue'
import SyncJobs from '../views/jobs/SyncJobs.vue'
import BackupJobs from '../views/jobs/BackupJobs.vue'
import RecoveryJobs from '../views/jobs/RecoveryJobs.vue'
import MigrationJobs from '../views/jobs/MigrationJobs.vue'
import Logs from '../views/Logs.vue'
import Settings from '../views/Settings.vue'
import Login from '../views/Login.vue'
import MainLayout from '../layouts/MainLayout.vue'

const router = createRouter({
    history: createWebHistory(import.meta.env.BASE_URL),
    routes: [
        {
            path: '/login',
            name: 'login',
            component: Login
        },
        {
            path: '/',
            component: MainLayout,
            meta: { requiresAuth: true },
            children: [
                {
                    path: '', // Default child
                    name: 'dashboard',
                    component: Dashboard
                },
                {
                    path: 'nodes',
                    name: 'nodes',
                    component: Nodes
                },
                {
                    path: 'vms',
                    name: 'vms',
                    component: VMs
                },
                {
                    path: 'replication',
                    name: 'replication',
                    component: () => import('../views/Replication.vue')
                },
                {
                    path: 'sync-jobs',
                    name: 'sync-jobs',
                    component: SyncJobs
                },
                {
                    path: 'backup-jobs',
                    name: 'backup-jobs',
                    component: BackupJobs
                },
                {
                    path: 'host-backup',
                    name: 'host-backup',
                    component: () => import('../views/HostBackupView.vue')
                },
                {
                    path: 'recovery-jobs',
                    name: 'recovery-jobs',
                    component: RecoveryJobs
                },
                {
                    path: 'migration-jobs',
                    name: 'migration-jobs',
                    component: MigrationJobs
                },
                {
                    path: 'logs',
                    name: 'logs',
                    component: Logs
                },
                {
                    path: 'settings',
                    name: 'settings',
                    component: Settings
                },
                {
                    path: 'updates',
                    name: 'updates',
                    component: () => import('../views/settings/Updates.vue')
                }
            ]
        },
        // Add other routes here
    ]
})

router.beforeEach((to, _from, next) => {
    const isAuthenticated = localStorage.getItem('access_token')
    if (to.meta.requiresAuth && !isAuthenticated) {
        next({ name: 'login' })
    } else {
        next()
    }
})

export default router
