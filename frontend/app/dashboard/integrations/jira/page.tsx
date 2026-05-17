'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { integrationsApi } from '@/lib/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import {
  Link2,
  RefreshCw,
  Unlink,
  CheckCircle,
  XCircle,
  AlertTriangle,
  ExternalLink,
  Clock,
} from 'lucide-react'
import { format, parseISO } from 'date-fns'
import type { JiraSyncedTaskItem, JiraSyncedTasksResponse, JiraReSyncResult } from '@/types'

const STATUS_COLORS: Record<string, string> = {
  todo: 'bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300',
  in_progress: 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300',
  done: 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300',
  blocked: 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300',
}

const STATUS_LABELS: Record<string, string> = {
  todo: 'To Do',
  in_progress: 'In Progress',
  done: 'Done',
  blocked: 'Blocked',
}

export default function JiraSyncDashboard() {
  const queryClient = useQueryClient()
  const [reSyncingIds, setReSyncingIds] = useState<Set<string>>(new Set())
  const [unlinkingIds, setUnlinkingIds] = useState<Set<string>>(new Set())
  const [localErrors, setLocalErrors] = useState<Record<string, string>>({})

  const { data, isLoading, isError } = useQuery<JiraSyncedTasksResponse>({
    queryKey: ['jira-synced-tasks'],
    queryFn: async () => (await integrationsApi.getSyncedJiraTasks()).data,
  })

  const reSyncMutation = useMutation({
    mutationFn: (taskId: string) => integrationsApi.reSyncJiraTask(taskId),
    onMutate: (taskId) => {
      setReSyncingIds(prev => new Set(prev).add(taskId))
    },
    onSettled: (res, _err, taskId) => {
      setReSyncingIds(prev => { const s = new Set(prev); s.delete(taskId); return s })
      const result = res?.data as JiraReSyncResult | undefined
      if (result?.status === 'error') {
        setLocalErrors(prev => ({ ...prev, [taskId]: result.error || 'Sync failed' }))
      } else {
        setLocalErrors(prev => { const s = { ...prev }; delete s[taskId]; return s })
      }
      queryClient.invalidateQueries({ queryKey: ['jira-synced-tasks'] })
    },
  })

  const unlinkMutation = useMutation({
    mutationFn: (taskId: string) => integrationsApi.unlinkJiraTask(taskId),
    onMutate: (taskId) => {
      setUnlinkingIds(prev => new Set(prev).add(taskId))
    },
    onSettled: (_res, _err, taskId) => {
      setUnlinkingIds(prev => { const s = new Set(prev); s.delete(taskId); return s })
      queryClient.invalidateQueries({ queryKey: ['jira-synced-tasks'] })
    },
  })

  const syncAllMutation = useMutation({
    mutationFn: () => integrationsApi.syncAllJiraTasks(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['jira-synced-tasks'] })
    },
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
      </div>
    )
  }

  if (isError) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-center dark:border-red-800 dark:bg-red-950">
        <XCircle className="mx-auto h-8 w-8 text-red-500 mb-2" />
        <p className="text-red-700 dark:text-red-300 font-medium">Jira not connected</p>
        <p className="text-sm text-red-500 mt-1">Connect Jira in Settings to use this dashboard.</p>
      </div>
    )
  }

  const tasks = data?.tasks ?? []
  const total = data?.total ?? 0
  const syncedToday = data?.synced_today ?? 0
  const failed = data?.failed ?? 0

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Jira Sync Dashboard</h1>
          <p className="text-sm text-muted-foreground mt-1">Manage all tasks linked to Jira issues</p>
        </div>
        <Button
          onClick={() => syncAllMutation.mutate()}
          disabled={syncAllMutation.isPending || tasks.length === 0}
          className="gap-2"
        >
          <RefreshCw className={`h-4 w-4 ${syncAllMutation.isPending ? 'animate-spin' : ''}`} />
          {syncAllMutation.isPending ? 'Syncing...' : `Sync All (${total})`}
        </Button>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Total Linked</p>
                <p className="text-3xl font-bold">{total}</p>
              </div>
              <Link2 className="h-8 w-8 text-blue-500" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Synced Today</p>
                <p className="text-3xl font-bold">{syncedToday}</p>
              </div>
              <CheckCircle className="h-8 w-8 text-green-500" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Sync Errors</p>
                <p className={`text-3xl font-bold ${failed > 0 ? 'text-red-600' : ''}`}>{failed}</p>
              </div>
              <AlertTriangle className={`h-8 w-8 ${failed > 0 ? 'text-red-500' : 'text-gray-300 dark:text-gray-600'}`} />
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Link2 className="h-5 w-5" />
            Linked Tasks
          </CardTitle>
        </CardHeader>
        <CardContent>
          {tasks.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground">
              <Link2 className="mx-auto h-10 w-10 mb-3 opacity-30" />
              <p className="font-medium">No tasks linked to Jira yet</p>
              <p className="text-sm mt-1">Push tasks to Jira from the meeting Action Items tab or task view.</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-200 dark:border-gray-700 text-left">
                    <th className="pb-3 pr-4 font-medium text-muted-foreground">Task</th>
                    <th className="pb-3 pr-4 font-medium text-muted-foreground">Jira Issue</th>
                    <th className="pb-3 pr-4 font-medium text-muted-foreground">Status</th>
                    <th className="pb-3 pr-4 font-medium text-muted-foreground hidden md:table-cell">Assignee</th>
                    <th className="pb-3 pr-4 font-medium text-muted-foreground hidden lg:table-cell">Last Synced</th>
                    <th className="pb-3 font-medium text-muted-foreground text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                  {tasks.map((task) => {
                    const hasError = !!(task.jira_sync_error || localErrors[task.id])
                    const errorMsg = task.jira_sync_error || localErrors[task.id]
                    const isReSyncing = reSyncingIds.has(task.id)
                    const isUnlinking = unlinkingIds.has(task.id)

                    return (
                      <tr key={task.id} className={hasError ? 'bg-red-50 dark:bg-red-950/20' : ''}>
                        <td className="py-3 pr-4">
                          <div className="flex items-start gap-2">
                            {hasError
                              ? <XCircle className="h-4 w-4 text-red-500 mt-0.5 shrink-0" />
                              : <CheckCircle className="h-4 w-4 text-green-500 mt-0.5 shrink-0" />
                            }
                            <div className="min-w-0">
                              <p className="font-medium text-gray-900 dark:text-gray-100 truncate max-w-xs">{task.title}</p>
                              {hasError && (
                                <p className="text-xs text-red-600 dark:text-red-400 mt-0.5 truncate max-w-xs" title={errorMsg}>
                                  {errorMsg}
                                </p>
                              )}
                            </div>
                          </div>
                        </td>
                        <td className="py-3 pr-4">
                          {task.jira_url ? (
                            <a href={task.jira_url} target="_blank" rel="noopener noreferrer"
                              className="inline-flex items-center gap-1 text-blue-600 hover:text-blue-800 dark:text-blue-400 font-mono text-xs">
                              {task.external_id}
                              <ExternalLink className="h-3 w-3" />
                            </a>
                          ) : (
                            <span className="font-mono text-xs text-gray-500">{task.external_id}</span>
                          )}
                        </td>
                        <td className="py-3 pr-4">
                          <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_COLORS[task.status] ?? 'bg-gray-100 text-gray-600'}`}>
                            {STATUS_LABELS[task.status] ?? task.status}
                          </span>
                        </td>
                        <td className="py-3 pr-4 hidden md:table-cell text-gray-600 dark:text-gray-400">
                          {task.assignee_name || '—'}
                        </td>
                        <td className="py-3 pr-4 hidden lg:table-cell">
                          {task.jira_synced_at ? (
                            <span className="inline-flex items-center gap-1 text-xs text-gray-500">
                              <Clock className="h-3 w-3" />
                              {format(parseISO(task.jira_synced_at), 'MMM d, HH:mm')}
                            </span>
                          ) : (
                            <span className="text-xs text-gray-400">Never</span>
                          )}
                        </td>
                        <td className="py-3 text-right">
                          <div className="flex items-center justify-end gap-2">
                            <Button variant="ghost" size="sm" className="h-7 px-2 text-xs"
                              onClick={() => reSyncMutation.mutate(task.id)}
                              disabled={isReSyncing || isUnlinking} title="Re-sync to Jira">
                              <RefreshCw className={`h-3 w-3 ${isReSyncing ? 'animate-spin' : ''}`} />
                              <span className="ml-1 hidden sm:inline">Re-sync</span>
                            </Button>
                            <Button variant="ghost" size="sm"
                              className="h-7 px-2 text-xs text-red-600 hover:text-red-700 hover:bg-red-50 dark:hover:bg-red-950"
                              onClick={() => unlinkMutation.mutate(task.id)}
                              disabled={isReSyncing || isUnlinking} title="Unlink (does not delete the Jira issue)">
                              <Unlink className="h-3 w-3" />
                              <span className="ml-1 hidden sm:inline">Unlink</span>
                            </Button>
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
