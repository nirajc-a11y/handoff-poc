import { useConversation, useConversationHandoffs } from '@/hooks/use-conversations'
import { useMessages } from '@/hooks/use-messages'
import { MessageThread } from '@/components/live/message-thread'
import { RecordingPlayer } from './recording-player'
import { cn, formatTime, formatDuration, stateColors, channelIcons } from '@/lib/utils'
import type { HandoffEvent } from '@/lib/types'
import { Phone, Clock, User, ArrowRight } from 'lucide-react'

interface HistoryDetailProps {
  conversationId: string
}

export function HistoryDetail({ conversationId }: HistoryDetailProps) {
  const { data: conv, isLoading: convLoading } = useConversation(conversationId)
  const { data: messages = [] } = useMessages(conversationId)
  const { data: apiHandoffs = [] } = useConversationHandoffs(conversationId)

  if (convLoading) {
    return (
      <div className="flex flex-1 items-center justify-center p-8">
        <p className="text-sm text-muted-foreground">Loading...</p>
      </div>
    )
  }

  if (!conv) {
    return (
      <div className="flex flex-1 items-center justify-center p-8">
        <p className="text-sm text-muted-foreground">Conversation not found.</p>
      </div>
    )
  }

  const contextHandoffs: HandoffEvent[] =
    Array.isArray((conv.context as Record<string, unknown>)?.handoff_events)
      ? ((conv.context as Record<string, unknown>).handoff_events as HandoffEvent[])
      : []
  const handoffEvents = apiHandoffs.length > 0 ? apiHandoffs : contextHandoffs

  return (
    <div className="flex flex-col gap-4 p-4 overflow-y-auto">
      {/* Customer info header */}
      <div className="rounded-xl ring-1 ring-foreground/10 bg-card p-4 flex flex-col gap-3">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-2">
            <div className="size-8 rounded-full bg-muted flex items-center justify-center">
              <User className="size-4 text-muted-foreground" />
            </div>
            <div>
              <p className="font-medium text-sm">
                {conv.customer_name ?? conv.customer_identifier}
              </p>
              {conv.customer_name && (
                <p className="text-xs text-muted-foreground">{conv.customer_identifier}</p>
              )}
            </div>
          </div>
          <span
            className={cn(
              'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium',
              stateColors[conv.state] ?? 'bg-gray-100 text-gray-700'
            )}
          >
            {conv.state.replace(/_/g, ' ')}
          </span>
        </div>

        <div className="grid grid-cols-3 gap-3 text-xs">
          <div className="flex flex-col gap-0.5">
            <span className="text-muted-foreground">Channel</span>
            <span className="flex items-center gap-1">
              <span>{channelIcons[conv.channel]}</span>
              <span className="capitalize">{conv.channel}</span>
            </span>
          </div>
          <div className="flex flex-col gap-0.5">
            <span className="text-muted-foreground">Duration</span>
            <span className="flex items-center gap-1">
              <Clock className="size-3" />
              {formatDuration(conv.duration_seconds)}
            </span>
          </div>
          <div className="flex flex-col gap-0.5">
            <span className="text-muted-foreground">Handler</span>
            <span className="capitalize">{conv.current_handler_type}</span>
          </div>
        </div>

        {conv.started_at && (
          <div className="text-xs text-muted-foreground">
            Started: {formatTime(conv.started_at)}
            {conv.ended_at && ` · Ended: ${formatTime(conv.ended_at)}`}
          </div>
        )}

        {conv.disposition && (
          <div className="text-xs">
            <span className="text-muted-foreground">Disposition: </span>
            <span className="font-medium">{conv.disposition}</span>
            {conv.disposition_notes && (
              <p className="mt-0.5 text-muted-foreground">{conv.disposition_notes}</p>
            )}
          </div>
        )}
      </div>

      {/* Message thread */}
      <div className="rounded-xl ring-1 ring-foreground/10 bg-card overflow-hidden">
        <div className="px-4 py-2.5 border-b">
          <p className="text-sm font-medium">Messages</p>
        </div>
        <div className="h-64 flex flex-col">
          <MessageThread conversationId={conversationId} />
        </div>
      </div>

      {/* Recording player */}
      <RecordingPlayer messages={messages} />

      {/* Handoff event timeline */}
      {handoffEvents.length > 0 && (
        <div className="rounded-xl ring-1 ring-foreground/10 bg-card p-4">
          <p className="text-sm font-medium mb-3">Handoff Timeline</p>
          <div className="flex flex-col gap-2">
            {handoffEvents.map((event, i) => (
              <div key={event.id ?? i} className="flex items-start gap-2">
                <div className="mt-0.5 size-5 rounded-full bg-muted flex items-center justify-center shrink-0">
                  <Phone className="size-3 text-muted-foreground" />
                </div>
                <div className="flex flex-col gap-0.5 min-w-0">
                  <div className="flex items-center gap-1.5 text-xs">
                    <span className="font-medium capitalize">
                      {event.event_type.replace(/_/g, ' ')}
                    </span>
                    <span className="text-muted-foreground">
                      {formatTime(event.created_at)}
                    </span>
                  </div>
                  {event.from_handler_type && event.to_handler_type && (
                    <div className="flex items-center gap-1 text-xs text-muted-foreground">
                      <span className="capitalize">{event.from_handler_type}</span>
                      <ArrowRight className="size-3" />
                      <span className="capitalize">{event.to_handler_type}</span>
                    </div>
                  )}
                  {event.reason && (
                    <p className="text-xs text-muted-foreground truncate">{event.reason}</p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
