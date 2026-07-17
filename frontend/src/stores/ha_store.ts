import { defineStore } from 'pinia';
import { ref } from 'vue';
import haService, { type ClusterEntryInfo } from '../services/ha';
import nodesService from '../services/nodes';

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
    const clusterEntry = ref<ClusterEntryInfo | null>(null);

    const resolveEntryNodeId = async (): Promise<number | null> => {
        try {
            const res = await haService.getClusterEntry();
            clusterEntry.value = res.data;
            if (res.data.entry_node_id) return res.data.entry_node_id;
        } catch {
            // fallback sotto
        }
        try {
            const nodesRes = await nodesService.getNodes();
            const nodes = nodesRes.data;
            const pve = nodes.find((n) => n.node_type === 'pve' || !n.node_type);
            if (pve) return pve.id;
            if (nodes.length > 0) return nodes[0].id;
        } catch {
            /* ignore */
        }
        return null;
    };

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

        const nodeId = await resolveEntryNodeId();
        if (!nodeId) return;

        if (!background) loading.value = true;
        error.value = null;

        try {
            const response = await haService.getCompleteData(nodeId);
            const data = response.data;
            haResources.value = data.ha_resources || [];
            haGroups.value = data.ha_groups || [];
            availableGuests.value = data.guests || [];
            clusterNodes.value = data.cluster_nodes || [];
            clusterStatus.value = data.cluster_status || null;
            lastUpdated.value = new Date();
        } catch {
            error.value = 'Network error loading HA data';
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
        clusterEntry,
        fetchHAData,
        setAnalysisResult,
        startBackgroundRefresh,
        stopBackgroundRefresh
    };
});

