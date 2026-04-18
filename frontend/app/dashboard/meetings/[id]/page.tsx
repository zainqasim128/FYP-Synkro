'use client'

import { useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { meetingApi } from '@/lib/api'
import { Meeting, ActionItem } from '@/types'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { formatDateTime } from '@/lib/utils'
import {
  ArrowLeft,
  Clock,
  FileText,
  CheckCircle2,
  XCircle,
  Loader2,
  AlertCircle,
  Mic,
  Sparkles,
  RotateCcw,
  ExternalLink,
} from 'lucide-react'

const statusConfig: Record<string, { label: string; variant: 'default' | 'secondary' | 'destructive' | 'outline' }> = {
  scheduled: { label: 'Scheduled', variant: 'outline' },
  processing: { label: 'Processing', variant: 'secondary' },
  transcribed: { label: 'Transcribed', variant: 'default' },
  completed: { label: 'Completed', variant: 'default' },
  failed: { label: 'Failed', variant: 'destructive' },
}

export default function MeetingDetailPage() {
  const params = useParams()
  const router = useRouter()
  const queryClient = useQueryClient()
  const meetingId = params.id as string

  const [activeTab, setActiveTab] = useState<'summary' | 'transcript' | 'actions'>('summary')
  // Track which action items are currently being converted / rejected
  const [convertingIds, setConvertingIds] = useState<Set<string>>(new Set())
  const [rejectingIds, setRejectingIds] = useState<Set<string>>(new Set())
  const [convertedCount, setConvertedCount] = useState(0)

  const { data: meeting, isLoading, error } = useQuery<Meeting>({
    queryKey: ['meeting', meetingId],
    queryFn: async () => {
      const { data } = await meetingApi.getMeeting(meetingId)
      return data
    },
    refetchInterval: (query) => {
      const m = query.state.data
      return m?.status === 'processing' ? 5000 : false
    },
  })

  const convertMutation = useMutation({
    mutationFn: (actionItemId: string) =>
      meetingApi.convertActionItem(meetingId, actionItemId),
    onMutate: (actionItemId) => {
      setConvertingIds((prev) => new Set(prev).add(actionItemId))
    },
    onSuccess: () => {
      setConvertedCount((c) => c + 1)
      queryClient.invalidateQueries({ queryKey: ['meeting', meetingId] })
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
      queryClient.invalidateQueries({ queryKey: ['task-stats'] })
      queryClient.invalidateQueries({ queryKey: ['recent-tasks'] })
    },
    onSettled: (_data, _err, actionItemId) => {
      setConvertingIds((prev) => {
        const next = new Set(prev)
        next.delete(actionItemId)
        return next
      })
    },
  })

  const rejectMutation = useMutation({
    mutationFn: (actionItemId: string) =>
      meetingApi.rejectActionItem(meetingId, actionItemId),
    onMutate: (actionItemId) => {
      setRejectingIds((prev) => new Set(prev).add(actionItemId))
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['meeting', meetingId] })
    },
    onSettled: (_data, _err, actionItemId) => {
      setRejectingIds((prev) => {
        const next = new Set(prev)
        next.delete(actionItemId)
        return next
      })
    },
  })

  const retryMutation = useMutation({
    mutationFn: () => meetingApi.retryMeeting(meetingId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['meeting', meetingId] })
    },
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    )
  }

  if (error || !meeting) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-4">
        <AlertCircle className="h-12 w-12 text-destructive" />
        <p className="text-muted-foreground">Meeting not found</p>
        <Button variant="outline" onClick={() => router.push('/dashboard/meetings')}>
          <ArrowLeft className="h-4 w-4 mr-2" />
          Back to Meetings
        </Button>
      </div>
    )
  }

  const statusInfo = statusConfig[meeting.status] || statusConfig.scheduled
  const pendingItems = meeting.action_items?.filter((a) => a.status === 'pending') || []
  const convertedItems = meeting.action_items?.filter((a) => a.status === 'converted') || []
  const rejectedItems = meeting.action_items?.filter((a) => a.status === 'rejected') || []

  return (
    <div className="space-y-6 max-w-5xl">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <button
            onClick={() => router.push('/dashboard/meetings')}
            className="text-sm text-muted-foreground hover:text-foreground flex items-center gap-1 mb-2"
          >
            <ArrowLeft className="h-3 w-3" />
            Back to Meetings
          </button>
          <h1 className="text-2xl font-bold">{meeting.title}</h1>
          <div className="flex items-center gap-3 text-sm text-muted-foreground">
            <span>{formatDateTime(meeting.created_at)}</span>
            {meeting.duration_minutes && (
              <span className="flex items-center gap-1">
                <Clock className="h-3 w-3" />
                {meeting.duration_minutes} min
              </span>
            )}
          </div>
        </div>
        <Badge variant={statusInfo.variant}>{statusInfo.label}</Badge>
      </div>

      {/* Processing indicator */}
      {(meeting.status === 'processing' || meeting.status === 'transcribed') && (
        <Card className="border-blue-200 bg-blue-50">
          <CardContent className="flex items-center gap-3 py-4">
            <Loader2 className="h-5 w-5 animate-spin text-blue-600" />
            <div>
              <p className="font-medium text-blue-900">
                {meeting.status === 'processing' ? 'Transcribing audio...' : 'Generating summary...'}
              </p>
              <p className="text-sm text-blue-700">
                {meeting.status === 'processing'
                  ? 'Converting speech to text. This usually takes a few minutes depending on recording length.'
                  : 'AI is analyzing the transcript and extracting action items. Almost done!'}
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Failed indicator with retry */}
      {meeting.status === 'failed' && (
        <Card className="border-red-200 bg-red-50">
          <CardContent className="flex items-center justify-between gap-3 py-4">
            <div className="flex items-center gap-3">
              <AlertCircle className="h-5 w-5 text-red-600" />
              <div>
                <p className="font-medium text-red-900">Transcription failed</p>
                <p className="text-sm text-red-700">
                  Something went wrong during processing. You can retry the transcription.
                </p>
              </div>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => retryMutation.mutate()}
              disabled={retryMutation.isPending}
              className="shrink-0"
            >
              {retryMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin mr-1" />
              ) : (
                <RotateCcw className="h-4 w-4 mr-1" />
              )}
              Retry
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Tabs */}
      {meeting.status !== 'processing' && meeting.status !== 'scheduled' && (
        <>
          <div className="flex border-b">
            <button
              onClick={() => setActiveTab('summary')}
              className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                activeTab === 'summary'
                  ? 'border-primary text-primary'
                  : 'border-transparent text-muted-foreground hover:text-foreground'
              }`}
            >
              <Sparkles className="h-4 w-4 inline mr-1" />
              Summary
            </button>
            <button
              onClick={() => setActiveTab('transcript')}
              className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                activeTab === 'transcript'
                  ? 'border-primary text-primary'
                  : 'border-transparent text-muted-foreground hover:text-foreground'
              }`}
            >
              <FileText className="h-4 w-4 inline mr-1" />
              Transcript
            </button>
            <button
              onClick={() => setActiveTab('actions')}
              className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                activeTab === 'actions'
                  ? 'border-primary text-primary'
                  : 'border-transparent text-muted-foreground hover:text-foreground'
              }`}
            >
              <CheckCircle2 className="h-4 w-4 inline mr-1" />
              Action Items
              {pendingItems.length > 0 && (
                <Badge variant="secondary" className="ml-2 text-xs">
                  {pendingItems.length}
                </Badge>
              )}
            </button>
          </div>

          {/* Summary Tab */}
          {activeTab === 'summary' && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Sparkles className="h-5 w-5" />
                  AI Summary
                </CardTitle>
                <CardDescription>
                  Generated by AI from the meeting transcript
                </CardDescription>
              </CardHeader>
              <CardContent>
                {meeting.summary ? (
                  <div className="prose prose-sm max-w-none whitespace-pre-wrap">
                    {meeting.summary}
                  </div>
                ) : (
                  <p className="text-muted-foreground italic">
                    No summary available yet.
                  </p>
                )}
              </CardContent>
            </Card>
          )}

          {/* Transcript Tab */}
          {activeTab === 'transcript' && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Mic className="h-5 w-5" />
                  Transcript
                </CardTitle>
                <CardDescription>
                  Full transcription of the meeting recording
                </CardDescription>
              </CardHeader>
              <CardContent>
                {meeting.transcript ? (
                  <div className="prose prose-sm max-w-none whitespace-pre-wrap font-mono text-sm bg-muted/50 p-4 rounded-lg max-h-[600px] overflow-y-auto">
                    {meeting.transcript}
                  </div>
                ) : (
                  <p className="text-muted-foreground italic">
                    No transcript available yet.
                  </p>
                )}
              </CardContent>
            </Card>
          )}

          {/* Action Items Tab */}
          {activeTab === 'actions' && (
            <div className="space-y-4">
              {/* Success banner */}
              {convertedCount > 0 && (
                <div className="flex items-center justify-between gap-3 rounded-lg border border-green-200 bg-green-50 dark:bg-green-950 dark:border-green-800 px-4 py-3">
                  <div className="flex items-center gap-2 text-sm text-green-800 dark:text-green-200">
                    <CheckCircle2 className="h-4 w-4 shrink-0" />
                    {convertedCount} task{convertedCount !== 1 ? 's' : ''} created successfully
                  </div>
                  <Button
                    size="sm"
                    variant="outline"
                    className="shrink-0 border-green-300 text-green-800 hover:bg-green-100 dark:text-green-200 dark:border-green-700"
                    onClick={() => router.push('/dashboard/tasks')}
                  >
                    <ExternalLink className="h-3 w-3 mr-1" />
                    View Tasks
                  </Button>
                </div>
              )}

              {/* Pending items */}
              {pendingItems.length > 0 && (
                <Card>
                  <CardHeader>
                    <CardTitle className="text-lg">Pending Action Items</CardTitle>
                    <CardDescription>
                      Review and convert these AI-extracted items to tasks
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    {pendingItems.map((item) => (
                      <ActionItemCard
                        key={item.id}
                        item={item}
                        onConvert={() => convertMutation.mutate(item.id)}
                        onReject={() => rejectMutation.mutate(item.id)}
                        isConverting={convertingIds.has(item.id)}
                        isRejecting={rejectingIds.has(item.id)}
                      />
                    ))}
                  </CardContent>
                </Card>
              )}

              {/* Converted items */}
              {convertedItems.length > 0 && (
                <Card>
                  <CardHeader>
                    <CardTitle className="text-lg text-green-700 dark:text-green-400">
                      Converted to Tasks ({convertedItems.length})
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-2">
                    {convertedItems.map((item) => (
                      <div
                        key={item.id}
                        className="flex items-center gap-3 p-3 bg-green-50 dark:bg-green-950/40 rounded-lg"
                      >
                        <CheckCircle2 className="h-4 w-4 text-green-600 shrink-0" />
                        <span className="text-sm">{item.description}</span>
                      </div>
                    ))}
                  </CardContent>
                </Card>
              )}

              {/* Rejected items */}
              {rejectedItems.length > 0 && (
                <Card>
                  <CardHeader>
                    <CardTitle className="text-lg text-muted-foreground">
                      Rejected ({rejectedItems.length})
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-2">
                    {rejectedItems.map((item) => (
                      <div
                        key={item.id}
                        className="flex items-center gap-3 p-3 bg-muted/50 rounded-lg"
                      >
                        <XCircle className="h-4 w-4 text-muted-foreground shrink-0" />
                        <span className="text-sm text-muted-foreground line-through">
                          {item.description}
                        </span>
                      </div>
                    ))}
                  </CardContent>
                </Card>
              )}

              {/* Empty state */}
              {(meeting.action_items?.length || 0) === 0 && (
                <Card>
                  <CardContent className="flex flex-col items-center justify-center py-12">
                    <CheckCircle2 className="h-12 w-12 text-muted-foreground mb-4" />
                    <p className="text-muted-foreground">No action items extracted</p>
                  </CardContent>
                </Card>
              )}
            </div>
          )}
        </>
      )}
    </div>
  )
}

function ActionItemCard({
  item,
  onConvert,
  onReject,
  isConverting,
  isRejecting,
}: {
  item: ActionItem
  onConvert: () => void
  onReject: () => void
  isConverting: boolean
  isRejecting: boolean
}) {
  return (
    <div className="flex items-start justify-between gap-4 p-4 border rounded-lg">
      <div className="flex-1 space-y-1">
        <p className="text-sm font-medium">{item.description}</p>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          {item.assignee_mentioned && (
            <Badge variant="outline" className="text-xs">
              Assignee: {item.assignee_mentioned}
            </Badge>
          )}
          {item.deadline_mentioned && (
            <Badge variant="outline" className="text-xs">
              Deadline: {item.deadline_mentioned}
            </Badge>
          )}
          <span>Confidence: {Math.round(item.confidence_score * 100)}%</span>
        </div>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <Button
          size="sm"
          onClick={onConvert}
          disabled={isConverting || isRejecting}
        >
          {isConverting ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <CheckCircle2 className="h-3 w-3 mr-1" />
          )}
          Convert
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={onReject}
          disabled={isConverting || isRejecting}
        >
          {isRejecting ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <XCircle className="h-3 w-3 mr-1" />
          )}
          Reject
        </Button>
      </div>
    </div>
  )
}
