import axios from 'axios'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

console.log('🔍 API_URL:', API_URL)
console.log('🔍 NEXT_PUBLIC_DEBUG:', process.env.NEXT_PUBLIC_DEBUG)

const api = axios.create({
  baseURL: API_URL,
  timeout: 30000,
})

// Attach access token to every request
api.interceptors.request.use((config) => {
  if (typeof window !== 'undefined') {
    const token = localStorage.getItem('access_token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
  }
  return config
})

// Auto-refresh on 401
let isRefreshing = false
let failedQueue: Array<{ resolve: (v: any) => void; reject: (e: any) => void }> = []

function processQueue(error: any, token: string | null = null) {
  failedQueue.forEach((prom) => {
    if (error) prom.reject(error)
    else prom.resolve(token)
  })
  failedQueue = []
}

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config

    if (error.response?.status === 401 && !originalRequest._retry) {
      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject })
        }).then((token) => {
          originalRequest.headers.Authorization = `Bearer ${token}`
          return api(originalRequest)
        })
      }

      originalRequest._retry = true
      isRefreshing = true

      try {
        const refreshToken = localStorage.getItem('refresh_token')
        if (!refreshToken) throw new Error('No refresh token')

        const response = await axios.post(`${API_URL}/api/auth/refresh`, {
          refresh_token: refreshToken,
        })
        const { access_token } = response.data
        localStorage.setItem('access_token', access_token)
        processQueue(null, access_token)
        originalRequest.headers.Authorization = `Bearer ${access_token}`
        return api(originalRequest)
      } catch (err) {
        processQueue(err, null)
        localStorage.removeItem('access_token')
        localStorage.removeItem('refresh_token')
        if (typeof window !== 'undefined') {
          window.location.href = '/login'
        }
        return Promise.reject(err)
      } finally {
        isRefreshing = false
      }
    }

    return Promise.reject(error)
  }
)

// Auth API
export const authApi = {
  register: (data: { email: string; password: string; full_name: string; role?: string; team_id?: string }) =>
    api.post('/api/auth/register', data),

  login: (data: { email: string; password: string }) => {
    console.log('🔍 Login attempt:', data)
    const form = new URLSearchParams()
    form.append('username', data.email)
    form.append('password', data.password)
    console.log('🔍 Form data:', form.toString())
    return api.post('/api/auth/login', form, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    })
  },

  refresh: (refreshToken: string) =>
    api.post('/api/auth/refresh', { refresh_token: refreshToken }),

  me: () => api.get('/api/auth/me'),

  updateProfile: (data: { full_name?: string; timezone?: string }) =>
    api.patch('/api/auth/me', data),

  logout: () => api.post('/api/auth/logout').catch(() => {}),

  forgotPassword: (email: string) =>
    api.post('/api/auth/forgot-password', { email }),

  resetPassword: (token: string, new_password: string) =>
    api.post('/api/auth/reset-password', { token, new_password }),

  getRoles: () => api.get('/api/auth/roles'),

  checkAdminExists: () => api.get('/api/auth/admin-exists'),
}

// Admin API
export const adminApi = {
  getAllUsers: () => api.get('/api/admin/users'),
  getUserCount: () => api.get('/api/admin/users/count'),
  getTeamUsers: () => api.get('/api/admin/users/team'),
  updateUserRole: (userId: string, role: string) =>
    api.patch(`/api/admin/users/${userId}/role`, null, { params: { role } }),
  toggleUserActive: (userId: string) =>
    api.patch(`/api/admin/users/${userId}/toggle-active`),
  deleteUser: (userId: string) =>
    api.delete(`/api/admin/users/${userId}`),
  deleteAllUsers: () =>
    api.delete('/api/admin/users'),
}

// Task API
export const taskApi = {
  getTasks: (params?: Record<string, any>) => api.get('/api/tasks', { params }),
  getTask: (id: string) => api.get(`/api/tasks/${id}`),
  createTask: (data: Record<string, any>) => api.post('/api/tasks', data),
  updateTask: (id: string, data: Record<string, any>) => api.patch(`/api/tasks/${id}`, data),
  deleteTask: (id: string) => api.delete(`/api/tasks/${id}`),
  getStats: () => api.get('/api/tasks/stats'),
}

// Meeting API
export const meetingApi = {
  getMeetings: (params?: Record<string, any>) => api.get('/api/meetings', { params }),
  getMeeting: (id: string) => api.get(`/api/meetings/${id}`),
  uploadMeeting: (formData: FormData) =>
    api.post('/api/meetings/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }),
  retryMeeting: (id: string) => api.post(`/api/meetings/${id}/retry`),
  deleteMeeting: (id: string) => api.delete(`/api/meetings/${id}`),
  convertActionItem: (meetingId: string, actionItemId: string) =>
    api.post(`/api/meetings/${meetingId}/action-items/${actionItemId}/convert`),
  rejectActionItem: (meetingId: string, actionItemId: string) =>
    api.post(`/api/meetings/${meetingId}/action-items/${actionItemId}/reject`),
}

// Chat API
export const chatApi = {
  query: (message: string) => api.post('/api/chat/query', { message }),
  getHistory: () => api.get('/api/chat/history'),
}

// Email API
export const emailApi = {
  getEmails: (params?: Record<string, any>) => api.get('/api/emails', { params }),
  getEmail: (id: string) => api.get(`/api/emails/${id}`),
  syncEmails: (params?: { limit?: number; days?: number }) =>
    api.post('/api/emails/sync', null, { params }),
  getStats: () => api.get('/api/emails/stats'),
  seedDemo: () => api.post('/api/emails/seed-demo'),
}

// Messages (Slack) API
export const messagesApi = {
  getMessages: (params?: Record<string, any>) => api.get('/api/messages', { params }),
  getStats: () => api.get('/api/messages/stats'),
  getDmConversations: () => api.get('/api/messages/dms'),
  getSlackUsers: () => api.get('/api/messages/dms/users'),
  sendDm: (payload: { slack_user_id: string; message: string; channel_id?: string }) =>
    api.post('/api/messages/dms/send', payload),
}

// Integrations API
export const integrationsApi = {
  getIntegrations: () => api.get('/api/integrations'),
  connectGmail: (credentials: { email: string; app_password: string }) =>
    api.post('/api/integrations/gmail/connect', credentials),
  startSlackOAuth: () => api.get('/api/integrations/slack/start'),
  connectSlackDemo: () => api.post('/api/integrations/slack/demo-connect'),
  connectJira: (credentials: { domain: string; email: string; api_token: string; project_key?: string }) =>
    api.post('/api/integrations/jira/connect', credentials),
  disconnectIntegration: (id: string) => api.delete(`/api/integrations/${id}`),
  syncIntegration: (id: string) => api.post(`/api/integrations/${id}/sync`),
}

// Direct Messages API
export const dmApi = {
  getUsers: () => api.get('/api/dm/users'),
  getConversations: () => api.get('/api/dm/conversations'),
  getConversation: (userId: string) => api.get(`/api/dm/${userId}`),
  sendMessage: (recipient_id: string, content: string) =>
    api.post('/api/dm/send', { recipient_id, content }),
  getUnreadCount: () => api.get<{ unread: number }>('/api/dm/unread-count'),
  clearAllDms: () => api.delete('/api/dm/clear-all'),
  deleteMessage: (messageId: string) => api.delete(`/api/dm/message/${messageId}`),
}

// Analytics API
export const analyticsApi = {
  getWorkload: (days = 30) => api.get(`/api/analytics/workload?days=${days}`),
  getTeamWorkload: () => api.get('/api/analytics/team-workload'),
  getMeetingInsights: (days = 30) => api.get(`/api/analytics/meeting-insights?days=${days}`),
  getProductivityTrend: (days = 14) => api.get(`/api/analytics/productivity-trend?days=${days}`),
}

export default api
