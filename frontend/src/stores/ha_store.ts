import { defineStore } from 'pinia';
import { ref, computed } from 'vue';

export const useHAStore = defineStore('ha_store', () => {
    // State
    const haResources = ref<any[]>([]);
    const haGroups = ref<any[]>([]);
    const availableGuests = ref<any[]>([]);
    const clusterNodes = ref<any[]>([]);
    const clusterStatus = ref<any>(null);

    // Analysis State
    const lastAnalysis = ref<any>(null);
    const analysisTimestamp = ref<Date | null>(null);
    const migrationHistory = ref<any[]>([]);

    const loading = ref(false);
    const lastUpdated = ref<Date | null>(null);
    const error = ref<string | null>(null);

    // Actions
    const setAnalysisResult = (result: any) => {
        lastAnalysis.value = result;
        analysisTimestamp.value = new Date();
    };

    const fetchHAData = async (force = false, background = false) => {
        // Se abbiamo dati recenti (meno di 60s) e non è force, non ricaricare
        if (!force && lastUpdated.value && (new Date().getTime() - lastUpdated.value.getTime() < 60000)) {
            return;
        }

        // Recupera token
        const token = localStorage.getItem('access_token');
        if (!token) return;

        // Recupera primo nodo (assumendo helper esterno o logica qui)
        let nodeId: number | null = null;
        try {
            const nodesRes = await fetch('/api/nodes/', {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (nodesRes.ok) {
                const nodes = await nodesRes.json();
                if (nodes.length > 0) nodeId = nodes[0].id;
            }
        } catch (e) {
            console.error(e);
        }

        if (!nodeId) return;

        if (!background) loading.value = true;
        error.value = null;

        try {
            const response = await fetch(`/api/ha/node/${nodeId}/complete-data`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });

            if (response.ok) {
                const data = await response.json();
                haResources.value = data.ha_resources || [];
                haGroups.value = data.ha_groups || [];
                availableGuests.value = data.guests || [];
                clusterNodes.value = data.cluster_nodes || [];
                clusterStatus.value = data.cluster_status || null;
                lastUpdated.value = new Date();
            } else {
                error.value = 'Failed to load HA data';
            }
        } catch (err) {
            error.value = 'Network error loading HA data';
            console.error(err);
        } finally {
            if (!background) loading.value = false;
        }
    };

    let pollInterval: any = null;

    const startBackgroundRefresh = (intervalMs = 30000) => {
        stopBackgroundRefresh();
        pollInterval = setInterval(() => {
            // Background refresh: silente, loading non true
            if (!loading.value) {
                fetchHAData(true, true); // force=true, background=true
            }
        }, intervalMs);
    };

    const stopBackgroundRefresh = () => {
        if (pollInterval) {
            clearInterval(pollInterval);
            pollInterval = null;
        }
    };

    return {
        haResources,
        haGroups,
        availableGuests,
        clusterNodes,
        clusterStatus,
        lastAnalysis,
        analysisTimestamp,
        migrationHistory,
        loading,
        lastUpdated,
        error,
        fetchHAData,
        setAnalysisResult,
        startBackgroundRefresh,
        stopBackgroundRefresh
    };
});

