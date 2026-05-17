import { create } from 'zustand'
import { authApi } from '@/lib/api'
import type { User, UserRole } from '@/types'

interface AuthState {
  user: User | null
  isAuthenticated: boolean
  isLoading: boolean
  error: string | null

  initialize: () => void
  login: (credentials: { email: string; password: string }) => Promise<void>
  register: (data: { email: string; password: string; full_name: string; role?: UserRole; team_id?: string; invite_token?: string }) => Promise<void>
  logout: () => void
  fetchUser: () => Promise<void>
  clearError: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isAuthenticated: false,
  isLoading: true,
  error: null,

  initialize: () => {
    if (typeof window === 'undefined') {
      set({ isLoading: false })
      return
    }
    const token = localStorage.getItem('access_token')
    if (!token) {
      set({ isAuthenticated: false, isLoading: false })
      return
    }

    authApi
      .me()
      .then((res) => {
        set({ user: res.data, isAuthenticated: true, isLoading: false })
      })
      .catch(() => {
        localStorage.removeItem('access_token')
        localStorage.removeItem('refresh_token')
        set({ user: null, isAuthenticated: false, isLoading: false })
      })
  },

  login: async (credentials) => {
    set({ isLoading: true, error: null })
    try {
      const tokenRes = await authApi.login(credentials)
      const { access_token, refresh_token } = tokenRes.data
      localStorage.setItem('access_token', access_token)
      if (refresh_token) localStorage.setItem('refresh_token', refresh_token)

      const userRes = await authApi.me()
      set({ user: userRes.data, isAuthenticated: true, isLoading: false, error: null })
    } catch (err: any) {
      const message =
        err.response?.data?.detail || 'Invalid email or password'
      set({ isLoading: false, error: message })
      throw err
    }
  },

  register: async (data) => {
    set({ isLoading: true, error: null })
    try {
      await authApi.register(data)
      // Auto-login after registration
      const tokenRes = await authApi.login({ email: data.email, password: data.password })
      const { access_token, refresh_token } = tokenRes.data
      localStorage.setItem('access_token', access_token)
      if (refresh_token) localStorage.setItem('refresh_token', refresh_token)

      const userRes = await authApi.me()
      set({ user: userRes.data, isAuthenticated: true, isLoading: false, error: null })
    } catch (err: any) {
      const message =
        err.response?.data?.detail || 'Registration failed'
      set({ isLoading: false, error: message })
      throw err
    }
  },

  logout: () => {
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    set({ user: null, isAuthenticated: false, error: null })
  },

  fetchUser: async () => {
    try {
      const res = await authApi.me()
      set({ user: res.data, isAuthenticated: true })
    } catch {
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
      set({ user: null, isAuthenticated: false })
    }
  },

  clearError: () => set({ error: null }),
}))
