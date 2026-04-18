'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { taskApi, dmApi } from '@/lib/api'
import { useAuthStore } from '@/lib/stores/authStore'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Search, Filter, Pencil, Trash2, Bot, MessageSquare, Video, User } from 'lucide-react'
import { formatDueDate, getStatusColor, getPriorityColor, capitalize } from '@/lib/utils'
import type { Task } from '@/types'
import { CreateTaskDialog } from '@/components/create-task-dialog'

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
      <DialogContent className="sm:max-w-[540px]">
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle>Edit Task</DialogTitle>
          </DialogHeader>

          <div className="grid gap-4 py-4">
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
                  onChange={(e) => setStatus(e.target.value)}
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
          </div>

          <DialogFooter>
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
  const [searchTerm, setSearchTerm] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [priorityFilter, setPriorityFilter] = useState<string>('all')
  const [editingTask, setEditingTask] = useState<Task | null>(null)

  // Fetch tasks
  const { data, isLoading } = useQuery<{ data: Task[] }>({
    queryKey: ['tasks', statusFilter, priorityFilter],
    queryFn: () => {
      const params: any = { limit: 100 }
      if (statusFilter !== 'all') params.status = statusFilter
      if (priorityFilter !== 'all') params.priority = priorityFilter
      return taskApi.getTasks(params)
    },
  })

  // Delete mutation
  const deleteMutation = useMutation({
    mutationFn: (id: string) => taskApi.deleteTask(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
      queryClient.invalidateQueries({ queryKey: ['task-stats'] })
    },
  })

  // Quick status update (cycle through all 4 statuses)
  const updateStatusMutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      taskApi.updateTask(id, { status }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
      queryClient.invalidateQueries({ queryKey: ['task-stats'] })
    },
  })

  const tasks = data?.data || []

  // Filter by search term (title + description)
  const filteredTasks = tasks.filter(
    (task) =>
      task.title.toLowerCase().includes(searchTerm.toLowerCase()) ||
      (task.description ?? '').toLowerCase().includes(searchTerm.toLowerCase())
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
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <h1 className="text-xl sm:text-2xl font-bold">Tasks</h1>
          <p className="text-sm text-muted-foreground">Manage and track your team's tasks</p>
        </div>
        <div className="shrink-0">
          <CreateTaskDialog />
        </div>
      </div>

      {/* Filters */}
      <Card className="p-3 sm:p-4">
        <div className="grid gap-3 grid-cols-1 sm:grid-cols-2 lg:grid-cols-4">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder="Search tasks..."
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

          <div className="flex items-center text-sm text-muted-foreground">
            <Filter className="h-4 w-4 mr-2" />
            {filteredTasks.length} task{filteredTasks.length !== 1 ? 's' : ''}
          </div>
        </div>
      </Card>

      {/* Tasks list */}
      {isLoading ? (
        <div className="text-center py-12 text-muted-foreground">Loading tasks...</div>
      ) : filteredTasks.length === 0 ? (
        <Card className="p-12 text-center">
          <p className="text-muted-foreground mb-4">No tasks found</p>
          <CreateTaskDialog />
        </Card>
      ) : (
        <div className="overflow-y-auto max-h-[calc(100vh-280px)] pr-1 space-y-2 scrollbar-thin">
          {filteredTasks.map((task) => (
            <Card key={task.id} className="p-3 sm:p-4 hover:shadow-md transition-shadow">
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
                  {/* Title row: title + badges + actions on one line (wraps on xs) */}
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
                      {/* Actions inline on mobile too */}
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-7 w-7 p-0"
                        title="Edit task"
                        onClick={() => setEditingTask(task)}
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
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
                    </div>
                  </div>

                  {task.description && (
                    <p className="text-sm text-muted-foreground mb-2 line-clamp-2">
                      {task.description}
                    </p>
                  )}

                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                    <SourceBadge type={task.source_type} />
                    {task.assignee && (
                      <span className="flex items-center gap-1">
                        <User className="h-3 w-3" />
                        <span className="truncate max-w-[120px]">{task.assignee.full_name}</span>
                      </span>
                    )}
                    {task.due_date && (
                      <span className={
                        new Date(task.due_date) < new Date() && task.status !== 'done'
                          ? 'text-red-500 font-medium'
                          : ''
                      }>
                        Due {formatDueDate(task.due_date)}
                      </span>
                    )}
                    {task.estimated_hours != null && (
                      <span>{task.estimated_hours}h est.</span>
                    )}
                    {task.external_id && (
                      <span className="text-blue-500 truncate max-w-[100px]">Jira: {task.external_id}</span>
                    )}
                  </div>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      {/* Edit dialog */}
      {editingTask && (
        <EditTaskDialog task={editingTask} onClose={() => setEditingTask(null)} />
      )}
    </div>
  )
}
