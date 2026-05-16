'use client'

import { useState, useRef, useEffect, useCallback } from 'react'
import { useMutation } from '@tanstack/react-query'
import { chatApi } from '@/lib/api'
import { useAuthStore } from '@/lib/stores/authStore'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Send, Sparkles, Loader2, RotateCcw, ShieldCheck, User as UserIcon } from 'lucide-react'
import type { ChatResponse } from '@/types'
import { ROLE_LABELS } from '@/types'

interface HistoryEntry {
  role: 'user' | 'assistant'
  content: string
}

interface Message extends HistoryEntry {
  suggestedActions?: Array<{
    action: string
    label: string
    url: string
  }>
  isError?: boolean
}

const SUGGESTED_QUERIES_GROUPED = [
  {
    label: 'My Tasks',
    queries: [
      "What's on my plate this week?",
      'Show me my overdue tasks',
      'What are my blocked tasks?',
      'Show me my in-progress tasks',
      'How many tasks do I have?',
    ],
  },
  {
    label: 'Priorities',
    queries: [
      'Show me my high priority tasks',
      'What urgent tasks do I have?',
      "What's due today?",
    ],
  },
  {
    label: 'Meetings',
    queries: [
      'Summarize our last meeting',
      'What action items came from recent meetings?',
      'What decisions were made recently?',
    ],
  },
  {
    label: 'Team (Admin)',
    queries: [
      "What's the team workload?",
      'Who has the most active tasks?',
      'Are there any overdue tasks across the team?',
    ],
  },
]

function RoleBadge({ role }: { role: string }) {
  const isAdmin = role === 'admin'
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium ${
        isAdmin
          ? 'bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300'
          : 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300'
      }`}
    >
      {isAdmin ? <ShieldCheck className="h-3 w-3" /> : <UserIcon className="h-3 w-3" />}
      {ROLE_LABELS[role as keyof typeof ROLE_LABELS] ?? role}
    </span>
  )
}

function TaskLine({ line }: { line: string }) {
  const isOverdue = line.includes('⚠') || line.toLowerCase().includes('overdue')
  return (
    <span className={isOverdue ? 'text-red-500 dark:text-red-400 font-medium' : ''}>
      {line}
    </span>
  )
}

function MessageContent({ content }: { content: string }) {
  const lines = content.split('\n')
  return (
    <div className="space-y-0.5">
      {lines.map((line, i) => {
        const trimmed = line.trimStart()
        const isBullet = trimmed.startsWith('•') || trimmed.startsWith('-') || trimmed.startsWith('*')
        return (
          <div key={i} className={isBullet ? 'pl-2' : ''}>
            <TaskLine line={line} />
          </div>
        )
      })}
    </div>
  )
}

export default function ChatPage() {
  const { user } = useAuthStore()
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [history, setHistory] = useState<HistoryEntry[]>([])
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const chatMutation = useMutation({
    mutationFn: (message: string) =>
      chatApi.query(message, history),
    onSuccess: (response: { data: ChatResponse }, sentMessage: string) => {
      const assistantContent = response.data.response
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: assistantContent,
          suggestedActions: response.data.suggested_actions,
        },
      ])
      setHistory((prev) => [
        ...prev,
        { role: 'user', content: sentMessage },
        { role: 'assistant', content: assistantContent },
      ])
    },
    onError: (error: any) => {
      const detail = error?.response?.data?.detail ?? 'Something went wrong. Please try again.'
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: detail, isError: true },
      ])
    },
  })

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault()
      const text = input.trim()
      if (!text || chatMutation.isPending) return
      setInput('')
      setMessages((prev) => [...prev, { role: 'user', content: text }])
      chatMutation.mutate(text)
    },
    [input, chatMutation],
  )

  const handleSuggestedQuery = (query: string) => {
    setInput(query)
    inputRef.current?.focus()
  }

  const handleReset = () => {
    setMessages([])
    setHistory([])
    setInput('')
  }

  const isAdmin = user?.role === 'admin'

  return (
    <div className="h-[calc(100vh-12rem)] flex flex-col">
      {/* Header */}
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Sparkles className="h-6 w-6 text-primary" />
            AI Assistant
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Ask questions about your tasks, meetings, and{' '}
            {isAdmin ? 'team workload' : 'your workspace'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {user && <RoleBadge role={user.role} />}
          {messages.length > 0 && (
            <Button variant="outline" size="sm" onClick={handleReset} className="gap-1 text-xs">
              <RotateCcw className="h-3 w-3" />
              New chat
            </Button>
          )}
        </div>
      </div>

      <div className="flex-1 flex gap-4 overflow-hidden">
        {/* Chat area */}
        <div className="flex-1 flex flex-col bg-background rounded-lg border border-border overflow-hidden">
          {/* Messages */}
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            {messages.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full text-center px-4">
                <Sparkles className="h-12 w-12 text-primary mb-4 opacity-80" />
                <h2 className="text-lg font-semibold mb-1">
                  Hi {user?.full_name?.split(' ')[0] ?? 'there'}, what can I help with?
                </h2>
                <p className="text-sm text-muted-foreground max-w-md">
                  {isAdmin
                    ? 'As admin you can ask about your tasks, any team member\'s tasks, team workload, and meeting summaries.'
                    : 'Ask about your assigned tasks, priorities, deadlines, overdue items, or recent meeting summaries.'}
                </p>
              </div>
            ) : (
              <>
                {messages.map((message, index) => (
                  <div
                    key={index}
                    className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
                  >
                    <div
                      className={`max-w-[80%] rounded-lg px-4 py-2.5 text-sm ${
                        message.role === 'user'
                          ? 'bg-primary text-primary-foreground'
                          : message.isError
                          ? 'bg-red-50 text-red-800 border border-red-200 dark:bg-red-950/50 dark:text-red-300 dark:border-red-800'
                          : 'bg-muted text-foreground border border-border'
                      }`}
                    >
                      {message.role === 'user' ? (
                        <p className="whitespace-pre-wrap">{message.content}</p>
                      ) : (
                        <MessageContent content={message.content} />
                      )}

                      {message.suggestedActions && message.suggestedActions.length > 0 && (
                        <div className="mt-3 flex flex-wrap gap-2">
                          {message.suggestedActions.map((action, idx) => (
                            <a
                              key={idx}
                              href={action.url}
                              className="inline-flex items-center px-3 py-1.5 text-xs font-medium bg-background text-foreground rounded-full border border-border hover:bg-muted transition-colors shadow-sm"
                            >
                              {action.label}
                            </a>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                ))}

                {chatMutation.isPending && (
                  <div className="flex justify-start">
                    <div className="bg-muted border border-border rounded-lg px-4 py-2.5">
                      <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                    </div>
                  </div>
                )}

                <div ref={messagesEndRef} />
              </>
            )}
          </div>

          {/* Input */}
          <form onSubmit={handleSubmit} className="border-t p-3">
            <div className="flex gap-2">
              <input
                ref={inputRef}
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Ask about your tasks, deadlines, or meetings…"
                className="flex-1 px-4 py-2 text-sm border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring bg-background text-foreground placeholder:text-muted-foreground"
                disabled={chatMutation.isPending}
              />
              <Button
                type="submit"
                size="sm"
                disabled={!input.trim() || chatMutation.isPending}
                className="px-3"
              >
                {chatMutation.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Send className="h-4 w-4" />
                )}
              </Button>
            </div>
            {history.length > 0 && (
              <p className="text-[11px] text-muted-foreground mt-1.5 px-1">
                {Math.floor(history.length / 2)} message{history.length / 2 !== 1 ? 's' : ''} in this conversation
              </p>
            )}
          </form>
        </div>

        {/* Suggested queries sidebar */}
        <Card className="w-60 p-3 hidden lg:flex flex-col gap-3 overflow-y-auto">
          <h3 className="font-semibold text-sm text-foreground">Suggested queries</h3>
          {SUGGESTED_QUERIES_GROUPED.map((group) => {
            if (group.label === 'Team (Admin)' && !isAdmin) return null
            return (
              <div key={group.label}>
                <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-1.5">
                  {group.label}
                </p>
                <div className="space-y-1">
                  {group.queries.map((query, idx) => (
                    <button
                      key={idx}
                      onClick={() => handleSuggestedQuery(query)}
                      className="w-full text-left text-xs px-2.5 py-1.5 rounded-md hover:bg-muted transition-colors text-foreground leading-snug"
                    >
                      {query}
                    </button>
                  ))}
                </div>
              </div>
            )
          })}
        </Card>
      </div>
    </div>
  )
}
