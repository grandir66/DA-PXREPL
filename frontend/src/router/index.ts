import { createRouter, createWebHistory } from 'vue-router'
import { getAppMode } from '../utils/appMode'
import Dashboard from '../views/Dashboard.vue'
import Nodes from '../views/Nodes.vue'
import VMs from '../views/VMs.vue'
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
                    path: '',
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
                    meta: { requiresFullMode: true },
                    component: VMs
                },
                {
                    path: 'replication',
                    name: 'replication',
                    meta: { requiresFullMode: true },
                    component: () => import('../views/Replication.vue')
                },
                {
                    path: 'sanoid-syncoid',
                    name: 'sanoid-syncoid',
                    meta: { requiresFullMode: true },
                    component: () => import('../views/SanoidSyncoid.vue')
                },
                // Legacy routes → modulo unificato Repliche
                { path: 'sync-jobs', redirect: { name: 'replication' } },
                { path: 'backup-jobs', redirect: { name: 'replication' } },
                { path: 'recovery-jobs', redirect: { name: 'replication' } },
                {
                    path: 'pbs-inventory',
                    name: 'pbs-inventory',
                    meta: { requiresFullMode: true },
                    component: () => import('../views/PBSInventory.vue')
                },
                {
                    path: 'host-backup',
                    name: 'host-backup',
                    meta: { requiresFullMode: true },
                    component: () => import('../views/HostBackupView.vue')
                },
                {
                    path: 'migration-jobs',
                    name: 'migration-jobs',
                    meta: { requiresFullMode: true },
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
                    meta: { requiresAdmin: true },
                    component: () => import('../views/settings/Updates.vue')
                },
                {
                    path: 'config-backup',
                    name: 'config-backup',
                    meta: { requiresAdmin: true },
                    component: () => import('../views/settings/ConfigBackup.vue')
                },
                {
                    path: 'load-balancer',
                    name: 'load-balancer',
                    meta: { requiresAdmin: true },
                    component: () => import('../views/LoadBalancer.vue')
                },
                {
                    path: 'cluster',
                    name: 'cluster',
                    component: () => import('../views/Cluster.vue')
                },
            ]
        },
    ]
})

router.beforeEach(async (to, _from, next) => {
    const isAuthenticated = localStorage.getItem('access_token')
    if (to.meta.requiresAuth && !isAuthenticated) {
        next({ name: 'login' })
        return
    }
    if (to.meta.requiresAdmin) {
        let user: { role?: string } | null = null
        try {
            user = JSON.parse(localStorage.getItem('user') || 'null')
        } catch {
            user = null
        }
        if (user?.role !== 'admin') {
            next({ name: 'dashboard' })
            return
        }
    }
    if (to.meta.requiresFullMode && getAppMode() === 'lb') {
        next({ name: 'dashboard' })
        return
    }
    next()
})

export default router
