'use client'

import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { taskApi, dmApi } from '@/lib/api'
import { useAuthStore } from '@/lib/stores/authStore'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Search,
  Filter,
  Pencil,
  Trash2,
  Bot,
  MessageSquare,
  Video,
  Copy,
  User,
  AlertTriangle,
  BarChart2,
  CheckCircle2,
  Clock,
  Loader2,
} from 'lucide-react'
import { format } from 'date-fns'
import { formatDueDate, getStatusColor, getPriorityColor, capitalize } from '@/lib/utils'
import type { Task } from '@/types'
import { CreateTaskDialog } from '@/components/create-task-dialog'
import { TaskCommentSection } from '@/components/TaskCommentSection'

// ── Source type badge ─────────────────────────────────────────────────────────

const SOURCE_CONFIG: Record<string, { label: string; color: string; Icon: any }> = {
  manual: { label: 'Manual', color: 'bg-gray-100 text-gray-700', Icon: User },
  meeting: { label: 'Meeting', color: 'bg-blue-100 text-blue-700', Icon: Video },
  message: { label: 'Message', color: 'bg-purple-100 text-purple-700', Icon: MessageSquare },
  ai: { label: 'AI', color: 'bg-emerald-100 text-emerald-700', Icon: Bot },
}

function SourceBadge({ type }: { type: string }) {
  const cfg = SOURCE_CONFIG[type] ?? SOURCE_CONFIG.manual
  const Icon = cfg.Icon
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${cfg.color}`}>
      <Icon className="h-3 w-3" />
      {cfg.label}
    </span>
  )
}

// ── Work Balance Panel (admin only) ──────────────────────────────────────────

interface WorkBalancePanelProps {
  tasks: Task[]
  members: { id: string; full_name: string; email: string }[]
  onFilterByMember: (id: string) => void
}

function WorkBalancePanel({ tasks, members, onFilterByMember }: WorkBalancePanelProps) {
  const now = new Date()

  // Build per-member stats from tasks that have an assignee
  const stats = useMemo(() => {
    const map: Record<string, { name: string; total: number; done: number; overdue: number; upcoming: number }> = {}
    for (const t of tasks) {
      if (!t.assignee_id) continue
      const name = t.assignee?.full_name ?? members.find((m) => m.id === t.assignee_id)?.full_name ?? 'Unknown'
      if (!map[t.assignee_id]) map[t.assignee_id] = { name, total: 0, done: 0, overdue: 0, upcoming: 0 }
      map[t.assignee_id].total++
      if (t.status === 'done') map[t.assignee_id].done++
      if (t.due_date && new Date(t.due_date) < now && t.status !== 'done') map[t.assignee_id].overdue++
      if (t.due_date && new Date(t.due_date) >= now && t.status !== 'done') map[t.assignee_id].upcoming++
    }
    return Object.entries(map)
      .map(([id, s]) => ({ id, ...s, active: s.total - s.done }))
      .sort((a, b) => b.active - a.active)
  }, [tasks, members])

  if (stats.length === 0) return null

  const maxActive = Math.max(...stats.map((s) => s.active), 1)

  return (
    <Card className="p-4 space-y-3">
      <div className="flex items-center gap-2">
        <BarChart2 className="h-4 w-4 text-muted-foreground" />
        <h2 className="text-sm font-semibold">Team Work Balance</h2>
        <span className="text-xs text-muted-foreground ml-auto">{tasks.length} tasks total</span>
      </div>
      <div className="space-y-2">
        {stats.map((s) => (
          <button
            key={s.id}
            className="w-full text-left group"
            onClick={() => onFilterByMember(s.id)}
            title={`Filter by ${s.name}`}
          >
            <div className="flex items-center justify-between mb-0.5">
              <span className="text-xs font-medium group-hover:text-primary transition-colors truncate max-w-[160px]">
                {s.name}
              </span>
              <div className="flex items-center gap-2 text-xs text-muted-foreground shrink-0 ml-2">
                {s.overdue > 0 && (
                  <span className="text-red-500 font-medium flex items-center gap-0.5">
                    <AlertTriangle className="h-3 w-3" />
                    {s.overdue} overdue
                  </span>
                )}
                <span>{s.active} active</span>
                <span className="text-green-600">{s.done} done</span>
              </div>
            </div>
            <div className="h-1.5 rounded-full bg-muted overflow-hidden">
              <div
                className={`h-full rounded-full transition-all ${s.overdue > 0 ? 'bg-red-400' : 'bg-primary'}`}
                style={{ width: `${(s.active / maxActive) * 100}%` }}
              />
            </div>
          </button>
        ))}
      </div>
    </Card>
  )
}

// ── Edit Task Dialog ──────────────────────────────────────────────────────────

interface EditTaskDialogProps {
  task: Task
  onClose: () => void
}

function EditTaskDialog({ task, onClose }: EditTaskDialogProps) {
  const queryClient = useQueryClient()
  const { user: currentUser } = useAuthStore()

  const [title, setTitle] = useState(task.title)
  const [description, setDescription] = useState(task.description ?? '')
  const [status, setStatus] = useState(task.status)
  const [priority, setPriority] = useState(task.priority)
  const [assigneeId, setAssigneeId] = useState(task.assignee_id ?? '')
  const [dueDate, setDueDate] = useState(
    task.due_date ? new Date(task.due_date).toISOString().split('T')[0] : ''
  )
  const [estimatedHours, setEstimatedHours] = useState(
    task.estimated_hours != null ? String(task.estimated_hours) : ''
  )
  const [isMeetingTask, setIsMeetingTask] = useState(task.is_meeting_task ?? false)
  const [meetingScheduledAt, setMeetingScheduledAt] = useState(
    task.meeting_scheduled_at
      ? new Date(task.meeting_scheduled_at).toISOString().slice(0, 16)
      : ''
  )
  const [meetingDuration, setMeetingDuration] = useState(
    String(task.meeting_duration_minutes ?? 60)
  )
  const [error, setError] = useState('')

  const { data: teamMembers = [] } = useQuery<{ id: string; full_name: string; email: string }[]>({
    queryKey: ['dm-users-for-tasks'],
    queryFn: async () => (await dmApi.getUsers()).data,
    staleTime: 60_000,
  })

  const assigneeOptions = currentUser
    ? [{ id: currentUser.id, full_name: `${currentUser.full_name} (you)`, email: currentUser.email }, ...teamMembers]
    : teamMembers

  const updateMutation = useMutation({
    mutationFn: (data: any) => taskApi.updateTask(task.id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
      queryClient.invalidateQueries({ queryKey: ['task-stats'] })
      queryClient.invalidateQueries({ queryKey: ['recent-tasks'] })
      onClose()
    },
    onError: (err: any) => {
      setError(err.response?.data?.detail || 'Failed to update task')
    },
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!title.trim()) {
      setError('Title is required')
      return
    }
    setError('')

    const data: any = {
      title: title.trim(),
      description: description.trim() || null,
      status,
      priority,
      assignee_id: assigneeId || null,
      estimated_hours: estimatedHours ? parseInt(estimatedHours) : null,
      is_meeting_task: isMeetingTask,
      meeting_duration_minutes: parseInt(meetingDuration) || 60,
      meeting_scheduled_at: isMeetingTask && meetingScheduledAt
        ? new Date(meetingScheduledAt).toISOString()
        : null,
    }

    if (dueDate) {
      data.due_date = new Date(dueDate).toISOString()
    } else {
      data.due_date = null
    }

    updateMutation.mutate(data)
  }

  return (
    <Dialog open onOpenChange={(v) => { if (!v) onClose() }}>
      <DialogContent className="sm:max-w-[540px] max-h-[90vh] flex flex-col">
        <form onSubmit={handleSubmit} className="flex flex-col min-h-0 flex-1">
          <DialogHeader className="shrink-0">
            <DialogTitle>Edit Task</DialogTitle>
          </DialogHeader>

          <div className="grid gap-4 py-4 overflow-y-auto flex-1 pr-1">
            {error && (
              <div className="rounded-md bg-red-50 dark:bg-red-950 p-3 text-sm text-red-600 dark:text-red-400">
                {error}
              </div>
            )}

            {/* Title */}
            <div className="space-y-2">
              <Label htmlFor="edit-title">Title *</Label>
              <Input
                id="edit-title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                autoFocus
              />
            </div>

            {/* Description */}
            <div className="space-y-2">
              <Label htmlFor="edit-desc">Description</Label>
              <Textarea
                id="edit-desc"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={3}
              />
            </div>

            {/* Status + Priority */}
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="edit-status">Status</Label>
                <select
                  id="edit-status"
                  value={status}
                  onChange={(e) => setStatus(e.target.value as Task['status'])}
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <option value="todo">To Do</option>
                  <option value="in_progress">In Progress</option>
                  <option value="done">Done</option>
                  <option value="blocked">Blocked</option>
                </select>
              </div>

              <div className="space-y-2">
                <Label htmlFor="edit-priority">Priority</Label>
                <select
                  id="edit-priority"
                  value={priority}
                  onChange={(e) => setPriority(e.target.value as Task['priority'])}
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
              <Label htmlFor="edit-assignee">Assign To</Label>
              <select
                id="edit-assignee"
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
                <Label htmlFor="edit-due">Due Date</Label>
                <Input
                  id="edit-due"
                  type="date"
                  value={dueDate}
                  onChange={(e) => setDueDate(e.target.value)}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="edit-hours">Estimated Hours</Label>
                <Input
                  id="edit-hours"
                  type="number"
                  min="0"
                  placeholder="e.g. 4"
                  value={estimatedHours}
                  onChange={(e) => setEstimatedHours(e.target.value)}
                />
              </div>
            </div>

            {/* Meeting toggle */}
            <div className="flex items-center gap-3">
              <input
                id="edit-is-meeting"
                type="checkbox"
                checked={isMeetingTask}
                onChange={(e) => setIsMeetingTask(e.target.checked)}
                className="h-4 w-4 rounded border-input"
              />
              <Label htmlFor="edit-is-meeting" className="cursor-pointer flex items-center gap-1.5">
                <Video className="h-3.5 w-3.5 text-muted-foreground" />
                Schedule as meeting
              </Label>
            </div>

            {/* Existing Meet link (read-only info) */}
            {task.google_meet_link && (
              <div className="flex items-center gap-2 rounded-lg border border-green-200 dark:border-green-800 bg-green-50 dark:bg-green-950 px-3 py-2 text-sm">
                <Video className="h-4 w-4 text-green-600 dark:text-green-400 shrink-0" />
                <span className="text-green-700 dark:text-green-300 font-medium truncate flex-1">
                  Meet link active
                </span>
                <a
                  href={task.google_meet_link}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs text-green-600 dark:text-green-400 hover:underline shrink-0"
                >
                  Open
                </a>
                <button
                  type="button"
                  title="Copy Meet link"
                  className="text-green-600 dark:text-green-400 hover:text-green-800 dark:hover:text-green-200 shrink-0"
                  onClick={() => navigator.clipboard.writeText(task.google_meet_link!)}
                >
                  <Copy className="h-3.5 w-3.5" />
                </button>
              </div>
            )}

            {/* Meeting date + duration fields */}
            {isMeetingTask && (
              <div className="grid gap-4 sm:grid-cols-2 rounded-lg border border-blue-200 dark:border-blue-800 bg-blue-50/50 dark:bg-blue-950/30 p-3">
                <div className="space-y-2">
                  <Label htmlFor="edit-meeting-at">Meeting Date &amp; Time</Label>
                  <Input
                    id="edit-meeting-at"
                    type="datetime-local"
                    value={meetingScheduledAt}
                    onChange={(e) => setMeetingScheduledAt(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="edit-meeting-dur">Duration</Label>
                  <select
                    id="edit-meeting-dur"
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

            {/* Comments */}
            <div className="border-t pt-4">
              <TaskCommentSection
                taskId={task.id}
                currentUserId={currentUser?.id ?? ''}
              />
            </div>
          </div>

          <DialogFooter className="shrink-0 pt-2">
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={updateMutation.isPending}>
              {updateMutation.isPending ? 'Saving...' : 'Save Changes'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function TasksPage() {
  const queryClient = useQueryClient()
  const { user: currentUser } = useAuthStore()
  const isAdmin = currentUser?.role === 'admin'

  const [searchTerm, setSearchTerm] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [priorityFilter, setPriorityFilter] = useState<string>('all')
  const [assigneeFilter, setAssigneeFilter] = useState<string>('all')
  const [editingTask, setEditingTask] = useState<Task | null>(null)

  // Team members for assignee filter (admins only)
  const { data: teamMembers = [] } = useQuery<{ id: string; full_name: string; email: string }[]>({
    queryKey: ['dm-users-for-tasks'],
    queryFn: async () => (await dmApi.getUsers()).data,
    staleTime: 60_000,
    enabled: isAdmin,
  })

  const queryKey = ['tasks', statusFilter, priorityFilter, assigneeFilter]

  // Fetch tasks — admins see all, non-admins only see their own
  const { data, isLoading } = useQuery<{ data: Task[] }>({
    queryKey,
    queryFn: () => {
      const params: any = { limit: 200 }
      if (statusFilter !== 'all') params.status = statusFilter
      if (priorityFilter !== 'all') params.priority = priorityFilter
      if (assigneeFilter !== 'all') params.assignee_id = assigneeFilter
      // Non-admins always filter to their own tasks
      if (!isAdmin && currentUser) params.assignee_id = currentUser.id
      return taskApi.getTasks(params)
    },
  })

  // Delete mutation — optimistic: remove immediately, rollback on error
  const deleteMutation = useMutation({
    mutationFn: (id: string) => taskApi.deleteTask(id),
    onMutate: async (id) => {
      await queryClient.cancelQueries({ queryKey })
      const previous = queryClient.getQueryData<{ data: Task[] }>(queryKey)
      queryClient.setQueryData<{ data: Task[] }>(queryKey, (old) =>
        old ? { ...old, data: old.data.filter((t) => t.id !== id) } : old
      )
      return { previous }
    },
    onError: (_err, _id, context: any) => {
      if (context?.previous) queryClient.setQueryData(queryKey, context.previous)
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
      queryClient.invalidateQueries({ queryKey: ['task-stats'] })
    },
  })

  // Generate Meet link for a task
  const generateMeetMutation = useMutation({
    mutationFn: (taskId: string) => taskApi.generateMeetLink(taskId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
    },
  })

  // Quick status update (cycle through all 4 statuses)
  const updateStatusMutation = useMutation({
    mutationFn: ({ id, status, priority }: { id: string; status?: string; priority?: string }) =>
      taskApi.updateTask(id, { ...(status !== undefined && { status }), ...(priority !== undefined && { priority }) }),
    onMutate: async ({ id, status, priority }) => {
      await queryClient.cancelQueries({ queryKey })
      const previous = queryClient.getQueryData<{ data: Task[] }>(queryKey)
      queryClient.setQueryData<{ data: Task[] }>(queryKey, (old) =>
        old
          ? {
              ...old,
              data: old.data.map((t) =>
                t.id === id
                  ? { ...t, ...(status !== undefined && { status: status as Task['status'] }), ...(priority !== undefined && { priority: priority as Task['priority'] }) }
                  : t
              ),
            }
          : old
      )
      return { previous }
    },
    onError: (_err, _vars, context: any) => {
      if (context?.previous) queryClient.setQueryData(queryKey, context.previous)
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
      queryClient.invalidateQueries({ queryKey: ['task-stats'] })
    },
  })

  const tasks = data?.data || []

  // Filter by search term (title + description + assignee name)
  const filteredTasks = tasks.filter(
    (task) =>
      task.title.toLowerCase().includes(searchTerm.toLowerCase()) ||
      (task.description ?? '').toLowerCase().includes(searchTerm.toLowerCase()) ||
      (task.assignee?.full_name ?? '').toLowerCase().includes(searchTerm.toLowerCase())
  )

  const now = new Date()
  const overdueTasks = filteredTasks.filter(
    (t) => t.due_date && new Date(t.due_date) < now && t.status !== 'done'
  )

  // Cycle status: todo → in_progress → done → todo
  const cycleStatus = (task: Task) => {
    const cycle: Record<string, string> = {
      todo: 'in_progress',
      in_progress: 'done',
      done: 'todo',
      blocked: 'todo',
    }
    updateStatusMutation.mutate({ id: task.id, status: cycle[task.status] ?? 'todo' })
  }

  const STATUS_ICON: Record<string, string> = {
    todo: '○',
    in_progress: '◑',
    done: '●',
    blocked: '✕',
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <h1 className="text-xl sm:text-2xl font-bold">Tasks</h1>
          <p className="text-sm text-muted-foreground">
            {isAdmin ? "Manage and track your team's tasks" : 'Your assigned tasks'}
          </p>
        </div>
        {isAdmin && (
          <div className="shrink-0">
            <CreateTaskDialog />
          </div>
        )}
      </div>

      {/* Admin: work balance panel */}
      {isAdmin && tasks.length > 0 && (
        <WorkBalancePanel
          tasks={tasks}
          members={teamMembers}
          onFilterByMember={(id) => setAssigneeFilter(id)}
        />
      )}

      {/* Overdue alert */}
      {overdueTasks.length > 0 && (
        <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 dark:bg-red-950 dark:border-red-800 px-4 py-2 text-sm text-red-700 dark:text-red-400">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span>
            <span className="font-semibold">{overdueTasks.length}</span> overdue task{overdueTasks.length !== 1 ? 's' : ''} — check deadlines below
          </span>
        </div>
      )}

      {/* Filters */}
      <Card className="p-3 sm:p-4">
        <div className="grid gap-3 grid-cols-1 sm:grid-cols-2 lg:grid-cols-5">
          <div className="relative lg:col-span-2">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder="Search tasks or assignee..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="pl-9"
            />
          </div>

          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
          >
            <option value="all">All Status</option>
            <option value="todo">To Do</option>
            <option value="in_progress">In Progress</option>
            <option value="done">Done</option>
            <option value="blocked">Blocked</option>
          </select>

          <select
            value={priorityFilter}
            onChange={(e) => setPriorityFilter(e.target.value)}
            className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
          >
            <option value="all">All Priority</option>
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
            <option value="urgent">Urgent</option>
          </select>

          {isAdmin ? (
            <select
              value={assigneeFilter}
              onChange={(e) => setAssigneeFilter(e.target.value)}
              className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
            >
              <option value="all">All Members</option>
              <option value="unassigned">Unassigned</option>
              {teamMembers.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.full_name}
                </option>
              ))}
            </select>
          ) : (
            <div className="flex items-center text-sm text-muted-foreground">
              <Filter className="h-4 w-4 mr-2" />
              {filteredTasks.length} task{filteredTasks.length !== 1 ? 's' : ''}
            </div>
          )}
        </div>

        {isAdmin && (
          <div className="flex items-center justify-between mt-2 pt-2 border-t text-xs text-muted-foreground">
            <span className="flex items-center gap-1">
              <Filter className="h-3 w-3" />
              {filteredTasks.length} task{filteredTasks.length !== 1 ? 's' : ''}
              {assigneeFilter !== 'all' && assigneeFilter !== 'unassigned' && (
                <span className="text-primary font-medium">
                  — {teamMembers.find((m) => m.id === assigneeFilter)?.full_name}
                </span>
              )}
            </span>
            {assigneeFilter !== 'all' && (
              <button
                onClick={() => setAssigneeFilter('all')}
                className="text-muted-foreground hover:text-foreground underline"
              >
                Clear filter
              </button>
            )}
          </div>
        )}
      </Card>

      {/* Tasks list */}
      {isLoading ? (
        <div className="text-center py-12 text-muted-foreground">Loading tasks...</div>
      ) : filteredTasks.length === 0 ? (
        <Card className="p-12 text-center">
          <p className="text-muted-foreground mb-4">No tasks found</p>
          {isAdmin && <CreateTaskDialog />}
        </Card>
      ) : (
        <div className="overflow-y-auto max-h-[calc(100vh-380px)] pr-1 space-y-2 scrollbar-thin">
          {filteredTasks.map((task) => {
            const isOverdue = task.due_date && new Date(task.due_date) < now && task.status !== 'done'
            return (
              <Card
                key={task.id}
                className={`p-3 sm:p-4 hover:shadow-md transition-shadow ${isOverdue ? 'border-red-200 dark:border-red-800' : ''}`}
              >
                <div className="flex items-start gap-2 sm:gap-3">
                  {/* Status cycle button */}
                  <button
                    className={`mt-0.5 text-lg leading-none shrink-0 w-5 text-center transition-colors ${
                      task.status === 'done'
                        ? 'text-green-500'
                        : task.status === 'in_progress'
                        ? 'text-blue-500'
                        : task.status === 'blocked'
                        ? 'text-red-500'
                        : 'text-gray-400'
                    }`}
                    title={`Status: ${task.status} — click to advance`}
                    onClick={() => cycleStatus(task)}
                    disabled={updateStatusMutation.isPending}
                  >
                    {STATUS_ICON[task.status] ?? '○'}
                  </button>

                  {/* Task content */}
                  <div className="flex-1 min-w-0">
                    {/* Title row */}
                    <div className="flex flex-wrap items-start gap-x-2 gap-y-1 mb-1">
                      <h3
                        className={`font-medium leading-snug flex-1 min-w-0 break-words ${
                          task.status === 'done' ? 'line-through text-muted-foreground' : ''
                        }`}
                      >
                        {task.title}
                      </h3>
                      <div className="flex items-center gap-1 flex-shrink-0">
                        <Badge className={`${getStatusColor(task.status)} text-xs px-1.5 py-0`}>
                          {capitalize(task.status.replace('_', ' '))}
                        </Badge>
                        <Badge className={`${getPriorityColor(task.priority)} text-xs px-1.5 py-0`}>
                          {capitalize(task.priority)}
                        </Badge>
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-7 w-7 p-0"
                          title="Edit task"
                          onClick={() => setEditingTask(task)}
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </Button>
                        {isAdmin && (
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 w-7 p-0 text-red-500 hover:text-red-700 hover:bg-red-50"
                            title="Delete task"
                            onClick={() => {
                              if (confirm('Delete this task?')) deleteMutation.mutate(task.id)
                            }}
                            disabled={deleteMutation.isPending}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        )}
                      </div>
                    </div>

                    {task.description && (
                      <p className="text-sm text-muted-foreground mb-2 line-clamp-2">
                        {task.description}
                      </p>
                    )}

                    {/* Assignee chip — prominent for admins */}
                    {task.assignee && (
                      <div className="mb-2">
                        <span className="inline-flex items-center gap-1.5 rounded-full bg-indigo-50 dark:bg-indigo-950 border border-indigo-200 dark:border-indigo-800 px-2.5 py-0.5 text-xs font-medium text-indigo-700 dark:text-indigo-300">
                          <User className="h-3 w-3" />
                          {task.assignee.full_name}
                        </span>
                      </div>
                    )}
                    {!task.assignee && isAdmin && (
                      <div className="mb-2">
                        <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-50 dark:bg-amber-950 border border-amber-200 dark:border-amber-800 px-2.5 py-0.5 text-xs font-medium text-amber-700 dark:text-amber-300">
                          <User className="h-3 w-3" />
                          Unassigned
                        </span>
                      </div>
                    )}

                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                      <SourceBadge type={task.source_type} />
                      {task.meeting_scheduled_at ? (
                        <span className="flex items-center gap-1 text-blue-600 dark:text-blue-400 font-medium">
                          <Video className="h-3 w-3" />
                          {format(new Date(task.meeting_scheduled_at), 'MMM d, h:mm a')}
                          {task.meeting_duration_minutes ? ` · ${task.meeting_duration_minutes} min` : ''}
                        </span>
                      ) : task.is_meeting_task && task.due_date ? (
                        <span className="flex items-center gap-1 text-blue-600 dark:text-blue-400 font-medium">
                          <Video className="h-3 w-3" />
                          {format(new Date(task.due_date), 'MMM d')}
                          {task.meeting_duration_minutes ? ` · ${task.meeting_duration_minutes} min` : ''}
                        </span>
                      ) : task.due_date ? (
                        <span className={`flex items-center gap-1 ${isOverdue ? 'text-red-500 font-semibold' : ''}`}>
                          {isOverdue ? (
                            <AlertTriangle className="h-3 w-3" />
                          ) : (
                            <Clock className="h-3 w-3" />
                          )}
                          {isOverdue ? 'Overdue: ' : 'Due '}
                          {formatDueDate(task.due_date)}
                        </span>
                      ) : null}
                      {task.estimated_hours != null && (
                        <span>{task.estimated_hours}h est.</span>
                      )}
                      {task.external_id && (
                        <span className="text-blue-500 truncate max-w-[100px]">Jira: {task.external_id}</span>
                      )}
                      {task.jira_synced_at && (
                        <span
                          className="text-xs text-muted-foreground"
                          title={`Synced from Jira: ${task.jira_synced_at}`}
                        >
                          ↻ {format(new Date(task.jira_synced_at), 'MMM d, HH:mm')}
                        </span>
                      )}
                    </div>

                    {/* Google Meet section */}
                    {task.google_meet_link ? (
                      <div className="flex items-center gap-2 mt-2">
                        <a
                          href={task.google_meet_link}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1.5 rounded-full bg-green-100 dark:bg-green-950 border border-green-300 dark:border-green-700 px-3 py-1 text-xs font-semibold text-green-700 dark:text-green-300 hover:bg-green-200 dark:hover:bg-green-900 transition-colors"
                        >
                          <Video className="h-3.5 w-3.5" />
                          Join Meeting
                        </a>
                        <button
                          title="Copy Meet link"
                          className="text-muted-foreground hover:text-foreground transition-colors"
                          onClick={() => navigator.clipboard.writeText(task.google_meet_link!)}
                        >
                          <Copy className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    ) : task.is_meeting_task ? (
                      <div className="mt-2">
                        <Button
                          size="sm"
                          variant="outline"
                          className="h-7 text-xs gap-1.5"
                          disabled={generateMeetMutation.isPending}
                          onClick={() => generateMeetMutation.mutate(task.id)}
                        >
                          {generateMeetMutation.isPending ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          ) : (
                            <Video className="h-3.5 w-3.5" />
                          )}
                          Generate Meet Link
                        </Button>
                      </div>
                    ) : null}
                  </div>
                </div>
              </Card>
            )
          })}
        </div>
      )}

      {/* Edit dialog */}
      {editingTask && (
        <EditTaskDialog task={editingTask} onClose={() => setEditingTask(null)} />
      )}
    </div>
  )
}
