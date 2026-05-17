'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { commentsApi } from '@/lib/api'
import { useAuthStore } from '@/lib/stores/authStore'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { MessageSquare, Trash2, Loader2 } from 'lucide-react'
import { format } from 'date-fns'
import type { TaskComment } from '@/types'

// Small Jira logo SVG badge
function JiraIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      className="h-3 w-3 fill-blue-500 shrink-0"
      aria-label="Jira"
    >
      <path d="M11.975 0C5.366 0 0 5.366 0 11.975c0 6.609 5.366 11.975 11.975 11.975 6.609 0 11.975-5.366 11.975-11.975C23.95 5.366 18.584 0 11.975 0zm.05 4.59l5.47 7.432-5.47 5.47-5.47-5.47 5.47-7.432z" />
    </svg>
  )
}

interface Props {
  taskId: string
  currentUserId: string
}

export function TaskCommentSection({ taskId, currentUserId }: Props) {
  const queryClient = useQueryClient()
  const { user } = useAuthStore()
  const [draft, setDraft] = useState('')

  const { data: comments = [], isLoading } = useQuery<TaskComment[]>({
    queryKey: ['task-comments', taskId],
    queryFn: async () => (await commentsApi.getComments(taskId)).data,
    staleTime: 30_000,
  })

  const addMutation = useMutation({
    mutationFn: (body: string) => commentsApi.addComment(taskId, body),
    onSuccess: () => {
      setDraft('')
      queryClient.invalidateQueries({ queryKey: ['task-comments', taskId] })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (commentId: string) => commentsApi.deleteComment(taskId, commentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['task-comments', taskId] })
    },
  })

  const handlePost = () => {
    if (!draft.trim()) return
    addMutation.mutate(draft.trim())
  }

  const isAdmin = user?.role === 'admin'

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
        <MessageSquare className="h-4 w-4" />
        Comments {comments.length > 0 && `(${comments.length})`}
      </div>

      {/* Comment list */}
      {isLoading ? (
        <div className="flex items-center gap-2 text-xs text-muted-foreground py-2">
          <Loader2 className="h-3 w-3 animate-spin" />
          Loading…
        </div>
      ) : comments.length === 0 ? (
        <p className="text-xs text-muted-foreground italic">No comments yet.</p>
      ) : (
        <ul className="space-y-2">
          {comments.map((c) => (
            <li
              key={c.id}
              className="rounded-md border bg-muted/30 px-3 py-2 text-sm"
            >
              <div className="flex items-center justify-between gap-2 mb-1">
                <div className="flex items-center gap-1.5 min-w-0">
                  {c.source === 'jira' && <JiraIcon />}
                  <span className="font-medium text-xs truncate">
                    {c.author_name ?? 'Unknown'}
                  </span>
                  <span className="text-xs text-muted-foreground shrink-0">
                    {format(new Date(c.created_at), 'MMM d, HH:mm')}
                  </span>
                  {c.source === 'jira' && (
                    <span className="text-[10px] text-blue-500 font-medium shrink-0">via Jira</span>
                  )}
                </div>
                {(isAdmin || c.author_id === currentUserId) && c.source === 'synkro' && (
                  <button
                    type="button"
                    onClick={() => deleteMutation.mutate(c.id)}
                    disabled={deleteMutation.isPending}
                    className="text-muted-foreground hover:text-destructive shrink-0"
                    title="Delete comment"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                )}
              </div>
              <p className="text-xs whitespace-pre-wrap break-words">{c.body}</p>
            </li>
          ))}
        </ul>
      )}

      {/* New comment input */}
      <div className="space-y-2">
        <Textarea
          placeholder="Add a comment…"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          rows={2}
          className="text-sm resize-none"
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
              e.preventDefault()
              handlePost()
            }
          }}
        />
        <div className="flex items-center justify-between gap-2">
          <span className="text-[10px] text-muted-foreground">Ctrl+Enter to post</span>
          <Button
            type="button"
            size="sm"
            disabled={!draft.trim() || addMutation.isPending}
            onClick={handlePost}
          >
            {addMutation.isPending ? (
              <Loader2 className="h-3 w-3 animate-spin mr-1" />
            ) : null}
            Post
          </Button>
        </div>
        {addMutation.isError && (
          <p className="text-xs text-red-500">Failed to post comment.</p>
        )}
      </div>
    </div>
  )
}
