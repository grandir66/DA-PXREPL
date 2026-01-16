import apiClient from './api';

export interface BackupInfo {
    filename: string;
    created_at: string;
    size: number;
    includes_database: boolean;
    includes_ssh_keys: boolean;
    includes_certificates: boolean;
    includes_config: boolean;
    version: string;
    source_hostname: string;
}

export interface BackupSystemInfo {
    database: {
        exists: boolean;
        path: string;
        size: number;
    };
    ssh_keys: {
        exists: boolean;
        files: string[];
    };
    certificates: {
        exists: boolean;
        files: string[];
    };
    config: {
        exists: boolean;
        path: string;
    };
    version: string;
    hostname: string;
}

export interface RestoreResult {
    success: boolean;
    message: string;
    restored_items: string[];
    warnings: string[];
}

export default {
    // Lista backup disponibili
    listBackups() {
        return apiClient.get<BackupInfo[]>('/config-backup/available');
    },

    // Info su cosa c'è da backuppare
    getSystemInfo() {
        return apiClient.get<BackupSystemInfo>('/config-backup/info');
    },

    // Crea nuovo backup
    createBackup(options: {
        include_database?: boolean;
        include_ssh_keys?: boolean;
        include_certificates?: boolean;
        include_config?: boolean;
    } = {}) {
        const params = new URLSearchParams();
        if (options.include_database !== undefined) params.append('include_database', String(options.include_database));
        if (options.include_ssh_keys !== undefined) params.append('include_ssh_keys', String(options.include_ssh_keys));
        if (options.include_certificates !== undefined) params.append('include_certificates', String(options.include_certificates));
        if (options.include_config !== undefined) params.append('include_config', String(options.include_config));

        return apiClient.post<{ success: boolean; filename: string; size: number; download_url: string }>(
            `/config-backup/export?${params.toString()}`
        );
    },

    // Download backup
    // Download backup
    async downloadBackup(filename: string) {
        return apiClient.get(`/config-backup/download/${filename}`, {
            responseType: 'blob'
        });
    },

    getDownloadUrl(filename: string) {
        const token = localStorage.getItem('access_token');
        return `${apiClient.defaults.baseURL}/config-backup/download/${filename}?token=${token}`;
    },

    // Upload e ripristina backup
    async restoreBackup(file: File, options: {
        restore_database?: boolean;
        restore_ssh_keys?: boolean;
        restore_certificates?: boolean;
        restore_config?: boolean;
    } = {}) {
        const formData = new FormData();
        formData.append('file', file);

        // Aggiungi opzioni come campi form
        if (options.restore_database !== undefined) formData.append('restore_database', String(options.restore_database));
        if (options.restore_ssh_keys !== undefined) formData.append('restore_ssh_keys', String(options.restore_ssh_keys));
        if (options.restore_certificates !== undefined) formData.append('restore_certificates', String(options.restore_certificates));
        if (options.restore_config !== undefined) formData.append('restore_config', String(options.restore_config));

        return apiClient.post<RestoreResult>(
            '/config-backup/restore',
            formData
        );
    },

    // Elimina backup
    deleteBackup(filename: string) {
        return apiClient.delete(`/config-backup/delete/${filename}`);
    }
};
