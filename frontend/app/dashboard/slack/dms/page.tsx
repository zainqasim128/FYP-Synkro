'use client'

import { useState, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { dmApi } from '@/lib/api'
import { useAuthStore } from '@/lib/stores/authStore'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import {
  MessageSquare,
  Send,
  Loader2,
  ArrowLeft,
  User,
  Search,
  X,
  RefreshCw,
} from 'lucide-react'
import { formatRelativeTime } from '@/lib/utils'
import Link from 'next/link'

// ── Types ────────────────────────────────────────────────────────────────────

interface TeamMember {
  id: string
  full_name: string
  email: string
  role: string
  avatar_url: string | null
}

interface Conversation {
  user_id: string
  full_name: string
  email: string
  avatar_url: string | null
  last_message: string
  last_timestamp: string
  is_sent: boolean
}

interface Message {
  id: string
  sender_id: string
  content: string
  created_at: string
  is_sent: boolean
}

interface ConversationThread {
  user: {
    id: string
    full_name: string
    email: string
    avatar_url: string | null
  }
  messages: Message[]
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function Avatar({ name, url, size = 'md' }: { name: string; url?: string | null; size?: 'sm' | 'md' }) {
  const cls = size === 'sm' ? 'h-7 w-7 text-xs' : 'h-9 w-9 text-xs'
  if (url) {
    return <img src={url} alt={name} className={`${cls} rounded-full object-cover`} />
  }
  return (
    <div className={`${cls} shrink-0 rounded-full bg-[#4A154B] flex items-center justify-center text-white font-bold`}>
      {name?.slice(0, 2).toUpperCase() || <User className="h-4 w-4" />}
    </div>
  )
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function SlackDmsPage() {
  const queryClient = useQueryClient()
  const { user: currentUser } = useAuthStore()
  const uid = currentUser?.id ?? 'anon'

  // Which conversation is open (by Synkro user_id of the other person)
  const [selectedUserId, setSelectedUserId] = useState<string | null>(null)
  // Are we composing a new DM?
  const [composing, setComposing] = useState(false)
  // Picked user for new DM
  const [newDmTarget, setNewDmTarget] = useState<TeamMember | null>(null)
  // Message input text
  const [messageText, setMessageText] = useState('')
  // Search filter for user picker
  const [userSearch, setUserSearch] = useState('')

  const messagesEndRef = useRef<HTMLDivElement>(null)

  // ── Data fetching ──────────────────────────────────────────────────────────

  // List of existing conversations (sidebar) — keyed by user ID to prevent cross-user cache bleed
  const { data: conversations = [], isLoading: convsLoading, refetch: refetchConvs } = useQuery({
    queryKey: ['dm-conversations', uid],
    queryFn: async () => (await dmApi.getConversations()).data as Conversation[],
    refetchInterval: 8000,
    enabled: !!currentUser,
  })

  // Full message thread for the selected conversation
  const { data: thread, isLoading: threadLoading, refetch: refetchThread } = useQuery({
    queryKey: ['dm-thread', uid, selectedUserId],
    queryFn: async () => (await dmApi.getConversation(selectedUserId!)).data as ConversationThread,
    enabled: !!selectedUserId && !composing && !!currentUser,
    refetchInterval: 5000,
  })

  // All team members (for new DM picker)
  const { data: teamMembers = [], isLoading: membersLoading } = useQuery({
    queryKey: ['dm-team-members', uid],
    queryFn: async () => (await dmApi.getUsers()).data as TeamMember[],
    enabled: composing && !!currentUser,
  })

  // Scroll to bottom when messages load or new message arrives
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [thread?.messages])

  // ── Send mutation ──────────────────────────────────────────────────────────

  const sendMutation = useMutation({
    mutationFn: async ({ recipientId, content }: { recipientId: string; content: string }) =>
      dmApi.sendMessage(recipientId, content),
    onSuccess: (_, variables) => {
      setMessageText('')
      setNewDmTarget(null)
      setComposing(false)
      setSelectedUserId(variables.recipientId)
      // Refresh both lists
      queryClient.invalidateQueries({ queryKey: ['dm-conversations', uid] })
      queryClient.invalidateQueries({ queryKey: ['dm-thread', uid, variables.recipientId] })
      queryClient.invalidateQueries({ queryKey: ['dm-unread-count', uid] })
    },
  })

  const handleSend = () => {
    const text = messageText.trim()
    if (!text) return
    const recipientId = newDmTarget?.id ?? selectedUserId
    if (!recipientId) return
    sendMutation.mutate({ recipientId, content: text })
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const openNewDm = (member: TeamMember) => {
    // If a conversation already exists with this user, just open it
    const existing = conversations.find((c) => c.user_id === member.id)
    if (existing) {
      setSelectedUserId(member.id)
      setComposing(false)
      setNewDmTarget(null)
    } else {
      setNewDmTarget(member)
      setSelectedUserId(null)
    }
    setUserSearch('')
  }

  const filteredMembers = teamMembers.filter(
    (m) =>
      m.full_name.toLowerCase().includes(userSearch.toLowerCase()) ||
      m.email.toLowerCase().includes(userSearch.toLowerCase())
  )

  const selectedConv = conversations.find((c) => c.user_id === selectedUserId) ?? null

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link href="/dashboard/slack">
            <Button variant="ghost" size="sm">
              <ArrowLeft className="h-4 w-4 mr-1" />
              Slack
            </Button>
          </Link>
          <div>
            <h1 className="text-2xl font-bold">Direct Messages</h1>
            <p className="text-sm text-muted-foreground">Private messages with your team</p>
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => refetchConvs()}>
            <RefreshCw className="h-4 w-4 mr-1" />
            Refresh
          </Button>
          <Button
            onClick={() => {
              setComposing(true)
              setSelectedUserId(null)
              setNewDmTarget(null)
              setUserSearch('')
            }}
          >
            <MessageSquare className="h-4 w-4 mr-2" />
            New DM
          </Button>
        </div>
      </div>

      {/* Main layout */}
      <div className="flex gap-4 h-[calc(100vh-14rem)]">

        {/* ── Conversation sidebar ─────────────────────────────────────────── */}
        <div className="w-72 shrink-0 flex flex-col gap-2 overflow-hidden">
          {convsLoading ? (
            <div className="flex items-center justify-center py-10">
              <Loader2 className="h-6 w-6 animate-spin text-primary" />
            </div>
          ) : conversations.length === 0 ? (
            <Card className="p-6 text-center">
              <MessageSquare className="h-8 w-8 mx-auto text-gray-400 mb-2" />
              <p className="text-sm text-muted-foreground">No conversations yet.</p>
              <p className="text-xs text-muted-foreground mt-1">
                Click <strong>New DM</strong> to start one.
              </p>
            </Card>
          ) : (
            <Card className="overflow-y-auto flex-1">
              <CardContent className="p-0 divide-y">
                {conversations.map((conv) => (
                  <button
                    key={conv.user_id}
                    className={`w-full text-left px-3 py-3 hover:bg-muted/50 transition-colors flex items-start gap-3 ${
                      selectedUserId === conv.user_id && !composing ? 'bg-primary/10' : ''
                    }`}
                    onClick={() => {
                      setSelectedUserId(conv.user_id)
                      setComposing(false)
                      setNewDmTarget(null)
                    }}
                  >
                    <Avatar name={conv.full_name} url={conv.avatar_url} />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-semibold truncate">{conv.full_name}</p>
                      <p className="text-xs text-muted-foreground truncate">
                        {conv.is_sent ? 'You: ' : ''}{conv.last_message}
                      </p>
                    </div>
                    <span className="text-xs text-muted-foreground whitespace-nowrap shrink-0 mt-0.5">
                      {conv.last_timestamp ? formatRelativeTime(conv.last_timestamp) : ''}
                    </span>
                  </button>
                ))}
              </CardContent>
            </Card>
          )}
        </div>

        {/* ── Right panel ─────────────────────────────────────────────────── */}
        <div className="flex-1 flex flex-col min-w-0">

          {/* NEW DM — user picker */}
          {composing && !newDmTarget && (
            <Card className="flex-1 flex flex-col overflow-hidden">
              <div className="p-4 border-b flex items-center justify-between">
                <h2 className="font-semibold">New Direct Message</h2>
                <button onClick={() => setComposing(false)}>
                  <X className="h-4 w-4 text-muted-foreground" />
                </button>
              </div>
              <div className="p-4 flex-1 overflow-hidden flex flex-col">
                <div className="relative mb-3">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input
                    placeholder="Search team members..."
                    value={userSearch}
                    onChange={(e) => setUserSearch(e.target.value)}
                    className="pl-9"
                    autoFocus
                  />
                </div>
                {membersLoading ? (
                  <div className="flex items-center justify-center py-8">
                    <Loader2 className="h-5 w-5 animate-spin text-primary" />
                  </div>
                ) : filteredMembers.length === 0 ? (
                  <p className="text-sm text-muted-foreground text-center py-8">No team members found.</p>
                ) : (
                  <div className="space-y-1 overflow-y-auto flex-1">
                    {filteredMembers.map((member) => (
                      <button
                        key={member.id}
                        className="w-full text-left flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-muted/50 transition-colors"
                        onClick={() => openNewDm(member)}
                      >
                        <Avatar name={member.full_name} url={member.avatar_url} size="sm" />
                        <div>
                          <p className="text-sm font-medium">{member.full_name}</p>
                          <p className="text-xs text-muted-foreground">{member.email}</p>
                        </div>
                        {conversations.find((c) => c.user_id === member.id) && (
                          <Badge variant="secondary" className="ml-auto text-xs">existing</Badge>
                        )}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </Card>
          )}

          {/* NEW DM — compose panel (target selected, no existing thread) */}
          {composing && newDmTarget && (
            <Card className="flex-1 flex flex-col overflow-hidden">
              <div className="p-4 border-b flex items-center gap-3">
                <button
                  className="text-muted-foreground hover:text-foreground mr-1"
                  onClick={() => setNewDmTarget(null)}
                >
                  <ArrowLeft className="h-4 w-4" />
                </button>
                <Avatar name={newDmTarget.full_name} url={newDmTarget.avatar_url} size="sm" />
                <div>
                  <p className="font-semibold text-sm">{newDmTarget.full_name}</p>
                  <p className="text-xs text-muted-foreground">{newDmTarget.email}</p>
                </div>
                <button className="ml-auto text-muted-foreground hover:text-foreground" onClick={() => setComposing(false)}>
                  <X className="h-4 w-4" />
                </button>
              </div>
              <div className="flex-1 flex items-center justify-center">
                <p className="text-sm text-muted-foreground">
                  Start a conversation with <strong>{newDmTarget.full_name}</strong>
                </p>
              </div>
              <div className="border-t p-4">
                <div className="flex gap-2">
                  <Input
                    placeholder={`Message ${newDmTarget.full_name}...`}
                    value={messageText}
                    onChange={(e) => setMessageText(e.target.value)}
                    onKeyDown={handleKeyDown}
                    disabled={sendMutation.isPending}
                    autoFocus
                  />
                  <Button
                    onClick={handleSend}
                    disabled={!messageText.trim() || sendMutation.isPending}
                  >
                    {sendMutation.isPending
                      ? <Loader2 className="h-4 w-4 animate-spin" />
                      : <Send className="h-4 w-4" />}
                  </Button>
                </div>
                {sendMutation.isError && (
                  <p className="text-xs text-red-500 mt-1">Failed to send. Please try again.</p>
                )}
              </div>
            </Card>
          )}

          {/* EXISTING CONVERSATION thread */}
          {selectedUserId && !composing && (
            <Card className="flex-1 flex flex-col overflow-hidden">
              {/* Thread header */}
              <div className="p-4 border-b flex items-center gap-3">
                <Avatar
                  name={thread?.user.full_name ?? selectedConv?.full_name ?? '?'}
                  url={thread?.user.avatar_url ?? selectedConv?.avatar_url}
                  size="sm"
                />
                <div>
                  <p className="font-semibold text-sm">
                    {thread?.user.full_name ?? selectedConv?.full_name ?? 'Loading...'}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {thread?.user.email ?? selectedConv?.email ?? ''}
                  </p>
                </div>
                <button
                  className="ml-auto text-muted-foreground hover:text-foreground"
                  onClick={() => refetchThread()}
                  title="Refresh messages"
                >
                  <RefreshCw className="h-4 w-4" />
                </button>
              </div>

              {/* Messages */}
              <div className="flex-1 overflow-y-auto p-4 space-y-3">
                {threadLoading ? (
                  <div className="flex items-center justify-center h-full">
                    <Loader2 className="h-6 w-6 animate-spin text-primary" />
                  </div>
                ) : !thread || thread.messages.length === 0 ? (
                  <div className="flex items-center justify-center h-full">
                    <p className="text-sm text-muted-foreground">No messages yet. Send one below.</p>
                  </div>
                ) : (
                  thread.messages.map((msg) => {
                    const isSent = msg.is_sent
                    const senderName = isSent ? 'You' : thread.user.full_name
                    return (
                      <div
                        key={msg.id}
                        className={`flex items-end gap-2 ${isSent ? 'flex-row-reverse' : 'flex-row'}`}
                      >
                        {!isSent && (
                          <Avatar name={thread.user.full_name} url={thread.user.avatar_url} size="sm" />
                        )}
                        <div className={`max-w-[70%] flex flex-col ${isSent ? 'items-end' : 'items-start'}`}>
                          {!isSent && (
                            <span className="text-xs font-semibold text-muted-foreground mb-0.5">
                              {senderName}
                            </span>
                          )}
                          <div
                            className={`rounded-2xl px-3 py-2 text-sm ${
                              isSent
                                ? 'bg-primary text-primary-foreground rounded-br-sm'
                                : 'bg-muted rounded-bl-sm'
                            }`}
                          >
                            <p className="whitespace-pre-wrap break-words">{msg.content}</p>
                          </div>
                          <span className="text-xs text-muted-foreground mt-0.5">
                            {msg.created_at ? formatRelativeTime(msg.created_at) : ''}
                          </span>
                        </div>
                      </div>
                    )
                  })
                )}
                <div ref={messagesEndRef} />
              </div>

              {/* Reply box */}
              <div className="border-t p-4">
                <div className="flex gap-2">
                  <Input
                    placeholder={`Reply to ${thread?.user.full_name ?? '...'}...`}
                    value={messageText}
                    onChange={(e) => setMessageText(e.target.value)}
                    onKeyDown={handleKeyDown}
                    disabled={sendMutation.isPending}
                  />
                  <Button
                    onClick={handleSend}
                    disabled={!messageText.trim() || sendMutation.isPending}
                  >
                    {sendMutation.isPending
                      ? <Loader2 className="h-4 w-4 animate-spin" />
                      : <Send className="h-4 w-4" />}
                  </Button>
                </div>
                {sendMutation.isError && (
                  <p className="text-xs text-red-500 mt-1">Failed to send message.</p>
                )}
              </div>
            </Card>
          )}

          {/* Empty state */}
          {!composing && !selectedUserId && (
            <div className="flex-1 flex items-center justify-center">
              <div className="text-center">
                <MessageSquare className="h-12 w-12 mx-auto text-gray-400 mb-3" />
                <p className="text-muted-foreground">Select a conversation or start a new DM</p>
                <Button
                  variant="outline"
                  className="mt-4"
                  onClick={() => {
                    setComposing(true)
                    setNewDmTarget(null)
                    setUserSearch('')
                  }}
                >
                  <MessageSquare className="h-4 w-4 mr-2" />
                  New DM
                </Button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
