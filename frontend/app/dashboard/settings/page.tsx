'use client'

import { useState, useEffect } from 'react'
import { useSearchParams } from 'next/navigation'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { authApi, integrationsApi, emailApi, adminApi } from '@/lib/api'
import { useAuthStore } from '@/lib/stores/authStore'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Mail, Link2, Link2Off, RefreshCw, Loader2, CheckCircle2, XCircle,
  Users, Shield, UserCheck, UserX, Trash2
} from 'lucide-react'
import type { Integration, AdminUserStats, AdminTeamResponse, AdminTeamUser, UserRole } from '@/types'
import { formatRelativeTime } from '@/lib/utils'
import { ROLE_LABELS } from '@/types'

const ROLE_OPTIONS: { value: UserRole; label: string }[] = [
  { value: 'admin', label: 'Admin' },
  { value: 'project_manager', label: 'Project Manager' },
  { value: 'team_lead', label: 'Team Lead' },
  { value: 'senior_developer', label: 'Senior Developer' },
  { value: 'developer', label: 'Developer' },
  { value: 'intern', label: 'Intern' },
]

export default function SettingsPage() {
  const queryClient = useQueryClient()
  const searchParams = useSearchParams()
  const { user, fetchUser } = useAuthStore()
  const [fullName, setFullName] = useState(user?.full_name || '')
  const [timezone, setTimezone] = useState(user?.timezone || 'UTC')
  const [isEditing, setIsEditing] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [integrationMessage, setIntegrationMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
  const [adminMessage, setAdminMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
  const [showGmailForm, setShowGmailForm] = useState(false)
  const [gmailEmail, setGmailEmail] = useState('')
  const [gmailAppPassword, setGmailAppPassword] = useState('')
  const [showJiraForm, setShowJiraForm] = useState(false)
  const [jiraDomain, setJiraDomain] = useState('')
  const [jiraEmail, setJiraEmail] = useState('')
  const [jiraApiToken, setJiraApiToken] = useState('')
  const [jiraProjectKey, setJiraProjectKey] = useState('')

  const isAdmin = user?.role === 'admin'

  // Handle OAuth callback query params
  useEffect(() => {
    const integration = searchParams.get('integration')
    const status = searchParams.get('status')

    if (integration && status) {
      if (status === 'success') {
        setIntegrationMessage({ type: 'success', text: `${integration.charAt(0).toUpperCase() + integration.slice(1)} connected successfully!` })
      } else if (status === 'error') {
        const message = searchParams.get('message') || 'Connection failed'
        setIntegrationMessage({ type: 'error', text: `Failed to connect ${integration}: ${message}` })
      }

      window.history.replaceState({}, '', '/dashboard/settings')
      setTimeout(() => setIntegrationMessage(null), 5000)
    }
  }, [searchParams])

  // Fetch integrations
  const { data: integrationsData } = useQuery<{ data: Integration[] }>({
    queryKey: ['integrations'],
    queryFn: () => integrationsApi.getIntegrations(),
  })

  const integrations = integrationsData?.data || []
  const gmailIntegration = integrations.find((i) => i.platform === 'gmail')
  const slackIntegration = integrations.find((i) => i.platform === 'slack')
  const jiraIntegration = integrations.find((i) => i.platform === 'jira')

  // Admin: Fetch user stats
  const { data: userStatsData, refetch: refetchUserStats } = useQuery<{ data: AdminUserStats }>({
    queryKey: ['admin-user-stats'],
    queryFn: () => adminApi.getUserCount(),
    enabled: isAdmin,
  })

  // Admin: Fetch team users
  const { data: teamUsersData, refetch: refetchTeamUsers } = useQuery<{ data: AdminTeamResponse }>({
    queryKey: ['admin-team-users'],
    queryFn: () => adminApi.getTeamUsers(),
    enabled: isAdmin,
  })

  const userStats = userStatsData?.data
  const teamUsers = teamUsersData?.data

  // Profile update mutation
  const updateMutation = useMutation({
    mutationFn: (data: any) => authApi.updateProfile(data),
    onSuccess: () => {
      fetchUser()
      queryClient.invalidateQueries({ queryKey: ['user'] })
      setSuccess('Profile updated successfully!')
      setIsEditing(false)
      setTimeout(() => setSuccess(''), 3000)
    },
    onError: (err: any) => {
      setError(err.response?.data?.detail || 'Failed to update profile')
      setTimeout(() => setError(''), 5000)
    },
  })

  // Gmail connect mutation
  const connectGmailMutation = useMutation({
    mutationFn: (credentials: { email: string; app_password: string }) =>
      integrationsApi.connectGmail(credentials),
    onSuccess: (response) => {
      queryClient.invalidateQueries({ queryKey: ['integrations'] })
      setIntegrationMessage({
        type: 'success',
        text: `Gmail connected: ${response.data.email}`,
      })
      setShowGmailForm(false)
      setGmailEmail('')
      setGmailAppPassword('')
      setTimeout(() => setIntegrationMessage(null), 5000)
    },
    onError: (err: any) => {
      setIntegrationMessage({
        type: 'error',
        text: err.response?.data?.detail || 'Failed to connect Gmail. Check your credentials.',
      })
      setTimeout(() => setIntegrationMessage(null), 5000)
    },
  })

  // Slack OAuth start mutation
  const startSlackOAuthMutation = useMutation({
    mutationFn: () => integrationsApi.startSlackOAuth(),
    onSuccess: (res: any) => {
      // Redirect user to Slack authorization page
      window.location.href = res.data.authorization_url
    },
    onError: (err: any) => {
      setIntegrationMessage({
        type: 'error',
        text: err.response?.data?.detail || 'Failed to start Slack OAuth.',
      })
      setTimeout(() => setIntegrationMessage(null), 5000)
    },
  })

  // Jira connect mutation
  const connectJiraMutation = useMutation({
    mutationFn: (credentials: { domain: string; email: string; api_token: string; project_key?: string }) =>
      integrationsApi.connectJira(credentials),
    onSuccess: (response) => {
      queryClient.invalidateQueries({ queryKey: ['integrations'] })
      setIntegrationMessage({
        type: 'success',
        text: `Jira connected: ${response.data.message}`,
      })
      setShowJiraForm(false)
      setJiraDomain('')
      setJiraEmail('')
      setJiraApiToken('')
      setJiraProjectKey('')
      setTimeout(() => setIntegrationMessage(null), 5000)
    },
    onError: (err: any) => {
      setIntegrationMessage({
        type: 'error',
        text: err.response?.data?.detail || 'Failed to connect Jira. Check your credentials.',
      })
      setTimeout(() => setIntegrationMessage(null), 5000)
    },
  })

  const [disconnectingId, setDisconnectingId] = useState<string | null>(null)

  // Disconnect mutation — shared handler, tracks which integration is being removed
  const disconnectMutation = useMutation({
    mutationFn: ({ id }: { id: string; name: string }) => {
      setDisconnectingId(id)
      return integrationsApi.disconnectIntegration(id)
    },
    onSuccess: (_data, { name }) => {
      setDisconnectingId(null)
      queryClient.invalidateQueries({ queryKey: ['integrations'] })
      setIntegrationMessage({ type: 'success', text: `${name} disconnected` })
      setTimeout(() => setIntegrationMessage(null), 3000)
    },
    onError: (err: any, { name }) => {
      setDisconnectingId(null)
      setIntegrationMessage({
        type: 'error',
        text: err.response?.data?.detail || `Failed to disconnect ${name}. Please try again.`,
      })
      setTimeout(() => setIntegrationMessage(null), 5000)
    },
  })

  // Gmail sync mutation
  const gmailSyncMutation = useMutation({
    mutationFn: () => emailApi.syncEmails({ limit: 30, days: 7 }),
    onSuccess: (response) => {
      queryClient.invalidateQueries({ queryKey: ['integrations'] })
      queryClient.invalidateQueries({ queryKey: ['emails'] })
      queryClient.invalidateQueries({ queryKey: ['email-stats'] })
      const msg = (response as any)?.data?.message || 'Sync complete!'
      setIntegrationMessage({ type: 'success', text: msg })
      setTimeout(() => setIntegrationMessage(null), 3000)
    },
    onError: (err: any) => {
      setIntegrationMessage({
        type: 'error',
        text: err.response?.data?.detail || 'Sync failed. Check your Gmail connection.',
      })
      setTimeout(() => setIntegrationMessage(null), 5000)
    },
  })

  // Generic integration sync (Slack/Jira)
  const integrationSyncMutation = useMutation({
    mutationFn: (id: string) => integrationsApi.syncIntegration(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['integrations'] })
      setIntegrationMessage({ type: 'success', text: 'Sync triggered' })
      setTimeout(() => setIntegrationMessage(null), 3000)
    },
    onError: (err: any) => {
      setIntegrationMessage({
        type: 'error',
        text: err.response?.data?.detail || 'Sync failed',
      })
      setTimeout(() => setIntegrationMessage(null), 5000)
    },
  })

  // Admin: Update user role mutation
  const updateRoleMutation = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: string }) =>
      adminApi.updateUserRole(userId, role),
    onSuccess: () => {
      refetchTeamUsers()
      refetchUserStats()
      queryClient.invalidateQueries({ queryKey: ['admin-user-count'] })
      setAdminMessage({ type: 'success', text: 'User role updated successfully' })
      setTimeout(() => setAdminMessage(null), 3000)
    },
    onError: (err: any) => {
      setAdminMessage({ type: 'error', text: err.response?.data?.detail || 'Failed to update role' })
      setTimeout(() => setAdminMessage(null), 5000)
    },
  })

  // Admin: Toggle user active mutation
  const toggleActiveMutation = useMutation({
    mutationFn: (userId: string) => adminApi.toggleUserActive(userId),
    onSuccess: () => {
      refetchTeamUsers()
      refetchUserStats()
      setAdminMessage({ type: 'success', text: 'User status updated' })
      setTimeout(() => setAdminMessage(null), 3000)
    },
    onError: (err: any) => {
      setAdminMessage({ type: 'error', text: err.response?.data?.detail || 'Failed to update status' })
      setTimeout(() => setAdminMessage(null), 5000)
    },
  })

  // Admin: Delete user mutation
  const deleteUserMutation = useMutation({
    mutationFn: (userId: string) => adminApi.deleteUser(userId),
    onSuccess: () => {
      refetchTeamUsers()
      refetchUserStats()
      queryClient.invalidateQueries({ queryKey: ['admin-user-count'] })
      setAdminMessage({ type: 'success', text: 'User deleted successfully' })
      setTimeout(() => setAdminMessage(null), 3000)
    },
    onError: (err: any) => {
      setAdminMessage({ type: 'error', text: err.response?.data?.detail || 'Failed to delete user' })
      setTimeout(() => setAdminMessage(null), 5000)
    },
  })

  if (!user) return null

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setSuccess('')

    if (!fullName.trim()) {
      setError('Full name is required')
      return
    }

    updateMutation.mutate({
      full_name: fullName.trim(),
      timezone,
    })
  }

  const handleCancel = () => {
    setFullName(user.full_name)
    setTimezone(user.timezone)
    setIsEditing(false)
    setError('')
    setSuccess('')
  }

  const handleDisconnect = (integrationId: string, name: string) => {
    if (confirm(`Are you sure you want to disconnect ${name}?`)) {
      disconnectMutation.mutate({ id: integrationId, name })
    }
  }

  const handleDeleteUser = (userId: string, userName: string) => {
    if (confirm(`Are you sure you want to delete user "${userName}"? This action cannot be undone.`)) {
      deleteUserMutation.mutate(userId)
    }
  }

  const getRoleBadgeColor = (role: string) => {
    const colors: Record<string, string> = {
      admin: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300',
      project_manager: 'bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-300',
      team_lead: 'bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-300',
      senior_developer: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300',
      developer: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300',
      intern: 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300',
    }
    return colors[role] || 'bg-gray-100 text-gray-800'
  }

  return (
    <div className="space-y-6 max-w-4xl">
      <div>
        <h1 className="text-2xl font-bold">Settings</h1>
        <p className="text-sm text-muted-foreground">
          Manage your account and preferences
        </p>
      </div>

      {/* Integration notification */}
      {integrationMessage && (
        <div
          className={`rounded-md p-3 text-sm flex items-center gap-2 ${
            integrationMessage.type === 'success'
              ? 'bg-green-50 text-green-800 dark:bg-green-950 dark:text-green-400'
              : 'bg-red-50 text-red-800 dark:bg-red-950 dark:text-red-400'
          }`}
        >
          {integrationMessage.type === 'success' ? (
            <CheckCircle2 className="h-4 w-4 shrink-0" />
          ) : (
            <XCircle className="h-4 w-4 shrink-0" />
          )}
          {integrationMessage.text}
        </div>
      )}

      {/* Profile Settings */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Profile Information</CardTitle>
              <CardDescription>
                Update your personal details
              </CardDescription>
            </div>
            {!isEditing && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => setIsEditing(true)}
              >
                Edit Profile
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            {error && (
              <div className="rounded-md bg-red-50 dark:bg-red-950 p-3 text-sm text-red-600 dark:text-red-400">
                {error}
              </div>
            )}

            {success && (
              <div className="rounded-md bg-green-50 dark:bg-green-950 p-3 text-sm text-green-600 dark:text-green-400">
                {success}
              </div>
            )}

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="full_name">Full Name</Label>
                <Input
                  id="full_name"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  disabled={!isEditing}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="email">Email</Label>
                <Input id="email" value={user.email} disabled />
              </div>

              <div className="space-y-2">
                <Label htmlFor="role">Role</Label>
                <div className="flex items-center h-10">
                  <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${getRoleBadgeColor(user.role)}`}>
                    {ROLE_LABELS[user.role] || user.role}
                  </span>
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="timezone">Timezone</Label>
                <select
                  id="timezone"
                  value={timezone}
                  onChange={(e) => setTimezone(e.target.value)}
                  disabled={!isEditing}
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <option value="UTC">UTC</option>
                  <option value="America/New_York">Eastern Time</option>
                  <option value="America/Chicago">Central Time</option>
                  <option value="America/Denver">Mountain Time</option>
                  <option value="America/Los_Angeles">Pacific Time</option>
                  <option value="Europe/London">London</option>
                  <option value="Europe/Paris">Paris</option>
                  <option value="Asia/Tokyo">Tokyo</option>
                  <option value="Asia/Shanghai">Shanghai</option>
                  <option value="Asia/Dubai">Dubai</option>
                  <option value="Australia/Sydney">Sydney</option>
                </select>
              </div>
            </div>

            <div className="flex items-center gap-2 pt-2">
              <Badge variant={user.is_active ? 'default' : 'destructive'}>
                {user.is_active ? 'Active' : 'Inactive'}
              </Badge>
              <Badge variant={user.is_verified ? 'default' : 'outline'}>
                {user.is_verified ? 'Verified' : 'Not Verified'}
              </Badge>
            </div>

            {isEditing && (
              <div className="flex gap-2 pt-4">
                <Button
                  type="submit"
                  disabled={updateMutation.isPending}
                >
                  {updateMutation.isPending ? 'Saving...' : 'Save Changes'}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  onClick={handleCancel}
                  disabled={updateMutation.isPending}
                >
                  Cancel
                </Button>
              </div>
            )}
          </form>
        </CardContent>
      </Card>

      {/* Admin Panel - Only visible to admin */}
      {isAdmin && (
        <Card className="border-amber-200 dark:border-amber-800">
          <CardHeader>
            <div className="flex items-center gap-2">
              <Shield className="h-5 w-5 text-amber-600 dark:text-amber-400" />
              <div>
                <CardTitle>User Management</CardTitle>
                <CardDescription>
                  Admin panel — manage team members and their roles
                </CardDescription>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* Admin notification */}
            {adminMessage && (
              <div
                className={`rounded-md p-3 text-sm flex items-center gap-2 ${
                  adminMessage.type === 'success'
                    ? 'bg-green-50 text-green-800 dark:bg-green-950 dark:text-green-400'
                    : 'bg-red-50 text-red-800 dark:bg-red-950 dark:text-red-400'
                }`}
              >
                {adminMessage.type === 'success' ? (
                  <CheckCircle2 className="h-4 w-4 shrink-0" />
                ) : (
                  <XCircle className="h-4 w-4 shrink-0" />
                )}
                {adminMessage.text}
              </div>
            )}

            {/* User Stats Summary */}
            {userStats && (
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 p-4 rounded-lg bg-amber-50 dark:bg-amber-950">
                <div className="text-center">
                  <div className="text-2xl font-bold text-amber-700 dark:text-amber-300">{userStats.total}</div>
                  <div className="text-xs text-amber-600 dark:text-amber-400">Total Users</div>
                </div>
                <div className="text-center">
                  <div className="text-2xl font-bold text-green-700 dark:text-green-400">{userStats.active}</div>
                  <div className="text-xs text-muted-foreground">Active</div>
                </div>
                <div className="text-center">
                  <div className="text-2xl font-bold text-red-700 dark:text-red-400">{userStats.inactive}</div>
                  <div className="text-xs text-muted-foreground">Inactive</div>
                </div>
                <div className="text-center">
                  <div className="text-2xl font-bold text-blue-700 dark:text-blue-400">{userStats.new_last_30_days}</div>
                  <div className="text-xs text-muted-foreground">New (30d)</div>
                </div>
              </div>
            )}

            {/* Team Members List */}
            <div>
              <h3 className="text-sm font-medium mb-3 flex items-center gap-2">
                <Users className="h-4 w-4" />
                Team Members ({teamUsers?.total || 0})
              </h3>

              {!teamUsers ? (
                <div className="text-center py-6 text-muted-foreground text-sm">
                  Loading users...
                </div>
              ) : teamUsers.users.length === 0 ? (
                <div className="text-center py-6 text-muted-foreground text-sm">
                  No team members found
                </div>
              ) : (
                <div className="space-y-2">
                  {teamUsers.users.map((member: AdminTeamUser) => (
                    <div
                      key={member.id}
                      className="flex items-center gap-3 p-3 rounded-lg border bg-card hover:bg-accent/50 transition-colors"
                    >
                      {/* Avatar */}
                      <div className="h-9 w-9 rounded-full bg-primary/10 flex items-center justify-center shrink-0">
                        <span className="text-xs font-semibold text-primary">
                          {member.full_name.split(' ').map(n => n[0]).join('').toUpperCase().slice(0, 2)}
                        </span>
                      </div>

                      {/* User info */}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <p className="text-sm font-medium truncate">{member.full_name}</p>
                          {member.id === user.id && (
                            <Badge variant="outline" className="text-xs">You</Badge>
                          )}
                          {!member.is_active && (
                            <Badge variant="destructive" className="text-xs">Inactive</Badge>
                          )}
                        </div>
                        <p className="text-xs text-muted-foreground truncate">{member.email}</p>
                      </div>

                      {/* Role selector */}
                      {member.id !== user.id ? (
                        <select
                          value={member.role}
                          onChange={(e) => updateRoleMutation.mutate({ userId: member.id, role: e.target.value })}
                          disabled={updateRoleMutation.isPending}
                          className="text-xs rounded-md border border-input bg-background px-2 py-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
                        >
                          {ROLE_OPTIONS.map(r => (
                            <option key={r.value} value={r.value}>{r.label}</option>
                          ))}
                        </select>
                      ) : (
                        <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium capitalize ${getRoleBadgeColor(member.role)}`}>
                          {ROLE_LABELS[member.role] || member.role}
                        </span>
                      )}

                      {/* Action buttons */}
                      {member.id !== user.id && (
                        <div className="flex items-center gap-1">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => toggleActiveMutation.mutate(member.id)}
                            disabled={toggleActiveMutation.isPending}
                            title={member.is_active ? 'Deactivate user' : 'Activate user'}
                            className="h-7 w-7 p-0"
                          >
                            {member.is_active ? (
                              <UserX className="h-3.5 w-3.5 text-orange-500" />
                            ) : (
                              <UserCheck className="h-3.5 w-3.5 text-green-500" />
                            )}
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleDeleteUser(member.id, member.full_name)}
                            disabled={deleteUserMutation.isPending}
                            title="Delete user"
                            className="h-7 w-7 p-0"
                          >
                            <Trash2 className="h-3.5 w-3.5 text-red-500" />
                          </Button>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Integrations */}
      <Card>
        <CardHeader>
          <CardTitle>Integrations</CardTitle>
          <CardDescription>
            Connect third-party services to enhance your workflow
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {/* Gmail Integration */}
            <div className="border rounded-lg overflow-hidden">
              <div className="flex items-center justify-between p-4">
                <div className="flex items-center gap-3">
                  <div className="h-10 w-10 rounded-lg bg-red-100 dark:bg-red-950 flex items-center justify-center">
                    <Mail className="h-5 w-5 text-red-600 dark:text-red-400" />
                  </div>
                  <div>
                    <p className="font-medium">Gmail</p>
                    {gmailIntegration ? (
                      <div className="space-y-0.5">
                        <p className="text-xs text-muted-foreground">
                          {gmailIntegration.metadata?.email || 'Connected'}
                        </p>
                        {gmailIntegration.last_synced_at && (
                          <p className="text-xs text-muted-foreground">
                            Last synced: {formatRelativeTime(gmailIntegration.last_synced_at)}
                          </p>
                        )}
                      </div>
                    ) : (
                      <p className="text-xs text-muted-foreground">
                        Connect your own Gmail to sync emails
                      </p>
                    )}
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  {gmailIntegration ? (
                    <>
                      <Badge variant="default" className="bg-green-600">
                        <CheckCircle2 className="h-3 w-3 mr-1" />
                        Connected
                      </Badge>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => gmailSyncMutation.mutate()}
                        disabled={gmailSyncMutation.isPending}
                        title="Sync now"
                      >
                        {gmailSyncMutation.isPending ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <RefreshCw className="h-4 w-4" />
                        )}
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handleDisconnect(gmailIntegration.id, 'Gmail')}
                        disabled={disconnectingId === gmailIntegration.id}
                        className="text-red-600 hover:text-red-700 hover:bg-red-50"
                        title="Disconnect"
                      >
                        {disconnectingId === gmailIntegration.id ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Link2Off className="h-4 w-4" />
                        )}
                      </Button>
                    </>
                  ) : (
                    <Button
                      size="sm"
                      variant={showGmailForm ? 'outline' : 'default'}
                      onClick={() => setShowGmailForm((v) => !v)}
                    >
                      {showGmailForm ? (
                        'Cancel'
                      ) : (
                        <>
                          <Link2 className="h-4 w-4 mr-1" />
                          Connect
                        </>
                      )}
                    </Button>
                  )}
                </div>
              </div>

              {/* Credentials form — shown when not connected and user clicked Connect */}
              {!gmailIntegration && showGmailForm && (
                <div className="border-t bg-muted/30 px-4 py-4 space-y-3">
                  <p className="text-xs text-muted-foreground">
                    Enter your Gmail address and a{' '}
                    <a
                      href="https://support.google.com/accounts/answer/185833"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="underline text-blue-600 dark:text-blue-400"
                    >
                      Gmail App Password
                    </a>
                    . Your credentials are stored only for your account.
                  </p>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <div className="space-y-1">
                      <Label htmlFor="gmail-email">Gmail Address</Label>
                      <Input
                        id="gmail-email"
                        type="email"
                        placeholder="you@gmail.com"
                        value={gmailEmail}
                        onChange={(e) => setGmailEmail(e.target.value)}
                        disabled={connectGmailMutation.isPending}
                      />
                    </div>
                    <div className="space-y-1">
                      <Label htmlFor="gmail-app-password">App Password</Label>
                      <Input
                        id="gmail-app-password"
                        type="password"
                        placeholder="xxxx xxxx xxxx xxxx"
                        value={gmailAppPassword}
                        onChange={(e) => setGmailAppPassword(e.target.value)}
                        disabled={connectGmailMutation.isPending}
                      />
                    </div>
                  </div>
                  <Button
                    size="sm"
                    onClick={() => {
                      if (!gmailEmail.trim() || !gmailAppPassword.trim()) {
                        setIntegrationMessage({ type: 'error', text: 'Please enter both your Gmail address and App Password.' })
                        setTimeout(() => setIntegrationMessage(null), 4000)
                        return
                      }
                      connectGmailMutation.mutate({ email: gmailEmail.trim(), app_password: gmailAppPassword.trim() })
                    }}
                    disabled={connectGmailMutation.isPending}
                  >
                    {connectGmailMutation.isPending ? (
                      <><Loader2 className="h-4 w-4 animate-spin mr-1" /> Connecting...</>
                    ) : (
                      'Save & Connect'
                    )}
                  </Button>
                </div>
              )}
            </div>

            {/* Slack */}
            <div className="border rounded-lg overflow-hidden">
              <div className="flex items-center justify-between p-4">
                <div className="flex items-center gap-3">
                  <div className="h-10 w-10 rounded-lg bg-purple-100 dark:bg-purple-950 flex items-center justify-center">
                    <svg className="h-5 w-5 text-purple-600" viewBox="0 0 24 24" fill="currentColor">
                      <path d="M5.042 15.165a2.528 2.528 0 0 1-2.52 2.523A2.528 2.528 0 0 1 0 15.165a2.527 2.527 0 0 1 2.522-2.52h2.52v2.52zM6.313 15.165a2.527 2.527 0 0 1 2.521-2.52 2.527 2.527 0 0 1 2.521 2.52v6.313A2.528 2.528 0 0 1 8.834 24a2.528 2.528 0 0 1-2.521-2.522v-6.313zM8.834 5.042a2.528 2.528 0 0 1-2.521-2.52A2.528 2.528 0 0 1 8.834 0a2.528 2.528 0 0 1 2.521 2.522v2.52H8.834zM8.834 6.313a2.528 2.528 0 0 1 2.521 2.521 2.528 2.528 0 0 1-2.521 2.521H2.522A2.528 2.528 0 0 1 0 8.834a2.528 2.528 0 0 1 2.522-2.521h6.312zM18.956 8.834a2.528 2.528 0 0 1 2.522-2.521A2.528 2.528 0 0 1 24 8.834a2.528 2.528 0 0 1-2.522 2.521h-2.522V8.834zM17.688 8.834a2.528 2.528 0 0 1-2.523 2.521 2.527 2.527 0 0 1-2.52-2.521V2.522A2.527 2.527 0 0 1 15.165 0a2.528 2.528 0 0 1 2.523 2.522v6.312zM15.165 18.956a2.528 2.528 0 0 1 2.523 2.522A2.528 2.528 0 0 1 15.165 24a2.527 2.527 0 0 1-2.52-2.522v-2.522h2.52zM15.165 17.688a2.527 2.527 0 0 1-2.52-2.523 2.526 2.526 0 0 1 2.52-2.52h6.313A2.527 2.527 0 0 1 24 15.165a2.528 2.528 0 0 1-2.522 2.523h-6.313z" />
                    </svg>
                  </div>
                  <div>
                    <p className="font-medium">Slack</p>
                    {slackIntegration ? (
                      <div className="space-y-0.5">
                        <p className="text-xs text-muted-foreground">
                          Team: {slackIntegration.metadata?.team_id || 'Connected'}
                        </p>
                        {slackIntegration.last_synced_at && (
                          <p className="text-xs text-muted-foreground">
                            Last synced: {formatRelativeTime(slackIntegration.last_synced_at)}
                          </p>
                        )}
                      </div>
                    ) : (
                      <p className="text-xs text-muted-foreground">
                        Process messages and mentions
                      </p>
                    )}
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  {slackIntegration ? (
                    <>
                      <Badge variant="default" className="bg-green-600">
                        <CheckCircle2 className="h-3 w-3 mr-1" />
                        Connected
                      </Badge>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => integrationSyncMutation.mutate(slackIntegration.id)}
                        disabled={integrationSyncMutation.isPending}
                        title="Sync now"
                      >
                        {integrationSyncMutation.isPending ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <RefreshCw className="h-4 w-4" />
                        )}
                      </Button>                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handleDisconnect(slackIntegration.id, 'Slack')}
                        disabled={disconnectingId === slackIntegration.id}
                        className="text-red-600 hover:text-red-700 hover:bg-red-50"
                        title="Disconnect"
                      >
                        {disconnectingId === slackIntegration.id ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Link2Off className="h-4 w-4" />
                        )}
                      </Button>
                    </>
                  ) : (
                    <Button
                      size="sm"
                      onClick={() => startSlackOAuthMutation.mutate()}
                      disabled={startSlackOAuthMutation.isPending}
                    >
                      {startSlackOAuthMutation.isPending ? (
                        <><Loader2 className="h-4 w-4 animate-spin mr-1" /> Connecting...</>
                      ) : (
                        <>
                          <Link2 className="h-4 w-4 mr-1" />
                          Connect
                        </>
                      )}
                    </Button>
                  )}
                </div>
              </div>
            </div>

            {/* Jira */}
            <div className="border rounded-lg overflow-hidden">
              <div className="flex items-center justify-between p-4">
                <div className="flex items-center gap-3">
                  <div className="h-10 w-10 rounded-lg bg-blue-100 dark:bg-blue-950 flex items-center justify-center">
                    <svg className="h-5 w-5 text-blue-600" viewBox="0 0 24 24" fill="currentColor">
                      <path d="M11.571 11.513H0a5.218 5.218 0 0 0 5.232 5.215h2.13v2.057A5.215 5.215 0 0 0 12.575 24V12.518a1.005 1.005 0 0 0-1.005-1.005zm5.723-5.756H5.736a5.215 5.215 0 0 0 5.215 5.214h2.129v2.058a5.218 5.218 0 0 0 5.215 5.214V6.758a1.001 1.001 0 0 0-1.001-1.001zM23.013 0H11.455a5.215 5.215 0 0 0 5.215 5.215h2.129v2.057A5.215 5.215 0 0 0 24.013 12.5V1.005A1.005 1.005 0 0 0 23.013 0z" />
                    </svg>
                  </div>
                  <div>
                    <p className="font-medium">Jira</p>
                    {jiraIntegration ? (
                      <div className="space-y-0.5">
                        <p className="text-xs text-muted-foreground">
                          {jiraIntegration.metadata?.domain || 'Connected'}
                        </p>
                        {jiraIntegration.last_synced_at && (
                          <p className="text-xs text-muted-foreground">
                            Last synced: {formatRelativeTime(jiraIntegration.last_synced_at)}
                          </p>
                        )}
                      </div>
                    ) : (
                      <p className="text-xs text-muted-foreground">
                        Sync tasks with Jira issues
                      </p>
                    )}
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  {jiraIntegration ? (
                    <>
                      <Badge variant="default" className="bg-green-600">
                        <CheckCircle2 className="h-3 w-3 mr-1" />
                        Connected
                      </Badge>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => integrationSyncMutation.mutate(jiraIntegration.id)}
                        disabled={integrationSyncMutation.isPending}
                        title="Sync now"
                      >
                        {integrationSyncMutation.isPending ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <RefreshCw className="h-4 w-4" />
                        )}
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handleDisconnect(jiraIntegration.id, 'Jira')}
                        disabled={disconnectingId === jiraIntegration.id}
                        className="text-red-600 hover:text-red-700 hover:bg-red-50"
                        title="Disconnect"
                      >
                        {disconnectingId === jiraIntegration.id ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Link2Off className="h-4 w-4" />
                        )}
                      </Button>
                    </>
                  ) : (
                    <Button
                      size="sm"
                      variant={showJiraForm ? 'outline' : 'default'}
                      onClick={() => setShowJiraForm((v) => !v)}
                    >
                      {showJiraForm ? (
                        'Cancel'
                      ) : (
                        <>
                          <Link2 className="h-4 w-4 mr-1" />
                          Connect
                        </>
                      )}
                    </Button>
                  )}
                </div>
              </div>

              {/* Credentials form — shown when not connected and user clicked Connect */}
              {!jiraIntegration && showJiraForm && (
                <div className="border-t bg-muted/30 px-4 py-4 space-y-3">
                  <p className="text-xs text-muted-foreground">
                    Enter your Jira Cloud domain, email, and{' '}
                    <a
                      href="https://id.atlassian.com/manage-profile/security/api-tokens"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="underline text-blue-600 dark:text-blue-400"
                    >
                      API token
                    </a>
                    . Your credentials are stored only for your account.
                  </p>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <div className="space-y-1">
                      <Label htmlFor="jira-domain">Jira Domain</Label>
                      <Input
                        id="jira-domain"
                        type="text"
                        placeholder="yourcompany.atlassian.net"
                        value={jiraDomain}
                        onChange={(e) => setJiraDomain(e.target.value)}
                        disabled={connectJiraMutation.isPending}
                      />
                    </div>
                    <div className="space-y-1">
                      <Label htmlFor="jira-email">Email</Label>
                      <Input
                        id="jira-email"
                        type="email"
                        placeholder="you@company.com"
                        value={jiraEmail}
                        onChange={(e) => setJiraEmail(e.target.value)}
                        disabled={connectJiraMutation.isPending}
                      />
                    </div>
                    <div className="space-y-1">
                      <Label htmlFor="jira-api-token">API Token</Label>
                      <Input
                        id="jira-api-token"
                        type="password"
                        placeholder="ATATT3xFfGF0..."
                        value={jiraApiToken}
                        onChange={(e) => setJiraApiToken(e.target.value)}
                        disabled={connectJiraMutation.isPending}
                      />
                    </div>
                    <div className="space-y-1">
                      <Label htmlFor="jira-project-key">Project Key (Optional)</Label>
                      <Input
                        id="jira-project-key"
                        type="text"
                        placeholder="PROJ"
                        value={jiraProjectKey}
                        onChange={(e) => setJiraProjectKey(e.target.value)}
                        disabled={connectJiraMutation.isPending}
                      />
                    </div>
                  </div>
                  <Button
                    size="sm"
                    onClick={() => {
                      if (!jiraDomain.trim() || !jiraEmail.trim() || !jiraApiToken.trim()) {
                        setIntegrationMessage({ type: 'error', text: 'Please enter domain, email and API token.' })
                        setTimeout(() => setIntegrationMessage(null), 4000)
                        return
                      }
                      connectJiraMutation.mutate({
                        domain: jiraDomain.trim(),
                        email: jiraEmail.trim(),
                        api_token: jiraApiToken.trim(),
                        project_key: jiraProjectKey.trim() || undefined
                      })
                    }}
                    disabled={connectJiraMutation.isPending}
                  >
                    {connectJiraMutation.isPending ? (
                      <><Loader2 className="h-4 w-4 animate-spin mr-1" /> Connecting...</>
                    ) : (
                      'Connect'
                    )}
                  </Button>
                </div>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* About */}
      <Card>
        <CardHeader>
          <CardTitle>About Synkro</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2 text-sm text-muted-foreground">
            <p>Version: 1.0.0</p>
            <p>AI-Powered Workspace Orchestration System</p>
            <p>Built with Next.js, FastAPI, and Groq AI</p>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
