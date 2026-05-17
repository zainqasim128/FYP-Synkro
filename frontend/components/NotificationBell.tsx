'use client'

import { useEffect, useRef, useState } from 'react'
import { Bell, Check } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { notificationsApi } from '@/lib/api'
import { Notification } from '@/types'
import { cn } from '@/lib/utils'

export default function NotificationBell() {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const router = useRouter()
  const queryClient = useQueryClient()

  const { data } = useQuery({
    queryKey: ['notifications'],
    queryFn: async () =>
      (await notificationsApi.list()).data as { notifications: Notification[]; unread_count: number },
    refetchInterval: 30_000,
  })

  const notifications = data?.notifications ?? []
  const unread = data?.unread_count ?? 0

  useEffect(() => {
    function onMouseDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onMouseDown)
    return () => document.removeEventListener('mousedown', onMouseDown)
  }, [])

  const markRead = async (n: Notification) => {
    await notificationsApi.markRead(n.id)
    queryClient.invalidateQueries({ queryKey: ['notifications'] })
    setOpen(false)
    if (n.link) router.push(n.link)
  }

  const markAllRead = async () => {
    await notificationsApi.markAllRead()
    queryClient.invalidateQueries({ queryKey: ['notifications'] })
  }

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((prev) => !prev)}
        aria-label="Notifications"
        className="relative p-2 rounded-lg text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
      >
        <Bell className="h-5 w-5" />
        {unread > 0 && (
          <span className="absolute top-0.5 right-0.5 flex h-4 min-w-[1rem] items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-bold text-white leading-none">
            {unread > 99 ? '99+' : unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-11 z-50 w-80 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 shadow-xl">
          {/* Header */}
          <div className="flex items-center justify-between border-b border-gray-200 dark:border-gray-700 px-4 py-3">
            <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">
              Notifications
              {unread > 0 && (
                <span className="ml-2 rounded-full bg-red-100 dark:bg-red-900/30 px-1.5 py-0.5 text-xs font-bold text-red-600 dark:text-red-400">
                  {unread}
                </span>
              )}
            </span>
            {unread > 0 && (
              <button
                onClick={markAllRead}
                className="flex items-center gap-1 text-xs text-primary hover:underline"
              >
                <Check className="h-3 w-3" />
                Mark all read
              </button>
            )}
          </div>

          {/* List */}
          <div className="max-h-96 overflow-y-auto divide-y divide-gray-100 dark:divide-gray-700">
            {notifications.length === 0 ? (
              <p className="px-4 py-10 text-center text-sm text-gray-400 dark:text-gray-500">
                No notifications
              </p>
            ) : (
              notifications.map((n) => (
                <button
                  key={n.id}
                  onClick={() => markRead(n)}
                  className={cn(
                    'w-full text-left px-4 py-3 hover:bg-gray-50 dark:hover:bg-gray-700/60 transition-colors',
                    !n.is_read && 'bg-blue-50 dark:bg-blue-900/20',
                  )}
                >
                  <div className="flex items-start gap-2.5">
                    {!n.is_read ? (
                      <span className="mt-1.5 h-2 w-2 flex-shrink-0 rounded-full bg-blue-500" />
                    ) : (
                      <span className="mt-1.5 h-2 w-2 flex-shrink-0" />
                    )}
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-gray-900 dark:text-gray-100 leading-snug">
                        {n.title}
                      </p>
                      {n.body && (
                        <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400 line-clamp-2">
                          {n.body}
                        </p>
                      )}
                      <p className="mt-1 text-xs text-gray-400 dark:text-gray-500">
                        {new Date(n.created_at).toLocaleString()}
                      </p>
                    </div>
                  </div>
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  )
}
