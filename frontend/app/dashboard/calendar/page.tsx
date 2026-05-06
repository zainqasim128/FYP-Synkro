'use client'

import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import Link from 'next/link'
import { calendarApi, integrationsApi, taskApi } from '@/lib/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { ChevronLeft, ChevronRight, CalendarDays, ExternalLink, Loader2, RefreshCw } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { Integration, Task } from '@/types'

// ── Types ──────────────────────────────────────────────────────────────────────

interface GCalEvent {
  id: string
  summary?: string
  description?: string
  start: { date?: string; dateTime?: string }
  end: { date?: string; dateTime?: string }
}

interface CalendarItem {
  id: string
  title: string
  kind: EventKind
  date: string        // "YYYY-MM-DD"
  time?: string       // "HH:MM" local, undefined = all-day
  description?: string
}

type EventKind = 'task' | 'meeting' | 'action' | 'digest'

// ── Helpers ────────────────────────────────────────────────────────────────────

const DOW_LABELS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
const MONTH_NAMES = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]

function classifyGCalEvent(summary: string = ''): EventKind {
  if (summary.startsWith('[TASK]') || summary.startsWith('[DONE]') || summary.startsWith('[BLOCKED]')) return 'task'
  if (summary.startsWith('[MEETING]')) return 'meeting'
  if (summary.startsWith('[ACTION]')) return 'action'
  return 'digest'
}

const KIND_STYLES: Record<EventKind, string> = {
  task:    'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
  meeting: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
  action:  'bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200',
  digest:  'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200',
}

const KIND_DOT: Record<EventKind, string> = {
  task:    'bg-blue-500',
  meeting: 'bg-green-500',
  action:  'bg-orange-500',
  digest:  'bg-purple-500',
}

function stripPrefix(summary: string = ''): string {
  return summary
    .replace(/^\[(TASK|DONE|BLOCKED|MEETING|ACTION)\]\s*/, '')
    .trim()
}

function fmt12(h: number, m: number): string {
  const ampm = h >= 12 ? 'PM' : 'AM'
  return `${h % 12 || 12}:${String(m).padStart(2, '0')} ${ampm}`
}

function taskToItem(t: Task): CalendarItem | null {
  if (!t.due_date) return null
  // Parse as local time: backend strips timezone (stores naive datetime),
  // so treat the string as local rather than UTC to avoid off-by-one-day issues.
  const raw = t.due_date as string
  // "2026-04-27T14:00:00" or "2026-04-27T00:00:00" — no Z suffix from backend
  const localStr = raw.endsWith('Z') ? raw.slice(0, -1) : raw
  const d = new Date(localStr)
  const date = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  const hasTime = d.getHours() !== 0 || d.getMinutes() !== 0
  return {
    id: `task-${t.id}`,
    title: t.title,
    kind: 'task',
    date,
    time: hasTime ? fmt12(d.getHours(), d.getMinutes()) : undefined,
    description: t.description ?? undefined,
  }
}

function gcalToItem(ev: GCalEvent): CalendarItem {
  const raw = ev.start.date ?? ev.start.dateTime ?? ''
  const date = raw.slice(0, 10)
  let time: string | undefined
  if (ev.start.dateTime) {
    // Extract HH:MM directly from the ISO string (e.g. "2026-05-02T13:00:00+05:00")
    // to avoid new Date() converting to browser timezone and showing the wrong hour
    const m = ev.start.dateTime.match(/T(\d{2}):(\d{2})/)
    if (m) time = fmt12(parseInt(m[1], 10), parseInt(m[2], 10))
  }
  const kind = classifyGCalEvent(ev.summary)
  return {
    id: `gcal-${ev.id}`,
    title: stripPrefix(ev.summary) || '(no title)',
    kind,
    date,
    time,
    description: ev.description?.split('\n')[0],
  }
}

// ── Legend chip ────────────────────────────────────────────────────────────────

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
      <span className={cn('h-2.5 w-2.5 rounded-full', color)} />
      {label}
    </span>
  )
}

// ── Day cell ───────────────────────────────────────────────────────────────────

function DayCell({
  day,
  isToday,
  isCurrentMonth,
  items,
  onDayClick,
  selected,
}: {
  day: Date
  isToday: boolean
  isCurrentMonth: boolean
  items: CalendarItem[]
  onDayClick: (d: Date) => void
  selected: boolean
}) {
  const MAX_VISIBLE = 3
  const sorted = [...items].sort((a, b) => (a.time ?? '').localeCompare(b.time ?? ''))
  const visible = sorted.slice(0, MAX_VISIBLE)
  const overflow = sorted.length - MAX_VISIBLE

  return (
    <div
      className={cn(
        'min-h-[90px] p-1.5 cursor-pointer border-b border-r border-gray-200 dark:border-gray-700 transition-colors',
        isCurrentMonth ? 'bg-white dark:bg-gray-800' : 'bg-gray-50 dark:bg-gray-850 opacity-50',
        selected && 'ring-2 ring-inset ring-primary',
        'hover:bg-blue-50 dark:hover:bg-gray-700'
      )}
      onClick={() => onDayClick(day)}
    >
      <span
        className={cn(
          'inline-flex h-6 w-6 items-center justify-center rounded-full text-sm font-medium',
          isToday
            ? 'bg-primary text-white'
            : isCurrentMonth
            ? 'text-gray-900 dark:text-gray-100'
            : 'text-gray-400 dark:text-gray-600'
        )}
      >
        {day.getDate()}
      </span>

      <div className="mt-1 space-y-0.5">
        {visible.map((item) => (
          <div
            key={item.id}
            title={item.title}
            className={cn(
              'truncate rounded px-1 py-0.5 text-[10px] leading-tight font-medium',
              KIND_STYLES[item.kind]
            )}
          >
            {item.time && <span className="opacity-70 mr-0.5">{item.time}</span>}
            {item.title}
          </div>
        ))}
        {overflow > 0 && (
          <div className="text-[10px] text-muted-foreground pl-1">+{overflow} more</div>
        )}
      </div>
    </div>
  )
}

// ── Event list for selected day ────────────────────────────────────────────────

function DayEventList({ items }: { items: CalendarItem[] }) {
  if (items.length === 0) {
    return (
      <p className="text-sm text-muted-foreground py-2">No events on this day.</p>
    )
  }
  const sorted = [...items].sort((a, b) => (a.time ?? '').localeCompare(b.time ?? ''))
  return (
    <div className="space-y-2">
      {sorted.map((item) => (
        <div key={item.id} className={cn('rounded-lg px-3 py-2 text-sm', KIND_STYLES[item.kind])}>
          <div className="flex items-start justify-between gap-2">
            <span className="font-medium leading-snug">{item.title}</span>
            <span className="shrink-0 text-xs opacity-75">{item.time ?? 'All day'}</span>
          </div>
          {item.description && (
            <p className="mt-0.5 text-xs opacity-70 line-clamp-2">{item.description}</p>
          )}
        </div>
      ))}
    </div>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function CalendarPage() {
  const today = new Date()
  const [year, setYear] = useState(today.getFullYear())
  const [month, setMonth] = useState(today.getMonth()) // 0-indexed
  const [selectedDay, setSelectedDay] = useState<Date | null>(today)
  const [syncMessage, setSyncMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
  const queryClient = useQueryClient()

  // Date range for the current month view (include surrounding partial weeks)
  const rangeStart = useMemo(() => {
    const d = new Date(year, month, 1)
    d.setDate(d.getDate() - d.getDay()) // back to Sunday
    return d
  }, [year, month])

  const rangeEnd = useMemo(() => {
    const d = new Date(year, month + 1, 0)
    d.setDate(d.getDate() + (6 - d.getDay())) // forward to Saturday
    const end = new Date(d)
    end.setDate(end.getDate() + 1) // exclusive
    return end
  }, [year, month])

  const startISO = rangeStart.toISOString()
  const endISO = rangeEnd.toISOString()

  // Check if GCal is connected
  const { data: integrations = [] } = useQuery<Integration[]>({
    queryKey: ['integrations'],
    queryFn: async () => {
      const { data } = await integrationsApi.getIntegrations()
      return data
    },
    staleTime: 30_000,
  })

  const gcalConnected = integrations.some(
    (i) => i.platform === 'google_calendar' && i.is_active
  )

  const syncMutation = useMutation({
    mutationFn: () => calendarApi.syncAllTasks(),
    onSuccess: (res: any) => {
      const msg = res?.data?.message || 'Tasks synced to Google Calendar!'
      setSyncMessage({ type: 'success', text: msg })
      queryClient.invalidateQueries({ queryKey: ['calendar-gcal-events'] })
      setTimeout(() => setSyncMessage(null), 5000)
    },
    onError: (err: any) => {
      const detail = err?.response?.data?.detail
      const status = err?.response?.status
      const text = detail
        ? `Sync failed (${status}): ${detail}`
        : `Sync failed. Check the backend logs for details.`
      setSyncMessage({ type: 'error', text })
      setTimeout(() => setSyncMessage(null), 10000)
    },
  })

  // Always fetch tasks directly — no Celery required
  const { data: tasksData, isLoading: tasksLoading, isError: tasksError } = useQuery<{ data: Task[] }>({
    queryKey: ['tasks', 'all'],
    queryFn: () => taskApi.getTasks({ limit: 100 }),
    staleTime: 0,   // always fresh — so new tasks appear immediately
    retry: 1,
  })

  // Fetch GCal events only when connected (meetings, digests, action items)
  const { data: gcalEvents = [], isLoading: gcalLoading } = useQuery<GCalEvent[]>({
    queryKey: ['calendar-gcal-events', startISO, endISO],
    queryFn: async () => {
      const { data } = await calendarApi.getEvents(startISO, endISO)
      // Exclude [TASK]/[DONE]/[BLOCKED] — shown from local API to avoid duplicates
      return (data as GCalEvent[]).filter((ev) => {
        const s = ev.summary ?? ''
        return !s.startsWith('[TASK]') && !s.startsWith('[DONE]') && !s.startsWith('[BLOCKED]')
      })
    },
    enabled: gcalConnected,
    staleTime: 60_000,
    retry: false,        // don't retry on 500 — show tasks-only silently
    throwOnError: false, // swallow GCal errors; local tasks still display
  })

  // Only block the grid on the tasks load — GCal failing is non-fatal
  const isLoading = tasksLoading

  // Merge tasks + GCal non-task events into unified CalendarItem map
  const itemsByDate = useMemo(() => {
    const map: Record<string, CalendarItem[]> = {}

    const addItem = (item: CalendarItem) => {
      if (!map[item.date]) map[item.date] = []
      map[item.date].push(item)
    }

    // Local tasks
    for (const t of tasksData?.data ?? []) {
      const item = taskToItem(t)
      if (item) addItem(item)
    }

    // GCal non-task events
    for (const ev of gcalEvents) {
      addItem(gcalToItem(ev))
    }

    return map
  }, [tasksData, gcalEvents])

  // Build calendar grid cells
  const cells = useMemo(() => {
    const days: Date[] = []
    const cur = new Date(rangeStart)
    while (cur < rangeEnd) {
      days.push(new Date(cur))
      cur.setDate(cur.getDate() + 1)
    }
    return days
  }, [rangeStart, rangeEnd])

  const prevMonth = () => {
    if (month === 0) { setMonth(11); setYear(y => y - 1) }
    else setMonth(m => m - 1)
  }
  const nextMonth = () => {
    if (month === 11) { setMonth(0); setYear(y => y + 1) }
    else setMonth(m => m + 1)
  }
  const goToday = () => {
    setYear(today.getFullYear())
    setMonth(today.getMonth())
    setSelectedDay(today)
  }

  const todayKey = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`

  const selectedDayKey = selectedDay
    ? `${selectedDay.getFullYear()}-${String(selectedDay.getMonth() + 1).padStart(2, '0')}-${String(selectedDay.getDate()).padStart(2, '0')}`
    : null

  const selectedDayItems: CalendarItem[] = selectedDayKey ? (itemsByDate[selectedDayKey] ?? []) : []

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold">Calendar</h1>
          <p className="text-sm text-muted-foreground">Tasks and events at a glance</p>
        </div>

        {/* Month navigation */}
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={prevMonth}>
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <span className="min-w-[140px] text-center text-sm font-semibold">
            {MONTH_NAMES[month]} {year}
          </span>
          <Button variant="outline" size="sm" onClick={nextMonth}>
            <ChevronRight className="h-4 w-4" />
          </Button>
          <Button variant="outline" size="sm" onClick={goToday}>
            Today
          </Button>
        </div>
      </div>

      {/* Task fetch error */}
      {tasksError && (
        <div className="rounded-lg border border-red-200 bg-red-50 dark:bg-red-950 dark:border-red-800 px-4 py-3 text-sm text-red-700 dark:text-red-400">
          Could not load tasks — please refresh the page. If the problem persists, check that the backend is running.
        </div>
      )}

      {/* Sync feedback */}
      {syncMessage && (
        <div className={cn(
          'rounded-lg px-4 py-3 text-sm',
          syncMessage.type === 'success'
            ? 'border border-green-200 bg-green-50 dark:bg-green-950 dark:border-green-800 text-green-700 dark:text-green-400'
            : 'border border-red-200 bg-red-50 dark:bg-red-950 dark:border-red-800 text-red-700 dark:text-red-400'
        )}>
          {syncMessage.text}
        </div>
      )}

      {/* GCal not connected — soft banner, grid still shows tasks */}
      {!gcalConnected && (
        <div className="flex items-center justify-between gap-3 rounded-lg border border-dashed border-gray-300 dark:border-gray-600 bg-gray-50 dark:bg-gray-800/50 px-4 py-3">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <CalendarDays className="h-4 w-4 shrink-0" />
            <span>Connect Google Calendar to also see meetings and digests here.</span>
          </div>
          <Button asChild size="sm" variant="outline">
            <Link href="/dashboard/settings">
              <ExternalLink className="h-3.5 w-3.5 mr-1.5" />
              Connect
            </Link>
          </Button>
        </div>
      )}

      {/* Sync to Google Calendar — shown when GCal is connected */}
      {gcalConnected && (
        <div className="flex items-center justify-between gap-3 rounded-lg border border-dashed border-gray-300 dark:border-gray-600 bg-gray-50 dark:bg-gray-800/50 px-4 py-3">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <CalendarDays className="h-4 w-4 shrink-0" />
            <span>Push all tasks with due dates to your Google Calendar.</span>
          </div>
          <Button
            size="sm"
            variant="outline"
            onClick={() => syncMutation.mutate()}
            disabled={syncMutation.isPending}
          >
            {syncMutation.isPending
              ? <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
              : <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
            }
            {syncMutation.isPending ? 'Syncing...' : 'Sync to Google Calendar'}
          </Button>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4 items-start">
        {/* Calendar grid */}
        <Card className="lg:col-span-3 overflow-hidden">
          {/* Legend */}
          <CardHeader className="pb-2 pt-3 px-4 border-b border-gray-200 dark:border-gray-700">
            <div className="flex flex-wrap gap-4">
              <LegendDot color="bg-blue-500"   label="Tasks" />
              <LegendDot color="bg-green-500"  label="Meetings" />
              <LegendDot color="bg-orange-500" label="Action Items" />
              <LegendDot color="bg-purple-500" label="Digest / Other" />
            </div>
          </CardHeader>

          {isLoading ? (
            <div className="flex items-center justify-center h-64">
              <Loader2 className="h-7 w-7 animate-spin text-primary" />
            </div>
          ) : (
            /* Grid */
            <div className="overflow-x-auto">
              <div className="min-w-[420px]">
                {/* Day-of-week header */}
                <div className="grid grid-cols-7 border-b border-gray-200 dark:border-gray-700">
                  {DOW_LABELS.map((d) => (
                    <div
                      key={d}
                      className="py-2 text-center text-xs font-medium text-muted-foreground border-r border-gray-200 dark:border-gray-700 last:border-r-0"
                    >
                      {d}
                    </div>
                  ))}
                </div>

                {/* Week rows */}
                {Array.from({ length: cells.length / 7 }).map((_, rowIdx) => (
                  <div key={rowIdx} className="grid grid-cols-7">
                    {cells.slice(rowIdx * 7, rowIdx * 7 + 7).map((day, colIdx) => {
                      const key = `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, '0')}-${String(day.getDate()).padStart(2, '0')}`
                      const dayItems = itemsByDate[key] ?? []
                      const isCurrentMonth = day.getMonth() === month
                      const isToday = key === todayKey
                      const isSelected = selectedDayKey === key

                      return (
                        <div
                          key={key}
                          className={cn(colIdx === 6 ? '' : 'border-r border-gray-200 dark:border-gray-700')}
                        >
                          <DayCell
                            day={day}
                            isToday={isToday}
                            isCurrentMonth={isCurrentMonth}
                            items={dayItems}
                            onDayClick={setSelectedDay}
                            selected={isSelected}
                          />
                        </div>
                      )
                    })}
                  </div>
                ))}
              </div>
            </div>
          )}
        </Card>

        {/* Selected-day panel */}
        <Card className="lg:col-span-1">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-semibold">
              {selectedDay
                ? `${DOW_LABELS[selectedDay.getDay()]}, ${MONTH_NAMES[selectedDay.getMonth()]} ${selectedDay.getDate()}`
                : 'Select a day'}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {selectedDay ? (
              <DayEventList items={selectedDayItems} />
            ) : (
              <p className="text-sm text-muted-foreground">Click a day to see its events.</p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
