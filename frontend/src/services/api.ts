import axios from 'axios'
import type { AxiosInstance, AxiosResponse, InternalAxiosRequestConfig } from 'axios'

const apiClient: AxiosInstance = axios.create({
    baseURL: '/api',
    headers: {
        'Content-Type': 'application/json',
    },
})

let isRefreshing = false
let refreshWaiters: Array<(token: string) => void> = []

function subscribeTokenRefresh(callback: (token: string) => void) {
    refreshWaiters.push(callback)
}

function notifyRefreshed(token: string) {
    refreshWaiters.forEach(cb => cb(token))
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
                subscribeTokenRefresh((token) => {
                    originalRequest.headers.Authorization = `Bearer ${token}`
                    resolve(apiClient(originalRequest))
                })
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
        } catch {
            // fall through to logout
        } finally {
            isRefreshing = false
        }

        clearSession()
        if (!window.location.pathname.startsWith('/login')) {
            window.location.href = '/login'
        }
        return Promise.reject(error)
    },
)

export default apiClient
