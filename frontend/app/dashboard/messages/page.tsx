'use client'

import { useState, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { dmApi } from '@/lib/api'
import { useAuthStore } from '@/lib/stores/authStore'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { MessageSquare, Send, Loader2, Plus, Trash2, ArrowLeft, Search, X } from 'lucide-react'
import { formatRelativeTime } from '@/lib/utils'

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

// ── Avatar ────────────────────────────────────────────────────────────────────

function Avatar({ name, url, size = 9 }: { name: string; url?: string | null; size?: number }) {
  const cls = `h-${size} w-${size} rounded-full flex items-center justify-center text-xs font-bold shrink-0`
  if (url) return <img src={url} alt={name} className={`${cls} object-cover`} />
  return (
    <div className={`${cls} bg-primary text-primary-foreground`}>
      {name.slice(0, 2).toUpperCase()}
    </div>
  )
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function MessagesPage() {
  const { user: currentUser } = useAuthStore()
  const queryClient = useQueryClient()

  const [selectedUserId, setSelectedUserId] = useState<string | null>(null)
  const [showPicker, setShowPicker] = useState(false)   // "New Message" user picker
  const [pickerSearch, setPickerSearch] = useState('')
  const [text, setText] = useState('')
  const [selectedMsgId, setSelectedMsgId] = useState<string | null>(null)
  const [sendError, setSendError] = useState<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  // Stable cache key scoped to this user — prevents bleed-over when switching accounts
  const uid = currentUser?.id ?? 'anon'

  // ── Queries ──────────────────────────────────────────────────────────────

  // Only the logged-in user's own conversations
  const { data: conversations = [], isLoading: convsLoading } = useQuery({
    queryKey: ['dm-conversations', uid],
    queryFn: async () => (await dmApi.getConversations()).data as Conversation[],
    refetchInterval: 5000,
    enabled: !!currentUser,
  })

  // Full message thread with the selected person
  const { data: activeConv, isLoading: msgsLoading } = useQuery({
    queryKey: ['dm-messages', uid, selectedUserId],
    queryFn: async () => (await dmApi.getConversation(selectedUserId!)).data,
    enabled: !!selectedUserId && !!currentUser,
    refetchInterval: 3000,
  })

  // All team members — only fetched when the picker is open
  const { data: members = [], isLoading: membersLoading } = useQuery({
    queryKey: ['dm-users', uid],
    queryFn: async () => (await dmApi.getUsers()).data as TeamMember[],
    enabled: showPicker && !!currentUser,
    staleTime: 60_000,
  })

  // Scroll to latest message
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [activeConv?.messages])

  // ── Mutations ─────────────────────────────────────────────────────────────

  const sendMutation = useMutation({
    mutationFn: ({ recipientId, content }: { recipientId: string; content: string }) =>
      dmApi.sendMessage(recipientId, content),
    onSuccess: (_, vars) => {
      setText('')
      setSendError(null)
      setShowPicker(false)
      setPickerSearch('')
      setSelectedUserId(vars.recipientId)
      queryClient.invalidateQueries({ queryKey: ['dm-messages', uid, vars.recipientId] })
      queryClient.invalidateQueries({ queryKey: ['dm-conversations', uid] })
      queryClient.invalidateQueries({ queryKey: ['dm-unread-count', uid] })
    },
    onError: (err: any) => {
      setSendError(err?.response?.data?.detail || 'Failed to send. Try again.')
      setTimeout(() => setSendError(null), 4000)
    },
  })

  const deleteMsgMutation = useMutation({
    mutationFn: (msgId: string) => dmApi.deleteMessage(msgId),
    onSuccess: () => {
      setSelectedMsgId(null)
      queryClient.invalidateQueries({ queryKey: ['dm-messages', uid, selectedUserId] })
      queryClient.invalidateQueries({ queryKey: ['dm-conversations', uid] })
    },
  })

  // ── Handlers ──────────────────────────────────────────────────────────────

  const handleSend = () => {
    if (!text.trim() || !selectedUserId) return
    sendMutation.mutate({ recipientId: selectedUserId, content: text.trim() })
  }

  const openConversation = (userId: string) => {
    setSelectedUserId(userId)
    setShowPicker(false)
    setPickerSearch('')
    setText('')
    setSelectedMsgId(null)
  }

  const startNewDmWith = (member: TeamMember) => {
    openConversation(member.id)
  }

  const filteredMembers = pickerSearch.trim()
    ? members.filter(
        (m) =>
          m.full_name.toLowerCase().includes(pickerSearch.toLowerCase()) ||
          m.email.toLowerCase().includes(pickerSearch.toLowerCase())
      )
    : members

  const selectedConvMeta =
    conversations.find((c) => c.user_id === selectedUserId) ??
    (activeConv?.user
      ? {
          user_id: activeConv.user.id,
          full_name: activeConv.user.full_name,
          email: activeConv.user.email,
          avatar_url: activeConv.user.avatar_url,
        }
      : null)

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-4 h-full">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <h1 className="text-xl sm:text-2xl font-bold">Direct Messages</h1>
          <p className="text-sm text-muted-foreground">Private messages with your team</p>
        </div>
        <Button
          onClick={() => {
            setShowPicker(true)
            setSelectedUserId(null)
            setPickerSearch('')
          }}
          size="sm"
        >
          <Plus className="h-4 w-4 mr-1" />
          New Message
        </Button>
      </div>

      <div className="flex gap-3 sm:gap-4" style={{ height: 'calc(100vh - 13rem)' }}>

        {/* ── Sidebar: hidden on mobile when a conversation is open ──────── */}
        <div className={`shrink-0 flex flex-col gap-2 overflow-y-auto w-full sm:w-64 lg:w-72 ${
          (selectedUserId || showPicker) ? 'hidden sm:flex' : 'flex'
        }`}>
          {convsLoading ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-primary" />
            </div>
          ) : conversations.length === 0 ? (
            <Card className="p-6 text-center">
              <MessageSquare className="h-8 w-8 mx-auto text-gray-400 mb-2" />
              <p className="text-sm text-muted-foreground">No conversations yet.</p>
              <p className="text-xs text-muted-foreground mt-1">
                Click <strong>New Message</strong> to start one.
              </p>
            </Card>
          ) : (
            <Card className="overflow-hidden">
              <CardContent className="p-0 divide-y">
                {conversations.map((conv) => (
                  <button
                    key={conv.user_id}
                    onClick={() => openConversation(conv.user_id)}
                    className={`w-full text-left px-3 py-3 hover:bg-muted/50 transition-colors flex items-start gap-3 ${
                      selectedUserId === conv.user_id && !showPicker ? 'bg-primary/10' : ''
                    }`}
                  >
                    <Avatar name={conv.full_name} url={conv.avatar_url} />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-semibold truncate">{conv.full_name}</p>
                      <p className="text-xs text-muted-foreground truncate">
                        {conv.is_sent ? 'You: ' : `${conv.full_name}: `}
                        {conv.last_message}
                      </p>
                    </div>
                    <span className="text-xs text-muted-foreground whitespace-nowrap shrink-0 mt-0.5">
                      {formatRelativeTime(conv.last_timestamp)}
                    </span>
                  </button>
                ))}
              </CardContent>
            </Card>
          )}
        </div>

        {/* ── Main panel ─────────────────────────────────────────────────── */}
        <div className={`flex-1 flex flex-col min-w-0 ${
          (!selectedUserId && !showPicker) ? 'hidden sm:flex' : 'flex'
        }`}>

          {/* NEW MESSAGE picker */}
          {showPicker && (
            <Card className="flex-1 flex flex-col overflow-hidden">
              <div className="p-4 border-b flex items-center justify-between shrink-0">
                <p className="font-semibold">New Message — select a person</p>
                <button onClick={() => setShowPicker(false)}>
                  <X className="h-4 w-4 text-muted-foreground" />
                </button>
              </div>
              <div className="p-3 border-b shrink-0">
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input
                    placeholder="Search by name or email..."
                    value={pickerSearch}
                    onChange={(e) => setPickerSearch(e.target.value)}
                    className="pl-9"
                    autoFocus
                  />
                </div>
              </div>
              <div className="flex-1 overflow-y-auto divide-y">
                {membersLoading ? (
                  <div className="flex justify-center py-8">
                    <Loader2 className="h-5 w-5 animate-spin text-primary" />
                  </div>
                ) : filteredMembers.length === 0 ? (
                  <p className="text-sm text-muted-foreground p-4 text-center">No members found.</p>
                ) : (
                  filteredMembers.map((member) => (
                    <button
                      key={member.id}
                      onClick={() => startNewDmWith(member)}
                      className="w-full text-left px-4 py-3 hover:bg-muted/50 transition-colors flex items-center gap-3"
                    >
                      <Avatar name={member.full_name} url={member.avatar_url} />
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-semibold">{member.full_name}</p>
                        <p className="text-xs text-muted-foreground">{member.role.replace(/_/g, ' ')}</p>
                      </div>
                      {conversations.find((c) => c.user_id === member.id) && (
                        <span className="text-xs text-muted-foreground">existing</span>
                      )}
                    </button>
                  ))
                )}
              </div>
            </Card>
          )}

          {/* CONVERSATION thread */}
          {selectedUserId && !showPicker && (
            <Card className="flex-1 flex flex-col overflow-hidden">
              {/* Header */}
              <div className="p-4 border-b flex items-center gap-3 shrink-0">
                <button
                  className="text-muted-foreground hover:text-foreground mr-1"
                  onClick={() => setSelectedUserId(null)}
                  title="Back to conversations"
                >
                  <ArrowLeft className="h-4 w-4" />
                </button>
                {selectedConvMeta && (
                  <>
                    <Avatar name={selectedConvMeta.full_name} url={selectedConvMeta.avatar_url} size={8} />
                    <div>
                      <p className="font-semibold text-sm">{selectedConvMeta.full_name}</p>
                      <p className="text-xs text-muted-foreground">{(selectedConvMeta as any).email ?? ''}</p>
                    </div>
                  </>
                )}
              </div>

              {/* Messages */}
              <div
                className="flex-1 overflow-y-auto p-4 space-y-3"
                onClick={() => setSelectedMsgId(null)}
              >
                {msgsLoading ? (
                  <div className="flex justify-center py-8">
                    <Loader2 className="h-5 w-5 animate-spin text-primary" />
                  </div>
                ) : (activeConv?.messages ?? []).length === 0 ? (
                  <div className="flex items-center justify-center h-full">
                    <p className="text-sm text-muted-foreground">No messages yet. Say hi!</p>
                  </div>
                ) : (
                  <>
                    {(activeConv?.messages ?? []).map((msg: Message) => (
                      <div
                        key={msg.id}
                        className={`flex items-end gap-2 ${msg.is_sent ? 'flex-row-reverse' : 'flex-row'}`}
                      >
                        {!msg.is_sent && activeConv?.user && (
                          <Avatar name={activeConv.user.full_name} url={activeConv.user.avatar_url} size={7} />
                        )}
                        <div
                          className={`max-w-[70%] flex flex-col ${msg.is_sent ? 'items-end' : 'items-start'}`}
                          onClick={(e) => {
                            e.stopPropagation()
                            if (msg.is_sent) setSelectedMsgId(selectedMsgId === msg.id ? null : msg.id)
                          }}
                        >
                          {!msg.is_sent && activeConv?.user && (
                            <span className="text-xs font-semibold text-muted-foreground mb-0.5">
                              {activeConv.user.full_name}
                            </span>
                          )}
                          <div
                            className={`rounded-2xl px-3 py-2 text-sm cursor-pointer ${
                              msg.is_sent
                                ? 'bg-primary text-primary-foreground rounded-br-sm'
                                : 'bg-muted rounded-bl-sm'
                            }`}
                          >
                            <p className="whitespace-pre-wrap break-words">{msg.content}</p>
                          </div>
                          <span className="text-xs text-muted-foreground mt-0.5">
                            {formatRelativeTime(msg.created_at)}
                          </span>
                          {msg.is_sent && selectedMsgId === msg.id && (
                            <button
                              onClick={(e) => {
                                e.stopPropagation()
                                deleteMsgMutation.mutate(msg.id)
                              }}
                              disabled={deleteMsgMutation.isPending}
                              className="mt-1 flex items-center gap-1 text-xs text-red-500 hover:text-red-700"
                            >
                              {deleteMsgMutation.isPending ? (
                                <Loader2 className="h-3 w-3 animate-spin" />
                              ) : (
                                <>
                                  <Trash2 className="h-3 w-3" /> Delete
                                </>
                              )}
                            </button>
                          )}
                        </div>
                      </div>
                    ))}
                    <div ref={bottomRef} />
                  </>
                )}
              </div>

              {/* Input */}
              <div className="border-t p-4 shrink-0">
                <div className="flex gap-2">
                  <Input
                    placeholder={`Message ${selectedConvMeta?.full_name ?? '...'}...`}
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault()
                        handleSend()
                      }
                    }}
                    disabled={sendMutation.isPending}
                  />
                  <Button onClick={handleSend} disabled={!text.trim() || sendMutation.isPending}>
                    {sendMutation.isPending ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Send className="h-4 w-4" />
                    )}
                  </Button>
                </div>
                {sendError && <p className="text-xs text-red-500 mt-1">{sendError}</p>}
              </div>
            </Card>
          )}

          {/* Empty state */}
          {!selectedUserId && !showPicker && (
            <div className="flex-1 flex items-center justify-center">
              <div className="text-center">
                <MessageSquare className="h-12 w-12 mx-auto text-gray-400 mb-3" />
                <p className="text-muted-foreground">Select a conversation or start a new one</p>
                <Button
                  variant="outline"
                  className="mt-4"
                  onClick={() => {
                    setShowPicker(true)
                    setPickerSearch('')
                  }}
                >
                  <Plus className="h-4 w-4 mr-2" />
                  New Message
                </Button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
