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
import { Plus } from 'lucide-react'

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
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!title.trim()) {
      setError('Title is required')
      return
    }
    setError('')

    const data: any = {
      title: title.trim(),
      description: description.trim() || undefined,
      status,
      priority,
      source_type: 'manual',
    }

    if (assigneeId) data.assignee_id = assigneeId
    if (dueDate) data.due_date = new Date(dueDate).toISOString()
    if (estimatedHours) data.estimated_hours = parseInt(estimatedHours)

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
                onChange={(e) => setTitle(e.target.value)}
                autoFocus
              />
            </div>

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
              {createMutation.isPending ? 'Creating...' : 'Create Task'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
