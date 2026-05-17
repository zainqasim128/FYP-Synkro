'use client'

import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { integrationsApi } from '@/lib/api'
import { ActionItem } from '@/types'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Loader2, ExternalLink, RefreshCw, CheckCircle2, XCircle, AlertCircle } from 'lucide-react'

interface SyncResult {
  task_id: string
  status: 'created' | 'already_synced' | 'error'
  jira_key?: string
  jira_url?: string
  error?: string
}

interface Props {
  convertedItems: ActionItem[]
  jiraDomain?: string
}

export default function JiraSyncPanel({ convertedItems, jiraDomain }: Props) {
  const syncableItems = convertedItems.filter((i) => i.task_id)
  const [results, setResults] = useState<Record<string, SyncResult>>({})

  const bulkSyncMutation = useMutation({
    mutationFn: (taskIds: string[]) =>
      integrationsApi.bulkSyncJira(taskIds).then((res) => res.data as SyncResult[]),
    onSuccess: (data) => {
      const map: Record<string, SyncResult> = {}
      for (const r of data) map[r.task_id] = r
      setResults((prev) => ({ ...prev, ...map }))
    },
  })

  const handlePushAll = () => {
    const unsynced = syncableItems
      .filter((i) => {
        const r = results[i.task_id!]
        return !r || r.status === 'error'
      })
      .map((i) => i.task_id!)
    if (unsynced.length) bulkSyncMutation.mutate(unsynced)
  }

  const handleSyncOne = (taskId: string) => {
    bulkSyncMutation.mutate([taskId])
  }

  if (syncableItems.length === 0) return null

  const allSynced = syncableItems.every((i) => {
    const r = results[i.task_id!]
    return r?.status === 'created' || r?.status === 'already_synced'
  })

  const unsyncedCount = syncableItems.filter((i) => {
    const r = results[i.task_id!]
    return !r || r.status === 'error'
  }).length

  return (
    <div className="border rounded-lg overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 bg-blue-50 dark:bg-blue-950 border-b">
        <div className="flex items-center gap-2">
          <svg className="h-4 w-4 text-blue-600" viewBox="0 0 24 24" fill="currentColor">
            <path d="M11.571 11.513H0a5.218 5.218 0 0 0 5.232 5.215h2.13v2.057A5.215 5.215 0 0 0 12.575 24V12.518a1.005 1.005 0 0 0-1.005-1.005zm5.723-5.756H5.736a5.215 5.215 0 0 0 5.215 5.214h2.129v2.058a5.218 5.218 0 0 0 5.215 5.214V6.758a1.001 1.001 0 0 0-1.001-1.001zM23.013 0H11.455a5.215 5.215 0 0 0 5.215 5.215h2.129v2.057A5.215 5.215 0 0 0 24.013 12.5V1.005A1.005 1.005 0 0 0 23.013 0z" />
          </svg>
          <span className="text-sm font-medium text-blue-900 dark:text-blue-200">
            Push to Jira
          </span>
          <Badge variant="secondary" className="text-xs">
            {syncableItems.length} task{syncableItems.length !== 1 ? 's' : ''}
          </Badge>
        </div>
        <Button
          size="sm"
          onClick={handlePushAll}
          disabled={bulkSyncMutation.isPending || allSynced}
          className="gap-2 bg-blue-600 hover:bg-blue-700 text-white"
        >
          {bulkSyncMutation.isPending ? (
            <><Loader2 className="h-3 w-3 animate-spin" /> Syncing...</>
          ) : allSynced ? (
            <><CheckCircle2 className="h-3 w-3" /> All Synced</>
          ) : (
            <>
              <svg className="h-3 w-3" viewBox="0 0 24 24" fill="currentColor">
                <path d="M11.571 11.513H0a5.218 5.218 0 0 0 5.232 5.215h2.13v2.057A5.215 5.215 0 0 0 12.575 24V12.518a1.005 1.005 0 0 0-1.005-1.005zm5.723-5.756H5.736a5.215 5.215 0 0 0 5.215 5.214h2.129v2.058a5.218 5.218 0 0 0 5.215 5.214V6.758a1.001 1.001 0 0 0-1.001-1.001zM23.013 0H11.455a5.215 5.215 0 0 0 5.215 5.215h2.129v2.057A5.215 5.215 0 0 0 24.013 12.5V1.005A1.005 1.005 0 0 0 23.013 0z" />
              </svg>
              Push {unsyncedCount} to Jira
            </>
          )}
        </Button>
      </div>

      {/* Error banner */}
      {bulkSyncMutation.isError && (
        <div className="px-4 py-2 bg-red-50 dark:bg-red-950 border-b flex items-center gap-2 text-xs text-red-700 dark:text-red-400">
          <AlertCircle className="h-3 w-3 shrink-0" />
          {(bulkSyncMutation.error as any)?.response?.data?.detail || 'Sync failed. Check your Jira settings.'}
        </div>
      )}

      {/* Task rows */}
      <div className="divide-y">
        {syncableItems.map((item) => {
          const result = results[item.task_id!]
          const isSynced = result?.status === 'created' || result?.status === 'already_synced'
          const isError = result?.status === 'error'
          const isPending = bulkSyncMutation.isPending

          return (
            <div key={item.task_id} className="flex items-center gap-3 px-4 py-3">
              {/* Status icon */}
              <div className="shrink-0 w-5 flex justify-center">
                {isSynced ? (
                  <CheckCircle2 className="h-4 w-4 text-green-600" />
                ) : isError ? (
                  <XCircle className="h-4 w-4 text-red-500" />
                ) : (
                  <div className="h-4 w-4 rounded-full border-2 border-muted-foreground/30" />
                )}
              </div>

              {/* Task info */}
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium truncate">{item.description}</p>
                <div className="flex items-center gap-2 mt-0.5 flex-wrap">
                  {item.assignee_mentioned && (
                    <span className="text-xs text-muted-foreground">
                      → {item.assignee_mentioned}
                    </span>
                  )}
                  {isError && result.error && (
                    <span className="text-xs text-red-500 truncate max-w-[250px]" title={result.error}>
                      {result.error}
                    </span>
                  )}
                </div>
              </div>

              {/* Jira key / re-sync */}
              <div className="flex items-center gap-2 shrink-0">
                {isSynced && result.jira_key && (
                  <a
                    href={result.jira_url || '#'}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-xs font-mono text-blue-600 hover:text-blue-700 hover:underline"
                  >
                    {result.jira_key}
                    <ExternalLink className="h-2.5 w-2.5" />
                  </a>
                )}
                {(isError || !result) && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => handleSyncOne(item.task_id!)}
                    disabled={isPending}
                    className="h-7 w-7 p-0"
                    title="Retry sync"
                  >
                    {isPending ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : (
                      <RefreshCw className="h-3 w-3" />
                    )}
                  </Button>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
