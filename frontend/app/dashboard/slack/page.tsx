'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { messagesApi, integrationsApi } from '@/lib/api'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import {
  MessageSquare,
  RefreshCw,
  Loader2,
  Search,
  Hash,
  X,
  AtSign,
  Download,
} from 'lucide-react'
import { formatRelativeTime } from '@/lib/utils'
import Link from 'next/link'

interface SlackMessage {
  id: string
  platform: string
  sender_name: string | null
  sender_email: string | null
  content: string
  timestamp: string | null
  thread_id: string | null
  intent: string | null
  processed: boolean
}

const INTENT_COLORS: Record<string, string> = {
  task_request: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300',
  blocker: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300',
  urgent_issue: 'bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-300',
  question: 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-300',
  information: 'bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300',
  casual: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300',
}

export default function SlackPage() {
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const [syncMsg, setSyncMsg] = useState('')

  const { data: integrationsData } = useQuery({
    queryKey: ['integrations'],
    queryFn: async () => (await integrationsApi.getIntegrations()).data,
  })

  const slackIntegration = (integrationsData as any[])?.find((i: any) => i.platform === 'slack')

  const syncMutation = useMutation({
    mutationFn: () => integrationsApi.syncIntegration(slackIntegration.id),
    onSuccess: (res: any) => {
      setSyncMsg(res.data?.message || 'Sync complete')
      queryClient.invalidateQueries({ queryKey: ['slack-messages'] })
      queryClient.invalidateQueries({ queryKey: ['message-stats'] })
      setTimeout(() => setSyncMsg(''), 4000)
    },
  })

  const { data: stats } = useQuery({
    queryKey: ['message-stats'],
    queryFn: async () => (await messagesApi.getStats()).data,
    refetchInterval: 5000,
  })

  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ['slack-messages', search],
    queryFn: async () => {
      const params: any = { platform: 'slack', limit: 100 }
      if (search) params.search = search
      return (await messagesApi.getMessages(params)).data as SlackMessage[]
    },
    refetchInterval: 5000,
  })

  const messages = data || []
  const slackCount = stats?.slack ?? 0

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Slack Messages</h1>
          <p className="text-sm text-muted-foreground">
            {slackCount} messages synced from Slack
          </p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <Link href="/dashboard/slack/dms">
            <Button variant="outline">
              <AtSign className="h-4 w-4 mr-2" />
              Direct Messages
            </Button>
          </Link>
          {slackIntegration && (
            <Button
              variant="outline"
              onClick={() => syncMutation.mutate()}
              disabled={syncMutation.isPending}
            >
              {syncMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin mr-2" />
              ) : (
                <Download className="h-4 w-4 mr-2" />
              )}
              {syncMutation.isPending ? 'Syncing...' : 'Sync from Slack'}
            </Button>
          )}
          <Button
            variant="outline"
            onClick={() => {
              queryClient.invalidateQueries({ queryKey: ['slack-messages'] })
              queryClient.invalidateQueries({ queryKey: ['message-stats'] })
              refetch()
            }}
            disabled={isFetching}
          >
            {isFetching ? (
              <Loader2 className="h-4 w-4 animate-spin mr-2" />
            ) : (
              <RefreshCw className="h-4 w-4 mr-2" />
            )}
            {isFetching ? 'Refreshing...' : 'Refresh'}
          </Button>
        </div>
      </div>

      {syncMsg && (
        <div className="rounded-md bg-green-50 dark:bg-green-950 border border-green-200 dark:border-green-800 px-4 py-2 text-sm text-green-800 dark:text-green-300">
          {syncMsg}
        </div>
      )}

      {/* Search */}
      <div className="relative max-w-sm">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          placeholder="Search messages..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="pl-9"
        />
        {search && (
          <button
            onClick={() => setSearch('')}
            className="absolute right-3 top-1/2 -translate-y-1/2"
          >
            <X className="h-4 w-4 text-muted-foreground" />
          </button>
        )}
      </div>

      {/* Message list */}
      {isLoading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      ) : messages.length === 0 ? (
        <Card className="p-12 text-center">
          <MessageSquare className="h-12 w-12 mx-auto text-gray-400 mb-4" />
          <p className="text-muted-foreground mb-2">
            {slackCount === 0
              ? 'No Slack messages yet'
              : 'No messages match your search'}
          </p>
          {slackCount === 0 && (
            <p className="text-sm text-muted-foreground">
              Send a message in your Slack workspace and it will appear here automatically.
            </p>
          )}
        </Card>
      ) : (
        <Card>
          <CardContent className="p-0 divide-y">
            {messages.map((msg) => (
              <div key={msg.id} className="px-4 py-3 hover:bg-muted/50 transition-colors flex items-start gap-3">
                {/* Avatar */}
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#4A154B] text-white text-xs font-bold mt-0.5">
                  {msg.sender_name
                    ? msg.sender_name.slice(0, 2).toUpperCase()
                    : <Hash className="h-4 w-4" />}
                </div>

                {/* Content */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-semibold">
                      {msg.sender_name || 'Unknown'}
                    </span>
                    {msg.intent && (
                      <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${INTENT_COLORS[msg.intent] || INTENT_COLORS.information}`}>
                        {msg.intent.replace('_', ' ')}
                      </span>
                    )}
                    {msg.processed && (
                      <Badge variant="outline" className="text-xs">AI processed</Badge>
                    )}
                  </div>
                  <p className="text-sm text-foreground mt-0.5 whitespace-pre-wrap break-words">
                    {msg.content}
                  </p>
                </div>

                {/* Time */}
                <span className="text-xs text-muted-foreground whitespace-nowrap shrink-0 mt-1">
                  {msg.timestamp ? formatRelativeTime(msg.timestamp) : ''}
                </span>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
