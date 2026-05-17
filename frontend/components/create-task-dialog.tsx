'use client'

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { taskApi, dmApi } from '@/lib/api'
import { useAuthStore } from '@/lib/stores/authStore'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Plus, Video } from 'lucide-react'

interface CreateTaskDialogProps {
  trigger?: React.ReactNode
}

interface TeamMember {
  id: string
  full_name: string
  email: string
}

export function CreateTaskDialog({ trigger }: CreateTaskDialogProps) {
  const queryClient = useQueryClient()
  const { user: currentUser } = useAuthStore()
  const [open, setOpen] = useState(false)
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [status, setStatus] = useState('todo')
  const [priority, setPriority] = useState('medium')
  const [assigneeId, setAssigneeId] = useState('')
  const [dueDate, setDueDate] = useState('')
  const [estimatedHours, setEstimatedHours] = useState('')
  const [error, setError] = useState('')
  const [isMeetingTask, setIsMeetingTask] = useState(false)
  const [meetingBannerDismissed, setMeetingBannerDismissed] = useState(false)
  const [meetingScheduledAt, setMeetingScheduledAt] = useState('')
  const [meetingDuration, setMeetingDuration] = useState('60')

  const MEETING_KEYWORDS = ['meeting', 'standup', 'stand-up', 'sync', 'call', 'review', 'demo', 'presentation', 'interview', 'conference', 'session', 'discussion', '1:1', 'one-on-one']
  const titleLooksLikeMeeting = MEETING_KEYWORDS.some((kw) => title.toLowerCase().includes(kw))

  // Fetch team members for the assignee picker (only when dialog is open)
  const { data: teamMembers = [] } = useQuery<TeamMember[]>({
    queryKey: ['dm-users-for-tasks'],
    queryFn: async () => (await dmApi.getUsers()).data,
    enabled: open,
    staleTime: 60_000,
  })

  // Combine current user + team members so you can assign to yourself too
  const assigneeOptions: TeamMember[] = currentUser
    ? [{ id: currentUser.id, full_name: `${currentUser.full_name} (you)`, email: currentUser.email }, ...teamMembers]
    : teamMembers

  const createMutation = useMutation({
    mutationFn: (data: any) => taskApi.createTask(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
      queryClient.invalidateQueries({ queryKey: ['task-stats'] })
      queryClient.invalidateQueries({ queryKey: ['recent-tasks'] })
      resetForm()
      setOpen(false)
    },
    onError: (err: any) => {
      setError(err.response?.data?.detail || 'Failed to create task')
    },
  })

  const resetForm = () => {
    setTitle('')
    setDescription('')
    setStatus('todo')
    setPriority('medium')
    setAssigneeId('')
    setDueDate('')
    setEstimatedHours('')
    setError('')
    setIsMeetingTask(false)
    setMeetingBannerDismissed(false)
    setMeetingScheduledAt('')
    setMeetingDuration('60')
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!title.trim()) {
      setError('Title is required')
      return
    }
    setError('')

    const effectiveMeetingTask = isMeetingTask || (titleLooksLikeMeeting && !meetingBannerDismissed)

    const data: any = {
      title: title.trim(),
      description: description.trim() || undefined,
      status,
      priority,
      source_type: 'manual',
      is_meeting_task: effectiveMeetingTask,
      meeting_duration_minutes: parseInt(meetingDuration) || 60,
    }

    if (assigneeId) data.assignee_id = assigneeId
    if (dueDate) data.due_date = new Date(dueDate).toISOString()
    if (estimatedHours) data.estimated_hours = parseInt(estimatedHours)
    if (meetingScheduledAt) data.meeting_scheduled_at = new Date(meetingScheduledAt).toISOString()

    createMutation.mutate(data)
  }

  return (
    <Dialog open={open} onOpenChange={(v) => { setOpen(v); if (!v) resetForm() }}>
      <DialogTrigger asChild>
        {trigger || (
          <Button>
            <Plus className="h-4 w-4 mr-2" />
            New Task
          </Button>
        )}
      </DialogTrigger>
      <DialogContent className="sm:max-w-[540px] max-h-[90vh] flex flex-col">
        <form onSubmit={handleSubmit} className="flex flex-col min-h-0 flex-1">
          <DialogHeader className="shrink-0">
            <DialogTitle>Create New Task</DialogTitle>
            <DialogDescription>Add a new task to your team's workspace.</DialogDescription>
          </DialogHeader>

          <div className="grid gap-4 py-4 overflow-y-auto flex-1 pr-1">
            {error && (
              <div className="rounded-md bg-red-50 dark:bg-red-950 p-3 text-sm text-red-600 dark:text-red-400">
                {error}
              </div>
            )}

            {/* Title */}
            <div className="space-y-2">
              <Label htmlFor="title">Title *</Label>
              <Input
                id="title"
                placeholder="Enter task title..."
                value={title}
                onChange={(e) => { setTitle(e.target.value); setMeetingBannerDismissed(false) }}
                autoFocus
              />
            </div>

            {/* Meeting auto-detect banner */}
            {titleLooksLikeMeeting && !meetingBannerDismissed && !isMeetingTask && (
              <div className="flex items-start gap-3 rounded-lg border border-blue-200 bg-blue-50 dark:bg-blue-950 dark:border-blue-800 px-4 py-3 text-sm">
                <Video className="h-4 w-4 text-blue-600 dark:text-blue-400 mt-0.5 shrink-0" />
                <div className="flex-1">
                  <p className="text-blue-700 dark:text-blue-300 font-medium">
                    This looks like a meeting — generate a Google Meet link?
                  </p>
                </div>
                <div className="flex gap-2 shrink-0">
                  <button
                    type="button"
                    className="text-xs font-semibold text-blue-700 dark:text-blue-300 hover:underline"
                    onClick={() => setIsMeetingTask(true)}
                  >
                    Yes
                  </button>
                  <button
                    type="button"
                    className="text-xs font-semibold text-muted-foreground hover:underline"
                    onClick={() => setMeetingBannerDismissed(true)}
                  >
                    No
                  </button>
                </div>
              </div>
            )}

            {/* Explicit meeting toggle */}
            <div className="flex items-center gap-3">
              <input
                id="is-meeting-task"
                type="checkbox"
                checked={isMeetingTask}
                onChange={(e) => setIsMeetingTask(e.target.checked)}
                className="h-4 w-4 rounded border-input"
              />
              <Label htmlFor="is-meeting-task" className="cursor-pointer flex items-center gap-1.5">
                <Video className="h-3.5 w-3.5 text-muted-foreground" />
                Schedule as meeting (auto-generate Google Meet link)
              </Label>
            </div>

            {/* Meeting fields — revealed when meeting mode is on */}
            {isMeetingTask && (
              <div className="grid gap-4 sm:grid-cols-2 rounded-lg border border-blue-200 dark:border-blue-800 bg-blue-50/50 dark:bg-blue-950/30 p-3">
                <div className="space-y-2">
                  <Label htmlFor="meeting-scheduled-at">Meeting Date &amp; Time</Label>
                  <Input
                    id="meeting-scheduled-at"
                    type="datetime-local"
                    value={meetingScheduledAt}
                    onChange={(e) => setMeetingScheduledAt(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="meeting-duration">Duration</Label>
                  <select
                    id="meeting-duration"
                    value={meetingDuration}
                    onChange={(e) => setMeetingDuration(e.target.value)}
                    className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <option value="15">15 min</option>
                    <option value="30">30 min</option>
                    <option value="45">45 min</option>
                    <option value="60">60 min</option>
                    <option value="90">90 min</option>
                    <option value="120">120 min</option>
                  </select>
                </div>
              </div>
            )}

            {/* Description */}
            <div className="space-y-2">
              <Label htmlFor="description">Description</Label>
              <Textarea
                id="description"
                placeholder="Describe the task..."
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={3}
              />
            </div>

            {/* Status + Priority */}
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="status">Status</Label>
                <select
                  id="status"
                  value={status}
                  onChange={(e) => setStatus(e.target.value)}
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <option value="todo">To Do</option>
                  <option value="in_progress">In Progress</option>
                  <option value="blocked">Blocked</option>
                </select>
              </div>

              <div className="space-y-2">
                <Label htmlFor="priority">Priority</Label>
                <select
                  id="priority"
                  value={priority}
                  onChange={(e) => setPriority(e.target.value)}
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <option value="low">Low</option>
                  <option value="medium">Medium</option>
                  <option value="high">High</option>
                  <option value="urgent">Urgent</option>
                </select>
              </div>
            </div>

            {/* Assignee */}
            <div className="space-y-2">
              <Label htmlFor="assignee">Assign To</Label>
              <select
                id="assignee"
                value={assigneeId}
                onChange={(e) => setAssigneeId(e.target.value)}
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <option value="">Unassigned</option>
                {assigneeOptions.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.full_name}
                  </option>
                ))}
              </select>
            </div>

            {/* Due date + Estimated hours */}
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="due_date">Due Date</Label>
                <Input
                  id="due_date"
                  type="date"
                  value={dueDate}
                  onChange={(e) => setDueDate(e.target.value)}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="estimated_hours">Estimated Hours</Label>
                <Input
                  id="estimated_hours"
                  type="number"
                  min="0"
                  placeholder="e.g. 4"
                  value={estimatedHours}
                  onChange={(e) => setEstimatedHours(e.target.value)}
                />
              </div>
            </div>
          </div>

          <DialogFooter className="shrink-0 pt-2">
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={createMutation.isPending}>
              {createMutation.isPending
                ? (isMeetingTask ? 'Generating Meet link...' : 'Creating...')
                : 'Create Task'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
