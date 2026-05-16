'use client'

import { useState, useMemo, useEffect, useRef, useCallback } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { meetingApi, authApi } from '@/lib/api'
import { Meeting, ActionItem, DiarizedSegment, ContextType } from '@/types'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { formatDate, formatDateTime } from '@/lib/utils'
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
  Users,
  Pencil,
  Check,
  Download,
  Video,
} from 'lucide-react'

// ── Speaker color palette ─────────────────────────────────────
const SPEAKER_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  'Speaker A': { bg: 'bg-blue-50',   text: 'text-blue-800',   border: 'border-blue-200' },
  'Speaker B': { bg: 'bg-green-50',  text: 'text-green-800',  border: 'border-green-200' },
  'Speaker C': { bg: 'bg-orange-50', text: 'text-orange-800', border: 'border-orange-200' },
  'Speaker D': { bg: 'bg-purple-50', text: 'text-purple-800', border: 'border-purple-200' },
  'Speaker E': { bg: 'bg-pink-50',   text: 'text-pink-800',   border: 'border-pink-200' },
}

const DEFAULT_SPEAKER_COLOR = { bg: 'bg-gray-50', text: 'text-gray-800', border: 'border-gray-200' }

function getSpeakerColor(speaker: string) {
  return SPEAKER_COLORS[speaker] ?? DEFAULT_SPEAKER_COLOR
}

// ── Context type config ───────────────────────────────────────
const CONTEXT_CONFIG: Record<ContextType, { label: string; variant: 'default' | 'secondary' | 'destructive' | 'outline'; emoji: string }> = {
  task_assignment:  { label: 'Task Assignment',  variant: 'default',     emoji: '📋' },
  task_completion:  { label: 'Completed',        variant: 'default',     emoji: '✅' },
  warning:          { label: 'Warning',          variant: 'destructive', emoji: '⚠️' },
  progress_update:  { label: 'Progress Update',  variant: 'secondary',   emoji: '📊' },
  question:         { label: 'Question',         variant: 'outline',     emoji: '❓' },
  decision:         { label: 'Decision',         variant: 'secondary',   emoji: '🔑' },
  general:          { label: 'General',          variant: 'outline',     emoji: '💬' },
}

function ContextBadge({ type }: { type?: ContextType }) {
  if (!type || type === 'general') return null
  const cfg = CONTEXT_CONFIG[type]
  return (
    <Badge variant={cfg.variant} className="text-xs shrink-0">
      {cfg.emoji} {cfg.label}
    </Badge>
  )
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

const statusConfig: Record<string, { label: string; variant: 'default' | 'secondary' | 'destructive' | 'outline' }> = {
  awaiting_upload: { label: 'Waiting for Recording', variant: 'outline' },
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
  // Speaker name mapping: "Speaker A" → user-defined name
  const [speakerNames, setSpeakerNames] = useState<Record<string, string>>({})
  const [editingSpeaker, setEditingSpeaker] = useState<string | null>(null)
  const [editingValue, setEditingValue] = useState('')
  const editingValueRef = useRef('')
  // Transcript filter/search
  const [transcriptSearch, setTranscriptSearch] = useState('')
  const [activeSpeakerFilter, setActiveSpeakerFilter] = useState<string | null>(null)
  // Speaker name suggestions from team members
  const [nameSuggestions, setNameSuggestions] = useState<string[]>([])

  const { data: meeting, isLoading, error } = useQuery<Meeting>({
    queryKey: ['meeting', meetingId],
    queryFn: async () => {
      const { data } = await meetingApi.getMeeting(meetingId)
      return data
    },
    refetchInterval: (query) => {
      const m = query.state.data
      return m?.status === 'processing' || m?.status === 'awaiting_upload' ? 5000 : false
    },
  })

  const { data: teamMembers } = useQuery<{ id: string; full_name: string; email: string }[]>({
    queryKey: ['team-members'],
    queryFn: async () => {
      const { data } = await authApi.getTeamMembers()
      return data
    },
  })

  // Initialise speaker names from persisted data when meeting loads
  useEffect(() => {
    if (meeting?.speaker_names) {
      try {
        setSpeakerNames(JSON.parse(meeting.speaker_names))
      } catch {
        // ignore malformed JSON
      }
    }
  }, [meeting?.speaker_names])

  const convertMutation = useMutation({
    mutationFn: (actionItemId: string) =>
      meetingApi.convertActionItem(meetingId, actionItemId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['meeting', meetingId] })
    },
  })

  const rejectMutation = useMutation({
    mutationFn: (actionItemId: string) =>
      meetingApi.rejectActionItem(meetingId, actionItemId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['meeting', meetingId] })
    },
  })

  const retryMutation = useMutation({
    mutationFn: () => meetingApi.retryMeeting(meetingId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['meeting', meetingId] })
    },
  })

  const generateMeetLinkMutation = useMutation({
    mutationFn: () => meetingApi.generateMeetLink(meetingId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['meeting', meetingId] })
    },
  })

  // AWAITING_UPLOAD — attach a local recording file
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)

  const uploadToMeetingMutation = useMutation({
    mutationFn: (file: File) => {
      const fd = new FormData()
      fd.append('file', file)
      return meetingApi.uploadToMeeting(meetingId, fd)
    },
    onSuccess: () => {
      setUploadError(null)
      queryClient.invalidateQueries({ queryKey: ['meeting', meetingId] })
    },
    onError: (err: any) => {
      setUploadError(err.response?.data?.detail || 'Upload failed. Please try again.')
    },
  })

  const handleFileSelected = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) uploadToMeetingMutation.mutate(file)
    // reset so same file can be re-selected if needed
    e.target.value = ''
  }, [uploadToMeetingMutation])

  // Parse diarized segments from JSON string
  const diarizedSegments = useMemo<DiarizedSegment[]>(() => {
    if (!meeting?.diarized_transcript) return []
    try {
      return JSON.parse(meeting.diarized_transcript)
    } catch {
      return []
    }
  }, [meeting?.diarized_transcript])

  const uniqueSpeakers = useMemo(
    () => [...new Set(diarizedSegments.map((s) => s.speaker))],
    [diarizedSegments]
  )

  const filteredSegments = useMemo(() => {
    let segs = diarizedSegments
    if (activeSpeakerFilter) segs = segs.filter((s) => s.speaker === activeSpeakerFilter)
    if (transcriptSearch.trim()) {
      const q = transcriptSearch.toLowerCase()
      segs = segs.filter((s) => s.text.toLowerCase().includes(q))
    }
    return segs
  }, [diarizedSegments, activeSpeakerFilter, transcriptSearch])

  // Speaking time per speaker (seconds)
  const speakingTime = useMemo<Record<string, number>>(() => {
    return diarizedSegments.reduce((acc, seg) => {
      const dur = (seg.end ?? 0) - (seg.start ?? 0)
      acc[seg.speaker] = (acc[seg.speaker] ?? 0) + dur
      return acc
    }, {} as Record<string, number>)
  }, [diarizedSegments])

  const totalSpeakingTime = useMemo(
    () => Object.values(speakingTime).reduce((a, b) => a + b, 0),
    [speakingTime]
  )

  // Context type counts for stats panel
  const contextStats = useMemo<Partial<Record<ContextType, number>>>(() => {
    if (!diarizedSegments.length) return {}
    return diarizedSegments.reduce((acc, seg) => {
      if (seg.context_type && seg.context_type !== 'general') {
        acc[seg.context_type] = (acc[seg.context_type] ?? 0) + 1
      }
      return acc
    }, {} as Partial<Record<ContextType, number>>)
  }, [diarizedSegments])

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

  // Resolve display name: use custom name if set, else original label
  const getDisplayName = (speaker: string) => speakerNames[speaker] || speaker

  const startEditingSpeaker = (speaker: string) => {
    setEditingSpeaker(speaker)
    const current = speakerNames[speaker] || ''
    setEditingValue(current)
    editingValueRef.current = current
    // Suggest team member names not already assigned to another speaker
    const usedNames = new Set(Object.values(speakerNames))
    const suggestions = (teamMembers || [])
      .map((m) => m.full_name)
      .filter((n) => !usedNames.has(n) || n === current)
    setNameSuggestions(suggestions)
  }

  const commitSpeakerName = (speaker: string) => {
    const trimmed = editingValue.trim()
    const updated = { ...speakerNames, [speaker]: trimmed || speaker }
    setSpeakerNames(updated)
    setEditingSpeaker(null)
    meetingApi.updateSpeakerNames(meetingId, updated).catch(() => {
      // Silently swallow — the local state is still correct, and the
      // user can rename again if the network request failed.
    })
  }

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
            {meeting.google_meet_link ? (
              <a
                href={meeting.google_meet_link}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 rounded-md border border-green-300 bg-green-50 px-2.5 py-1 text-xs font-medium text-green-800 hover:bg-green-100 transition-colors dark:border-green-700 dark:bg-green-950 dark:text-green-300 dark:hover:bg-green-900"
              >
                <Video className="h-3 w-3" />
                Join with Google Meet
              </a>
            ) : (
              <button
                onClick={() => generateMeetLinkMutation.mutate()}
                disabled={generateMeetLinkMutation.isPending}
                className="inline-flex items-center gap-1.5 rounded-md border border-dashed border-green-400 bg-transparent px-2.5 py-1 text-xs font-medium text-green-700 hover:bg-green-50 transition-colors disabled:opacity-50 dark:border-green-600 dark:text-green-400"
              >
                {generateMeetLinkMutation.isPending ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <Video className="h-3 w-3" />
                )}
                {generateMeetLinkMutation.isPending ? 'Generating…' : 'Get Meet Link'}
              </button>
            )}
          </div>
        </div>
        <Badge variant={statusInfo.variant}>{statusInfo.label}</Badge>
      </div>

      {/* Awaiting upload banner */}
      {meeting.status === 'awaiting_upload' && (
        <Card className="border-yellow-300 bg-yellow-50 dark:border-yellow-700 dark:bg-yellow-950">
          <CardContent className="flex items-center justify-between gap-3 py-4">
            <div className="flex items-center gap-3">
              {uploadToMeetingMutation.isPending ? (
                <Loader2 className="h-5 w-5 animate-spin text-yellow-600 dark:text-yellow-400 shrink-0" />
              ) : (
                <AlertCircle className="h-5 w-5 text-yellow-600 dark:text-yellow-400 shrink-0" />
              )}
              <div>
                <p className="font-medium text-yellow-900 dark:text-yellow-200">
                  {uploadToMeetingMutation.isPending ? 'Uploading…' : 'Waiting for recording'}
                </p>
                <p className="text-sm text-yellow-700 dark:text-yellow-400">
                  {uploadToMeetingMutation.isPending
                    ? 'Uploading your recording. Transcription will start automatically.'
                    : 'Pick the local recording file to start transcription.'}
                </p>
                {uploadError && (
                  <p className="text-sm text-red-600 dark:text-red-400 mt-1">{uploadError}</p>
                )}
              </div>
            </div>
            <input
              ref={fileInputRef}
              type="file"
              accept=".mp3,.wav,.m4a,.webm,.mp4,.mpeg,.mpga"
              className="hidden"
              onChange={handleFileSelected}
            />
            <Button
              size="sm"
              className="shrink-0"
              disabled={uploadToMeetingMutation.isPending}
              onClick={() => fileInputRef.current?.click()}
            >
              {uploadToMeetingMutation.isPending ? (
                <><Loader2 className="h-4 w-4 animate-spin mr-1" /> Uploading…</>
              ) : (
                'Upload Recording'
              )}
            </Button>
          </CardContent>
        </Card>
      )}

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
      {(meeting.status === 'failed' || meeting.status === 'completed') && (
        <Card className={meeting.status === 'failed' ? 'border-red-200 bg-red-50' : 'border-muted'}>
          <CardContent className="flex items-center justify-between gap-3 py-4">
            <div className="flex items-center gap-3">
              {meeting.status === 'failed' ? (
                <>
                  <AlertCircle className="h-5 w-5 text-red-600" />
                  <div>
                    <p className="font-medium text-red-900">Transcription failed</p>
                    <p className="text-sm text-red-700">Something went wrong during processing.</p>
                  </div>
                </>
              ) : (
                <>
                  <RotateCcw className="h-5 w-5 text-muted-foreground" />
                  <div>
                    <p className="font-medium text-sm">Re-analyse with speaker identification</p>
                    <p className="text-xs text-muted-foreground">Reprocess to apply speaker diarization.</p>
                  </div>
                </>
              )}
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
              {meeting.status === 'failed' ? 'Retry' : 'Re-analyse'}
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
            <div className="space-y-4">
              {/* Meeting Stats Panel */}
              {(Object.keys(contextStats).length > 0 || uniqueSpeakers.length > 0) && (
                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="text-base flex items-center gap-2">
                      <Users className="h-4 w-4" />
                      Meeting Insights
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    {/* Speaker summary */}
                    {uniqueSpeakers.length > 0 && (
                      <div>
                        <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">
                          Participants ({uniqueSpeakers.length})
                        </p>
                        <div className="flex flex-wrap gap-2">
                          {uniqueSpeakers.map((spk) => {
                            const colors = getSpeakerColor(spk)
                            const count = diarizedSegments.filter((s) => s.speaker === spk).length
                            return (
                              <span
                                key={spk}
                                className={`inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium border ${colors.bg} ${colors.text} ${colors.border}`}
                              >
                                {getDisplayName(spk)}
                                <span className="opacity-60">· {count}</span>
                              </span>
                            )
                          })}
                        </div>
                      </div>
                    )}

                    {/* Speaking time bar chart */}
                    {totalSpeakingTime > 0 && (
                      <div>
                        <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">
                          Speaking Time
                        </p>
                        <div className="space-y-2">
                          {uniqueSpeakers
                            .sort((a, b) => (speakingTime[b] ?? 0) - (speakingTime[a] ?? 0))
                            .map((spk) => {
                              const colors = getSpeakerColor(spk)
                              const secs = speakingTime[spk] ?? 0
                              const pct = totalSpeakingTime > 0 ? (secs / totalSpeakingTime) * 100 : 0
                              const mins = Math.floor(secs / 60)
                              const s = Math.floor(secs % 60)
                              return (
                                <div key={spk} className="flex items-center gap-3">
                                  <span className={`text-xs font-medium w-20 shrink-0 ${colors.text}`}>
                                    {getDisplayName(spk)}
                                  </span>
                                  <div className="flex-1 h-5 bg-muted rounded-full overflow-hidden">
                                    <div
                                      className={`h-full rounded-full transition-all ${colors.bg} border ${colors.border}`}
                                      style={{ width: `${pct}%` }}
                                    />
                                  </div>
                                  <span className="text-xs text-muted-foreground w-16 text-right shrink-0">
                                    {mins > 0 ? `${mins}m ` : ''}{s}s ({Math.round(pct)}%)
                                  </span>
                                </div>
                              )
                            })}
                        </div>
                      </div>
                    )}

                    {/* Context type breakdown */}
                    {Object.keys(contextStats).length > 0 && (
                      <div>
                        <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">
                          Context Breakdown
                        </p>
                        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                          {(Object.entries(contextStats) as [ContextType, number][])
                            .sort(([, a], [, b]) => b - a)
                            .map(([type, count]) => {
                              const cfg = CONTEXT_CONFIG[type]
                              return (
                                <div
                                  key={type}
                                  className="flex items-center justify-between px-3 py-2 rounded-lg bg-muted/50 border"
                                >
                                  <span className="text-xs font-medium flex items-center gap-1">
                                    <span>{cfg.emoji}</span>
                                    <span>{cfg.label}</span>
                                  </span>
                                  <Badge variant="secondary" className="text-xs ml-2">
                                    {count}
                                  </Badge>
                                </div>
                              )
                            })}
                        </div>
                      </div>
                    )}
                  </CardContent>
                </Card>
              )}

              {/* AI Summary card */}
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
            </div>
          )}

          {/* Transcript Tab */}
          {activeTab === 'transcript' && (
            <Card>
              <CardHeader>
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <CardTitle className="flex items-center gap-2">
                      <Mic className="h-5 w-5" />
                      Transcript
                      {diarizedSegments.length > 0 && (
                        <Badge variant="secondary" className="ml-2 text-xs">
                          <Users className="h-3 w-3 mr-1" />
                          {uniqueSpeakers.length} speaker{uniqueSpeakers.length !== 1 ? 's' : ''}
                        </Badge>
                      )}
                    </CardTitle>
                    <CardDescription className="mt-1">
                      {diarizedSegments.length > 0
                        ? 'Speaker-labeled transcript with context classification'
                        : 'Full transcription of the meeting recording'}
                    </CardDescription>
                  </div>
                  <div className="flex gap-2 shrink-0">
                    <a
                      href={`/api/meetings/${meeting.id}/export?format=txt`}
                      download
                      className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded border hover:bg-muted transition-colors"
                    >
                      <Download className="h-3 w-3" />
                      Transcript
                    </a>
                    {meeting.summary && (
                      <a
                        href={`/api/meetings/${meeting.id}/export?format=summary`}
                        download
                        className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded border hover:bg-muted transition-colors"
                      >
                        <Download className="h-3 w-3" />
                        Summary
                      </a>
                    )}
                  </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                {/* Search + speaker filter */}
                <div className="flex flex-wrap gap-2 items-center pb-3 border-b">
                  <Input
                    placeholder="Search transcript..."
                    value={transcriptSearch}
                    onChange={(e) => setTranscriptSearch(e.target.value)}
                    className="h-8 text-sm w-48"
                  />
                  {uniqueSpeakers.map((spk) => {
                    const colors = getSpeakerColor(spk)
                    const active = activeSpeakerFilter === spk
                    return (
                      <button
                        key={spk}
                        onClick={() => setActiveSpeakerFilter(active ? null : spk)}
                        className={`px-2 py-1 rounded-full text-xs font-medium border transition-opacity ${colors.bg} ${colors.text} ${colors.border} ${active ? 'ring-2 ring-offset-1 ring-current' : 'opacity-70 hover:opacity-100'}`}
                      >
                        {getDisplayName(spk)}
                      </button>
                    )
                  })}
                  {(transcriptSearch || activeSpeakerFilter) && (
                    <button
                      onClick={() => { setTranscriptSearch(''); setActiveSpeakerFilter(null) }}
                      className="text-xs text-muted-foreground hover:text-foreground underline"
                    >
                      Clear
                    </button>
                  )}
                </div>

                {/* Speaker legend with rename UI */}
                {uniqueSpeakers.length > 0 && (
                  <div className="pb-3 border-b space-y-2">
                    <p className="text-xs text-muted-foreground">Click a speaker to rename</p>
                    <div className="flex flex-wrap gap-2">
                      {uniqueSpeakers.map((spk) => {
                        const colors = getSpeakerColor(spk)
                        const isEditing = editingSpeaker === spk
                        return isEditing ? (
                          <div key={spk} className="flex flex-col gap-1">
                            <form
                              className="flex items-center gap-1"
                              onSubmit={(e) => { e.preventDefault(); commitSpeakerName(spk) }}
                            >
                              <Input
                                autoFocus
                                value={editingValue}
                                onChange={(e) => { setEditingValue(e.target.value); editingValueRef.current = e.target.value }}
                                onBlur={() => setTimeout(() => {
                                  const trimmed = editingValueRef.current.trim()
                                  const updated = { ...speakerNames, [spk]: trimmed || spk }
                                  setSpeakerNames(updated)
                                  setEditingSpeaker(null)
                                  meetingApi.updateSpeakerNames(meetingId, updated).catch(() => {})
                                }, 150)}
                                placeholder={spk}
                                className="h-6 text-xs w-32 px-2"
                              />
                              <Button type="submit" size="icon" variant="ghost" className="h-6 w-6">
                                <Check className="h-3 w-3" />
                              </Button>
                            </form>
                            {nameSuggestions.length > 0 && (
                              <div className="flex flex-wrap gap-1">
                                {nameSuggestions.map((name) => (
                                  <button
                                    key={name}
                                    type="button"
                                    onMouseDown={(e) => { e.preventDefault(); setEditingValue(name); editingValueRef.current = name }}
                                    className="text-xs px-1.5 py-0.5 rounded bg-muted border hover:bg-accent transition-colors"
                                  >
                                    {name}
                                  </button>
                                ))}
                              </div>
                            )}
                          </div>
                        ) : (
                          <button
                            key={spk}
                            onClick={() => startEditingSpeaker(spk)}
                            className={`inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium border cursor-pointer hover:opacity-80 transition-opacity ${colors.bg} ${colors.text} ${colors.border}`}
                          >
                            {getDisplayName(spk)}
                            <Pencil className="h-2.5 w-2.5 opacity-50" />
                          </button>
                        )
                      })}
                    </div>
                  </div>
                )}

                {/* Diarized transcript */}
                {diarizedSegments.length > 0 ? (
                  <div className="space-y-2 max-h-[600px] overflow-y-auto">
                    {filteredSegments.length === 0 && (
                      <p className="text-sm text-muted-foreground italic text-center py-4">
                        No segments match your filter.
                      </p>
                    )}
                    {filteredSegments.map((seg, idx) => {
                      const colors = getSpeakerColor(seg.speaker)
                      return (
                        <div
                          key={idx}
                          className={`flex flex-col gap-2 p-3 rounded-lg border ${colors.bg} ${colors.border}`}
                        >
                          <div className="flex gap-3 items-start">
                            {/* Timestamp */}
                            <span className="text-xs text-muted-foreground font-mono shrink-0 w-12">
                              {formatTime(seg.start)}
                            </span>
                            {/* Speaker label */}
                            <span className={`text-xs font-semibold shrink-0 w-20 ${colors.text}`}>
                              {getDisplayName(seg.speaker)}
                            </span>
                          </div>
                          {/* Text + context badge */}
                          <div className="flex-1 space-y-1 pl-1">
                            <p className={`text-sm leading-relaxed ${colors.text}`}>{seg.text}</p>
                            {seg.context_type && seg.context_type !== 'general' && (
                              <ContextBadge type={seg.context_type} />
                            )}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                ) : meeting.transcript ? (
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
                        isConverting={convertMutation.isPending}
                        isRejecting={rejectMutation.isPending}
                      />
                    ))}
                  </CardContent>
                </Card>
              )}

              {/* Converted items */}
              {convertedItems.length > 0 && (
                <Card>
                  <CardHeader>
                    <CardTitle className="text-lg text-green-700">
                      Converted to Tasks ({convertedItems.length})
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-2">
                    {convertedItems.map((item) => (
                      <div
                        key={item.id}
                        className="flex items-center gap-3 p-3 bg-green-50 rounded-lg"
                      >
                        <CheckCircle2 className="h-4 w-4 text-green-600 shrink-0" />
                        <span className="text-sm text-green-900">{item.description}</span>
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
    <div className="flex items-start justify-between gap-4 p-4 border rounded-lg bg-card">
      <div className="flex-1 space-y-2">
        {/* Context type + description */}
        <div className="flex items-start gap-2 flex-wrap">
          <ContextBadge type={item.context_type} />
          <p className="text-sm font-medium text-foreground">{item.description}</p>
        </div>

        {/* Speaker attribution */}
        {(item.assigned_by || item.speaker_label) && (
          <div className="flex items-center gap-1 text-xs text-muted-foreground">
            {item.assigned_by && (
              <>
                <span className="font-medium">{item.assigned_by}</span>
                {item.assignee_mentioned && (
                  <>
                    <span>→</span>
                    <span className="font-medium">{item.assignee_mentioned}</span>
                  </>
                )}
              </>
            )}
            {!item.assigned_by && item.speaker_label && (
              <span>Said by: <span className="font-medium">{item.speaker_label}</span></span>
            )}
          </div>
        )}

        {/* Meta badges */}
        <div className="flex items-center gap-2 text-xs text-muted-foreground flex-wrap">
          {item.assignee_mentioned && !item.assigned_by && (
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
