'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { emailApi } from '@/lib/api'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import {
  Mail,
  MailOpen,
  MailCheck,
  RefreshCw,
  Loader2,
  Star,
  Search,
  Inbox,
  ChevronDown,
  ChevronUp,
  X,
  Plus,
  Trash2,
} from 'lucide-react'
import { formatRelativeTime } from '@/lib/utils'

interface EmailItem {
  id: string
  subject: string
  sender: string
  body_preview: string
  received_at: string | null
  is_read: boolean
  is_flagged: boolean
  ai_classification: string | null
}

interface EmailDetail {
  id: string
  subject: string
  sender: string
  to: string
  body: string
  body_preview: string
  received_at: string | null
  is_read: boolean
  is_flagged: boolean
  ai_classification: string | null
  ai_summary: string | null
}

type Filter = 'all' | 'unread' | 'flagged'

function parseSender(sender: string): { name: string; email: string } {
  const match = sender.match(/^(.*?)\s*<(.+?)>$/)
  if (match) return { name: match[1].trim().replace(/"/g, ''), email: match[2] }
  return { name: sender, email: sender }
}

export default function EmailsPage() {
  const queryClient = useQueryClient()
  const [filter, setFilter] = useState<Filter>('all')
  const [search, setSearch] = useState('')
  const [expandedId, setExpandedId] = useState<string | null>(null)

  // Stats
  const { data: statsData } = useQuery({
    queryKey: ['email-stats'],
    queryFn: async () => (await emailApi.getStats()).data,
  })

  // Email list
  const { data: emailsData, isLoading } = useQuery({
    queryKey: ['emails', filter, search],
    queryFn: async () => {
      const params: any = { limit: 50 }
      if (filter === 'unread') params.is_read = false
      if (filter === 'flagged') params.is_flagged = true
      if (search) params.search = search
      return (await emailApi.getEmails(params)).data
    },
  })

  // Email detail (when expanded)
  const { data: emailDetail, isLoading: detailLoading } = useQuery({
    queryKey: ['email-detail', expandedId],
    queryFn: async () => (await emailApi.getEmail(expandedId!)).data as EmailDetail,
    enabled: !!expandedId,
  })

  // Sync mutation
  const syncMutation = useMutation({
    mutationFn: () => emailApi.syncEmails({ limit: 50, days: 15 }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['emails'] })
      queryClient.invalidateQueries({ queryKey: ['email-stats'] })
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
    },
  })

  // Mark as read mutation
  const markReadMutation = useMutation({
    mutationFn: (id: string) => emailApi.markAsRead(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['emails'] })
      queryClient.invalidateQueries({ queryKey: ['email-stats'] })
    },
  })

  // Seed demo mutation
  const seedMutation = useMutation({
    mutationFn: () => emailApi.seedDemo(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['emails'] })
      queryClient.invalidateQueries({ queryKey: ['email-stats'] })
    },
  })

  // Delete mutation
  const deleteMutation = useMutation({
    mutationFn: (id: string) => emailApi.deleteEmail(id),
    onSuccess: (_, id) => {
      if (expandedId === id) setExpandedId(null)
      queryClient.invalidateQueries({ queryKey: ['emails'] })
      queryClient.invalidateQueries({ queryKey: ['email-stats'] })
    },
  })

  const emails: EmailItem[] = emailsData || []
  const stats = statsData || { total: 0, unread: 0, flagged: 0 }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Emails</h1>
          <p className="text-sm text-muted-foreground">
            {stats.total} emails synced &middot; {stats.unread} unread
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={() => seedMutation.mutate()}
            disabled={seedMutation.isPending}
          >
            {seedMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin mr-2" />
            ) : (
              <Plus className="h-4 w-4 mr-2" />
            )}
            {seedMutation.isPending ? 'Loading...' : 'Load Demo'}
          </Button>
          <Button
            onClick={() => syncMutation.mutate()}
            disabled={syncMutation.isPending}
          >
            {syncMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin mr-2" />
            ) : (
              <RefreshCw className="h-4 w-4 mr-2" />
            )}
            {syncMutation.isPending ? 'Syncing...' : 'Sync Gmail'}
          </Button>
        </div>
      </div>

      {/* Sync result message */}
      {syncMutation.isSuccess && (
        <div className="rounded-md bg-green-50 dark:bg-green-950 p-3 text-sm text-green-800 dark:text-green-400">
          {(syncMutation.data as any)?.data?.message || 'Sync complete!'}
          {(syncMutation.data as any)?.data?.tasks_created > 0 && (
            <span className="ml-1 font-medium">
              Check your Tasks dashboard for newly extracted tasks.
            </span>
          )}
        </div>
      )}

      {/* Sync error message */}
      {syncMutation.isError && (
        <div className="rounded-md bg-red-50 dark:bg-red-950 p-3 text-sm text-red-800 dark:text-red-400">
          {(syncMutation.error as any)?.response?.data?.detail || 'Sync failed. Connect Gmail in Settings first.'}
        </div>
      )}

      {/* Seed result message */}
      {seedMutation.isSuccess && (
        <div className="rounded-md bg-green-50 dark:bg-green-950 p-3 text-sm text-green-800 dark:text-green-400">
          {(seedMutation.data as any)?.data?.message || 'Demo emails loaded!'}
        </div>
      )}

      {/* Filters + Search */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex gap-1">
          {(['all', 'unread', 'flagged'] as Filter[]).map((f) => (
            <Button
              key={f}
              variant={filter === f ? 'default' : 'outline'}
              size="sm"
              onClick={() => setFilter(f)}
            >
              {f === 'all' && <Inbox className="h-3 w-3 mr-1" />}
              {f === 'unread' && <Mail className="h-3 w-3 mr-1" />}
              {f === 'flagged' && <Star className="h-3 w-3 mr-1" />}
              {f.charAt(0).toUpperCase() + f.slice(1)}
              {f === 'unread' && stats.unread > 0 && (
                <Badge variant="secondary" className="ml-1 text-xs">{stats.unread}</Badge>
              )}
            </Button>
          ))}
        </div>
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search emails..."
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
      </div>

      {/* Email list */}
      {isLoading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      ) : emails.length === 0 ? (
        <Card className="p-12 text-center">
          <Inbox className="h-12 w-12 mx-auto text-gray-400 mb-4" />
          <p className="text-muted-foreground mb-4">
            {stats.total === 0 ? 'No emails yet' : 'No emails match your filters'}
          </p>
          {stats.total === 0 && (
            <div className="flex gap-3 justify-center">
              <Button variant="outline" onClick={() => seedMutation.mutate()} disabled={seedMutation.isPending}>
                {seedMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <Plus className="h-4 w-4 mr-2" />}
                Load Demo Emails
              </Button>
              <Button onClick={() => syncMutation.mutate()} disabled={syncMutation.isPending}>
                {syncMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <RefreshCw className="h-4 w-4 mr-2" />}
                Sync Gmail
              </Button>
            </div>
          )}
        </Card>
      ) : (
        <Card>
          <CardContent className="p-0 divide-y">
            {emails.map((em) => {
              const isExpanded = expandedId === em.id
              const { name: senderName, email: senderEmail } = parseSender(em.sender)

              const isDeleting = deleteMutation.isPending && (deleteMutation.variables === em.id)
              const isMarkingRead = markReadMutation.isPending && (markReadMutation.variables === em.id)

              return (
                <div key={em.id}>
                  {/* Email row */}
                  <div
                    className={`w-full text-left px-4 py-3 hover:bg-muted/50 transition-colors flex items-start gap-3 ${
                      !em.is_read ? 'bg-blue-50/50 dark:bg-blue-950/20' : ''
                    }`}
                  >
                    {/* Icon */}
                    <button
                      onClick={() => setExpandedId(isExpanded ? null : em.id)}
                      className="mt-0.5 shrink-0"
                    >
                      {em.is_read ? (
                        <MailOpen className="h-4 w-4 text-muted-foreground" />
                      ) : (
                        <Mail className="h-4 w-4 text-blue-600" />
                      )}
                    </button>

                    {/* Content */}
                    <button
                      onClick={() => setExpandedId(isExpanded ? null : em.id)}
                      className="flex-1 min-w-0 text-left"
                    >
                      <div className="flex items-center gap-2">
                        <span className={`text-sm truncate ${!em.is_read ? 'font-semibold' : 'font-medium'}`}>
                          {senderName || senderEmail}
                        </span>
                        {em.is_flagged && <Star className="h-3 w-3 text-yellow-500 fill-yellow-500 shrink-0" />}
                        {em.ai_classification && (
                          <Badge variant="outline" className="text-xs shrink-0">
                            {em.ai_classification}
                          </Badge>
                        )}
                      </div>
                      <p className={`text-sm truncate ${!em.is_read ? 'text-foreground' : 'text-muted-foreground'}`}>
                        {em.subject || '(no subject)'}
                      </p>
                      <p className="text-xs text-muted-foreground truncate mt-0.5">
                        {em.body_preview}
                      </p>
                    </button>

                    {/* Date + expand + actions */}
                    <div className="flex items-center gap-1 shrink-0">
                      <button onClick={() => setExpandedId(isExpanded ? null : em.id)} className="flex items-center gap-1 mr-1">
                        <span className="text-xs text-muted-foreground whitespace-nowrap">
                          {em.received_at ? formatRelativeTime(em.received_at) : ''}
                        </span>
                        {isExpanded ? (
                          <ChevronUp className="h-4 w-4 text-muted-foreground" />
                        ) : (
                          <ChevronDown className="h-4 w-4 text-muted-foreground" />
                        )}
                      </button>
                      {!em.is_read && (
                        <button
                          onClick={() => markReadMutation.mutate(em.id)}
                          disabled={isMarkingRead}
                          className="p-1 rounded hover:bg-green-100 dark:hover:bg-green-950 text-muted-foreground hover:text-green-600 transition-colors disabled:opacity-50"
                          title="Mark as read"
                        >
                          {isMarkingRead ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                          ) : (
                            <MailCheck className="h-4 w-4" />
                          )}
                        </button>
                      )}
                      <button
                        onClick={() => {
                          if (confirm('Delete this email? It will also be removed from Gmail.')) {
                            deleteMutation.mutate(em.id)
                          }
                        }}
                        disabled={isDeleting}
                        className="p-1 rounded hover:bg-red-100 dark:hover:bg-red-950 text-muted-foreground hover:text-red-600 transition-colors disabled:opacity-50"
                        title="Delete email"
                      >
                        {isDeleting ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Trash2 className="h-4 w-4" />
                        )}
                      </button>
                    </div>
                  </div>

                  {/* Expanded body */}
                  {isExpanded && (
                    <div className="px-4 py-4 bg-muted/30 border-t">
                      {detailLoading ? (
                        <div className="flex items-center gap-2 text-sm text-muted-foreground">
                          <Loader2 className="h-4 w-4 animate-spin" />
                          Loading...
                        </div>
                      ) : emailDetail ? (
                        <div className="space-y-3">
                          <div className="flex items-center justify-between">
                            <div>
                              <h3 className="font-semibold">{emailDetail.subject || '(no subject)'}</h3>
                              <p className="text-sm text-muted-foreground">
                                From: {emailDetail.sender}
                              </p>
                              <p className="text-sm text-muted-foreground">
                                To: {emailDetail.to}
                              </p>
                            </div>
                            <span className="text-xs text-muted-foreground">
                              {emailDetail.received_at ? new Date(emailDetail.received_at).toLocaleString() : ''}
                            </span>
                          </div>
                          {emailDetail.ai_summary && (
                            <div className="rounded-md bg-blue-50 dark:bg-blue-950 p-3 text-sm">
                              <p className="font-medium text-blue-800 dark:text-blue-300 mb-1">AI Summary</p>
                              <p className="text-blue-700 dark:text-blue-400">{emailDetail.ai_summary}</p>
                            </div>
                          )}
                          <div className="whitespace-pre-wrap text-sm bg-background rounded-lg p-4 border max-h-[400px] overflow-y-auto">
                            {emailDetail.body || '(empty)'}
                          </div>
                        </div>
                      ) : null}
                    </div>
                  )}
                </div>
              )
            })}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
