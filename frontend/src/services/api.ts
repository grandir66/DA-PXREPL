import axios from 'axios'
import type { AxiosInstance, AxiosResponse, InternalAxiosRequestConfig } from 'axios'

const apiClient: AxiosInstance = axios.create({
    baseURL: '/api',
    headers: {
        'Content-Type': 'application/json',
    },
})

let isRefreshing = false
// Ogni waiter porta resolve E reject: se il refresh fallisce, le richieste in
// coda vengono rigettate SUBITO invece di restare appese fino al timeout (C-13).
let refreshWaiters: Array<{ resolve: (token: string) => void; reject: (err: unknown) => void }> = []

function subscribeTokenRefresh(resolve: (token: string) => void, reject: (err: unknown) => void) {
    refreshWaiters.push({ resolve, reject })
}

function notifyRefreshed(token: string) {
    refreshWaiters.forEach(w => w.resolve(token))
    refreshWaiters = []
}

function failRefreshWaiters(err: unknown) {
    refreshWaiters.forEach(w => w.reject(err))
    refreshWaiters = []
}

function clearSession() {
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    localStorage.removeItem('user')
}

async function refreshAccessToken(): Promise<string | null> {
    const refreshToken = localStorage.getItem('refresh_token')
    if (!refreshToken) return null

    const response = await axios.post(
        '/api/auth/refresh',
        {},
        { headers: { Authorization: `Bearer ${refreshToken}` } },
    )
    const accessToken = response.data?.access_token as string | undefined
    const newRefresh = response.data?.refresh_token as string | undefined
    if (!accessToken) return null

    localStorage.setItem('access_token', accessToken)
    if (newRefresh) {
        localStorage.setItem('refresh_token', newRefresh)
    }
    return accessToken
}

function isAuthEndpoint(url?: string): boolean {
    if (!url) return false
    return url.includes('/auth/login') || url.includes('/auth/refresh')
}

// Request interceptor for API calls
apiClient.interceptors.request.use(
    (config: InternalAxiosRequestConfig) => {
        const token = localStorage.getItem('access_token')
        if (token) {
            config.headers.Authorization = `Bearer ${token}`
        }
        return config
    },
    (error) => Promise.reject(error),
)

// Response interceptor: refresh token on 401
apiClient.interceptors.response.use(
    (response: AxiosResponse) => response,
    async (error) => {
        const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean }
        if (!originalRequest || error.response?.status !== 401) {
            return Promise.reject(error)
        }
        if (originalRequest._retry || isAuthEndpoint(originalRequest.url)) {
            clearSession()
            if (!window.location.pathname.startsWith('/login')) {
                window.location.href = '/login'
            }
            return Promise.reject(error)
        }

        if (isRefreshing) {
            return new Promise((resolve, reject) => {
                subscribeTokenRefresh(
                    (token) => {
                        originalRequest.headers.Authorization = `Bearer ${token}`
                        resolve(apiClient(originalRequest))
                    },
                    (err) => reject(err),
                )
                // Rete di sicurezza: se il refresh non notifica mai, non restare
                // appesi all'infinito.
                setTimeout(() => reject(error), 15000)
            })
        }

        originalRequest._retry = true
        isRefreshing = true
        try {
            const newToken = await refreshAccessToken()
            if (newToken) {
                notifyRefreshed(newToken)
                originalRequest.headers.Authorization = `Bearer ${newToken}`
                return apiClient(originalRequest)
            }
        } catch (refreshErr) {
            // Refresh fallito: sblocca subito le richieste in coda.
            failRefreshWaiters(refreshErr)
        } finally {
            isRefreshing = false
        }

        // Refresh senza token valido: rigetta anche eventuali waiter residui.
        failRefreshWaiters(error)
        clearSession()
        if (!window.location.pathname.startsWith('/login')) {
            window.location.href = '/login'
        }
        return Promise.reject(error)
    },
)

export default apiClient
