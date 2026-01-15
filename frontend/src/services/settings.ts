import apiClient from './api'

export interface NotificationConfig {
    smtp_enabled: boolean;
    smtp_host?: string;
    smtp_port?: number;
    smtp_user?: string;
    smtp_password?: string;
    smtp_from?: string;
    smtp_to?: string;
    smtp_subject_prefix?: string;
    smtp_tls: boolean;

    webhook_enabled: boolean;
    webhook_url?: string;
    webhook_secret?: string;

    telegram_enabled: boolean;
    telegram_chat_id?: string;
    telegram_bot_token?: string;

    notify_on_success: boolean;
    notify_on_failure: boolean;
    notify_on_warning: boolean;
}

export interface AuthConfig {
    auth_method: string;
    auth_proxmox_node?: string;
    auth_session_timeout: number;
}

export default {
    getNotificationConfig() {
        return apiClient.get<NotificationConfig>('/settings/notifications');
    },

    updateNotificationConfig(config: Partial<NotificationConfig>) {
        return apiClient.put('/settings/notifications', config);
    },

    testNotification(channel: string) {
        return apiClient.post('/settings/notifications/test', null, { params: { channel } });
    },

    // SSL & System
    getSSLStatus() {
        return apiClient.get('/settings/ssl/status');
    },

    generateCert(data: any) {
        return apiClient.post('/settings/ssl/generate-cert', data);
    },

    uploadCert(data: { certificate: string, private_key: string }) {
        return apiClient.post('/settings/ssl/upload-cert', data);
    },

    deleteCert() {
        return apiClient.delete('/settings/ssl/cert');
    },

    getAuthConfig() {
        return apiClient.get<AuthConfig>('/settings/auth/config');
    },

    updateAuthConfig(config: Partial<AuthConfig>) {
        return apiClient.put('/settings/auth/config', config);
    },

    // Server Config
    getServerConfig() {
        return apiClient.get('/settings/server/config');
    },

    updateServerConfig(config: { port?: number, ssl_enabled?: boolean }) {
        return apiClient.put('/settings/server/config', config);
    }
}
