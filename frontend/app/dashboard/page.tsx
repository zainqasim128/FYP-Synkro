'use client'

import { useQuery } from '@tanstack/react-query'
import { taskApi, meetingApi, adminApi } from '@/lib/api'
import { useAuthStore } from '@/lib/stores/authStore'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { CheckSquare, Clock, AlertCircle, TrendingUp, Video, MessageSquare, Users, Shield } from 'lucide-react'
import Link from 'next/link'
import { formatRelativeTime, getStatusColor, getPriorityColor } from '@/lib/utils'
import type { TaskStats, Task, Meeting, AdminUserStats } from '@/types'
import { CreateTaskDialog } from '@/components/create-task-dialog'

export default function DashboardPage() {
  const { user } = useAuthStore()
  const isAdmin = user?.role === 'admin'

  // Fetch task statistics
  const { data: stats } = useQuery<{ data: TaskStats }>({
    queryKey: ['task-stats'],
    queryFn: () => taskApi.getStats(),
  })

  // Fetch recent tasks
  const { data: tasksResponse } = useQuery<{ data: Task[] }>({
    queryKey: ['recent-tasks'],
    queryFn: () => taskApi.getTasks({ limit: 5 }),
  })

  // Fetch recent meetings
  const { data: meetingsResponse } = useQuery<{ data: Meeting[] }>({
    queryKey: ['recent-meetings'],
    queryFn: () => meetingApi.getMeetings({ limit: 3 }),
  })

  // Admin only: fetch user count
  const { data: userCountData } = useQuery<{ data: AdminUserStats }>({
    queryKey: ['admin-user-count'],
    queryFn: () => adminApi.getUserCount(),
    enabled: isAdmin,
  })

  const taskStats = stats?.data
  const recentTasks = tasksResponse?.data || []
  const recentMeetings = meetingsResponse?.data || []
  const userStats = userCountData?.data

  return (
    <div className="space-y-6">
      {/* Admin Banner */}
      {isAdmin && (
        <div className="flex items-center gap-3 rounded-lg border border-amber-200 bg-amber-50 dark:bg-amber-950 dark:border-amber-800 px-4 py-3">
          <Shield className="h-5 w-5 text-amber-600 dark:text-amber-400 shrink-0" />
          <div>
            <p className="text-sm font-medium text-amber-800 dark:text-amber-300">
              Admin Dashboard
            </p>
            <p className="text-xs text-amber-600 dark:text-amber-400">
              You have full system access. You can upload meetings and manage users.
            </p>
          </div>
        </div>
      )}

      {/* Stats Grid */}
      <div className="grid gap-3 sm:gap-4 grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Active Tasks</CardTitle>
            <CheckSquare className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{taskStats?.total || 0}</div>
            <p className="text-xs text-muted-foreground">
              {taskStats?.todo || 0} to do, {taskStats?.in_progress || 0} in progress
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">In Progress</CardTitle>
            <Clock className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{taskStats?.in_progress || 0}</div>
            <p className="text-xs text-muted-foreground">
              Currently being worked on
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Overdue</CardTitle>
            <AlertCircle className="h-4 w-4 text-red-500" />
          </CardHeader>
          <CardContent>
            <div className={`text-2xl font-bold ${taskStats?.overdue ? 'text-red-500' : ''}`}>
              {taskStats?.overdue || 0}
            </div>
            <p className="text-xs text-muted-foreground">
              Need immediate attention
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Completion Rate</CardTitle>
            <TrendingUp className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {taskStats?.completion_rate?.toFixed(0) || 0}%
            </div>
            <p className="text-xs text-muted-foreground">
              {taskStats?.done || 0} completed tasks
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Admin-only: User Statistics */}
      {isAdmin && userStats && (
        <div className="grid gap-3 sm:gap-4 grid-cols-2 lg:grid-cols-4">
          <Card className="border-amber-200 dark:border-amber-800">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Total Users</CardTitle>
              <Users className="h-4 w-4 text-amber-600" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{userStats.total}</div>
              <p className="text-xs text-muted-foreground">
                {userStats.active} active, {userStats.inactive} inactive
              </p>
            </CardContent>
          </Card>

          <Card className="border-amber-200 dark:border-amber-800">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">New This Month</CardTitle>
              <Users className="h-4 w-4 text-amber-600" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{userStats.new_last_30_days}</div>
              <p className="text-xs text-muted-foreground">
                Users joined last 30 days
              </p>
            </CardContent>
          </Card>

          <Card className="border-amber-200 dark:border-amber-800 md:col-span-2">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Users by Role</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex flex-wrap gap-2">
                {Object.entries(userStats.by_role || {}).map(([role, count]) => (
                  count > 0 && (
                    <div key={role} className="flex items-center gap-1.5">
                      <Badge variant="outline" className="capitalize">
                        {role.replace(/_/g, ' ')}
                      </Badge>
                      <span className="text-sm font-medium">{String(count)}</span>
                    </div>
                  )
                ))}
              </div>
              <Link
                href="/dashboard/settings"
                className="text-xs text-primary hover:underline mt-2 inline-block"
              >
                Manage Users →
              </Link>
            </CardContent>
          </Card>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Recent Tasks */}
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle>Recent Tasks</CardTitle>
              <Link
                href="/dashboard/tasks"
                className="text-sm font-medium text-primary hover:underline"
              >
                View All
              </Link>
            </div>
          </CardHeader>
          <CardContent>
            {recentTasks.length === 0 ? (
              <p className="text-sm text-muted-foreground">No tasks yet. Create your first task!</p>
            ) : (
              <div className="space-y-4">
                {recentTasks.map((task) => (
                  <Link
                    key={task.id}
                    href={`/dashboard/tasks`}
                    className="block rounded-lg border p-3 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex-1 min-w-0">
                        <p className="font-medium text-sm truncate">{task.title}</p>
                        {task.assignee && (
                          <p className="text-xs text-muted-foreground mt-1">
                            Assigned to {task.assignee.full_name}
                          </p>
                        )}
                      </div>
                      <div className="flex flex-col gap-1 items-end">
                        <Badge className={getStatusColor(task.status)}>
                          {task.status.replace('_', ' ')}
                        </Badge>
                        <Badge className={getPriorityColor(task.priority)}>
                          {task.priority}
                        </Badge>
                      </div>
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Recent Meetings */}
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle>Recent Meetings</CardTitle>
              <Link
                href="/dashboard/meetings"
                className="text-sm font-medium text-primary hover:underline"
              >
                View All
              </Link>
            </div>
          </CardHeader>
          <CardContent>
            {recentMeetings.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                {isAdmin
                  ? 'No meetings yet. Upload your first recording!'
                  : 'No meetings uploaded by admin yet.'}
              </p>
            ) : (
              <div className="space-y-4">
                {recentMeetings.map((meeting) => (
                  <Link
                    key={meeting.id}
                    href={`/dashboard/meetings/${meeting.id}`}
                    className="block rounded-lg border p-3 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
                  >
                    <div className="flex items-start gap-3">
                      <Video className="h-5 w-5 text-muted-foreground mt-0.5" />
                      <div className="flex-1 min-w-0">
                        <p className="font-medium text-sm truncate">{meeting.title}</p>
                        <p className="text-xs text-muted-foreground mt-1">
                          {formatRelativeTime(meeting.created_at)}
                        </p>
                      </div>
                      <Badge className={getStatusColor(meeting.status)}>
                        {meeting.status}
                      </Badge>
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Quick Actions */}
      <Card>
        <CardHeader>
          <CardTitle>Quick Actions</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <CreateTaskDialog
              trigger={
                <button className="flex items-center gap-3 rounded-lg border p-4 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors text-left w-full">
                  <CheckSquare className="h-8 w-8 text-primary" />
                  <div>
                    <p className="font-medium">Create Task</p>
                    <p className="text-xs text-muted-foreground">Add a new task manually</p>
                  </div>
                </button>
              }
            />

            {/* Upload Meeting - Admin only */}
            {isAdmin && (
              <Link
                href="/dashboard/meetings"
                className="flex items-center gap-3 rounded-lg border p-4 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
              >
                <Video className="h-8 w-8 text-primary" />
                <div>
                  <p className="font-medium">Upload Meeting</p>
                  <p className="text-xs text-muted-foreground">Transcribe and summarize</p>
                </div>
              </Link>
            )}

            <Link
              href="/dashboard/chat"
              className="flex items-center gap-3 rounded-lg border p-4 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
            >
              <MessageSquare className="h-8 w-8 text-primary" />
              <div>
                <p className="font-medium">Ask AI</p>
                <p className="text-xs text-muted-foreground">Query your workspace</p>
              </div>
            </Link>

            {/* Manage Users - Admin only */}
            {isAdmin && (
              <Link
                href="/dashboard/settings"
                className="flex items-center gap-3 rounded-lg border border-amber-200 bg-amber-50 dark:bg-amber-950 dark:border-amber-800 p-4 hover:bg-amber-100 dark:hover:bg-amber-900 transition-colors"
              >
                <Users className="h-8 w-8 text-amber-600 dark:text-amber-400" />
                <div>
                  <p className="font-medium">Manage Users</p>
                  <p className="text-xs text-muted-foreground">View and manage team members</p>
                </div>
              </Link>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
