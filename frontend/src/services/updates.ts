import apiClient from './api';

export interface UpdateCheckResult {
    current_version: string;
    available_version: string | null;
    update_available: boolean;
    last_check: string | null;
    changelog?: string;
    release_date?: string;
    release_url?: string;
}

export interface UpdateStatus {
    in_progress: boolean;
    last_update: string | null;
    log: string[];
    error: string | null;
    success?: boolean;
}

export default {
    checkForUpdates() {
        return apiClient.get<UpdateCheckResult>('/updates/check');
    },

    getStatus() {
        return apiClient.get<UpdateStatus>('/updates/status');
    },

    startUpdate() {
        return apiClient.post<{ success: boolean; message: string }>('/updates/start');
    },

    getVersion() {
        return apiClient.get<{ version: string }>('/updates/version');
    },

    refreshVersion() {
        return apiClient.post<{ success: boolean; version: string; message: string }>('/updates/refresh-version');
    }
};
