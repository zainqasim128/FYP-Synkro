'use client'

import { useEffect, useState } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import Link from 'next/link'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuthStore } from '@/lib/stores/authStore'
import { useThemeStore } from '@/lib/stores/themeStore'
import {
  LayoutDashboard,
  CheckSquare,
  Video,
  Mail,
  MessageSquare,
  BarChart3,
  Settings,
  LogOut,
  Menu,
  X,
  Moon,
  Sun,
  Shield,
  AtSign,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn, getInitials, getAvatarColor } from '@/lib/utils'
import { ROLE_LABELS } from '@/types'
import { dmApi } from '@/lib/api'

const navigation = [
  { name: 'Dashboard', href: '/dashboard', icon: LayoutDashboard },
  { name: 'Tasks', href: '/dashboard/tasks', icon: CheckSquare },
  { name: 'Meetings', href: '/dashboard/meetings', icon: Video },
  { name: 'Emails', href: '/dashboard/emails', icon: Mail },
  { name: 'Slack', href: '/dashboard/slack', icon: MessageSquare },
  { name: 'Direct Messages', href: '/dashboard/messages', icon: AtSign },
  { name: 'Chat', href: '/dashboard/chat', icon: MessageSquare },
  { name: 'Analytics', href: '/dashboard/analytics', icon: BarChart3 },
  { name: 'Settings', href: '/dashboard/settings', icon: Settings },
]

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const router = useRouter()
  const pathname = usePathname()
  const { user, isAuthenticated, isLoading, logout, fetchUser } = useAuthStore()
  const { theme, toggleTheme } = useThemeStore()
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const queryClient = useQueryClient()

  const { data: unreadData } = useQuery({
    queryKey: ['dm-unread-count', user?.id],
    queryFn: async () => (await dmApi.getUnreadCount()).data as { unread: number },
    refetchInterval: 10000,
    enabled: isAuthenticated && !!user?.id,
  })

  useEffect(() => {
    // Wait for auth initialization to complete before redirecting
    if (isLoading) return

    if (!isAuthenticated) {
      router.push('/login')
      return
    }

    if (!user) {
      fetchUser().catch(() => {
        router.push('/login')
      })
    }
  }, [isAuthenticated, isLoading, user, router, fetchUser])

  const handleLogout = () => {
    logout()
    // Wipe entire React Query cache so the next user never sees this user's data
    queryClient.clear()
    router.push('/login')
  }

  if (isLoading || !user) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="text-center">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent mx-auto mb-3" />
          <p className="text-gray-500 text-sm">Loading...</p>
        </div>
      </div>
    )
  }

  const isAdmin = user.role === 'admin'
  const roleLabel = ROLE_LABELS[user.role] || user.role

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 overflow-x-hidden">
      {/* Mobile sidebar backdrop */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-40 bg-gray-600 bg-opacity-75 lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-50 w-64 transform bg-white dark:bg-gray-800 border-r border-gray-200 dark:border-gray-700 transition-transform duration-300 ease-in-out lg:translate-x-0',
          sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        )}
      >
        <div className="flex h-full flex-col">
          {/* Logo */}
          <div className="flex h-16 items-center justify-between px-6 border-b border-gray-200 dark:border-gray-700">
            <h1 className="text-2xl font-bold text-primary">Synkro</h1>
            <button
              onClick={() => setSidebarOpen(false)}
              className="lg:hidden"
            >
              <X className="h-6 w-6" />
            </button>
          </div>

          {/* Navigation */}
          <nav className="flex-1 overflow-y-auto space-y-1 px-3 py-4">
            {navigation.map((item) => {
              const isActive = pathname === item.href
              const unread = item.href === '/dashboard/messages' ? (unreadData?.unread ?? 0) : 0
              return (
                <Link
                  key={item.name}
                  href={item.href}
                  className={cn(
                    'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                    isActive
                      ? 'bg-primary text-white'
                      : 'text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700'
                  )}
                  onClick={() => setSidebarOpen(false)}
                >
                  <item.icon className="h-5 w-5" />
                  <span className="flex-1">{item.name}</span>
                  {unread > 0 && (
                    <span className="ml-auto flex h-5 min-w-5 items-center justify-center rounded-full bg-red-500 px-1.5 text-xs font-bold text-white">
                      {unread > 99 ? '99+' : unread}
                    </span>
                  )}
                </Link>
              )
            })}
          </nav>

          {/* User section */}
          <div className="border-t border-gray-200 dark:border-gray-700 p-4">
            <div className="flex items-center gap-3 mb-3">
              <div className={cn(
                'flex h-10 w-10 items-center justify-center rounded-full text-white font-semibold',
                getAvatarColor(user.full_name)
              )}>
                {getInitials(user.full_name)}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">
                  {user.full_name}
                </p>
                <p className="text-xs text-gray-500 dark:text-gray-400 truncate">
                  {user.email}
                </p>
              </div>
            </div>

            {/* Role badge */}
            <div className="mb-3 flex items-center gap-1.5">
              {isAdmin && <Shield className="h-3 w-3 text-amber-500" />}
              <span className={cn(
                'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium capitalize',
                isAdmin
                  ? 'bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-300'
                  : 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300'
              )}>
                {roleLabel}
              </span>
            </div>

            <Button
              variant="outline"
              size="sm"
              className="w-full"
              onClick={handleLogout}
            >
              <LogOut className="h-4 w-4 mr-2" />
              Logout
            </Button>
          </div>
        </div>
      </aside>

      {/* Main content */}
      <div className="lg:pl-64 min-w-0">
        {/* Top bar */}
        <header className="sticky top-0 z-30 flex h-16 items-center gap-4 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-4 sm:px-6">
          <button
            onClick={() => setSidebarOpen(true)}
            className="lg:hidden"
          >
            <Menu className="h-6 w-6" />
          </button>
          <div className="flex-1">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
              {navigation.find(item => item.href === pathname || (item.href !== '/dashboard' && pathname.startsWith(item.href)))?.name || 'Dashboard'}
            </h2>
          </div>
          {isAdmin && (
            <div className="hidden sm:flex items-center gap-1.5 rounded-full bg-amber-100 dark:bg-amber-900 px-3 py-1">
              <Shield className="h-3.5 w-3.5 text-amber-600 dark:text-amber-400" />
              <span className="text-xs font-medium text-amber-700 dark:text-amber-300">Admin</span>
            </div>
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={toggleTheme}
            className="mr-2"
          >
            {theme === 'dark' ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
          </Button>
        </header>

        {/* Page content */}
        <main className="p-4 sm:p-6 lg:p-8 min-w-0 overflow-x-hidden">
          {children}
        </main>
      </div>
    </div>
  )
}
