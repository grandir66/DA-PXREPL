import { defineStore } from 'pinia'
import authService, { type User } from '../services/auth'

export const useAuthStore = defineStore('auth', {
    state: () => ({
        user: JSON.parse(localStorage.getItem('user') || 'null') as User | null,
        token: localStorage.getItem('access_token') || null,
        isAuthenticated: !!localStorage.getItem('access_token'),
        realms: [] as any[],
    }),

    actions: {
        async login(credentials: any) {
            try {
                const response = await authService.login(credentials)
                this.token = response.data.access_token
                this.isAuthenticated = true
                localStorage.setItem('access_token', this.token || '')

                // Fetch user details immediately after login
                await this.fetchUser()
                return true
            } catch (error) {
                console.error('Login failed', error)
                throw error
            }
        },

        async fetchUser() {
            try {
                const response = await authService.getMe()
                this.user = response.data
                localStorage.setItem('user', JSON.stringify(this.user))
                return this.user
            } catch (error) {
                this.logout()
            }
        },

        async fetchRealms() {
            try {
                const response = await authService.getRealms();
                this.realms = response.data;
            } catch (error) {
                console.error('Failed to fetch realms', error);
            }
        },

        logout() {
            this.user = null
            this.token = null
            this.isAuthenticated = false
            localStorage.removeItem('access_token')
            localStorage.removeItem('user')
            // router push handled in component or interceptor
        }
    }
})
