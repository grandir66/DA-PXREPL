import apiClient from './api'

export interface User {
    username: string;
    email?: string;
    full_name?: string;
    role?: string;
    is_active?: boolean;
}

export interface LoginResponse {
    access_token: string;
    token_type: string;
    user: User;
}

export default {
    login(credentials: any) {
        return apiClient.post('/auth/login', {
            username: credentials.username,
            password: credentials.password,
            realm: credentials.realm
        });
    },

    getMe() {
        return apiClient.get<User>('/auth/me');
    },

    getRealms() {
        return apiClient.get('/auth/realms');
    },

    setup(data: any) {
        return apiClient.post('/auth/setup', data);
    },

    // Admin User Management
    getUsers() {
        return apiClient.get<User[]>('/auth/users');
    },

    createUser(data: any) {
        return apiClient.post<User>('/auth/users', data);
    },

    updateUser(id: number | string, data: any) {
        return apiClient.put<User>(`/auth/users/${id}`, data);
    },

    deleteUser(id: number | string) {
        return apiClient.delete(`/auth/users/${id}`);
    },

    // Password Management
    changePassword(data: any) {
        return apiClient.put('/auth/me/password', data);
    }
}
