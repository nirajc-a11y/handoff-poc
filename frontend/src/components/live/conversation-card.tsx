import { useState, useEffect } from 'react'
import { ArrowDownLeft, ArrowUpRight } from 'lucide-react'
import type { Conversation } from '@/lib/types'
import { cn, stateColors, channelIcons, timeSince, formatDuration } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'

interface ConversationCardProps {
  conversation: Conversation
  selected: boolean
  onClick: () => void
}

export function ConversationCard({ conversation, selected, onClick }: ConversationCardProps) {
  const [elapsed, setElapsed] = useState(() => timeSince(conversation.started_at))

  useEffect(() => {
    if (conversation.ended_at) return
    const timer = setInterval(() => {
      setElapsed(timeSince(conversation.started_at))
    }, 1000)
    return () => clearInterval(timer)
  }, [conversation.started_at, conversation.ended_at])

  const channelIcon = channelIcons[conversation.channel] ?? '?'
  const stateClass = stateColors[conversation.state] ?? 'bg-gray-100 text-gray-700'
  const displayName = conversation.customer_name || 'Unknown'
  const phoneNumber = conversation.customer_identifier
  const isEnded = conversation.state === 'ended' || conversation.state === 'failed'

  return (
    <button
      onClick={onClick}
      className={cn(
        'flex w-full items-start gap-2.5 rounded-lg border p-2.5 text-left transition-all',
        selected
          ? 'border-blue-200 bg-blue-50/80 shadow-sm'
          : 'border-transparent hover:bg-gray-50 hover:border-gray-200',
        isEnded && !selected && 'opacity-60'
      )}
    >
      <span className="mt-0.5 text-base leading-none">{channelIcon}</span>

      <div className="flex flex-1 flex-col gap-1 overflow-hidden">
        <div className="flex items-center justify-between gap-1">
          <span className="truncate text-sm font-medium text-gray-900">{displayName}</span>
          <div className="flex items-center gap-1.5 shrink-0">
            <span className="text-[11px] font-mono tabular-nums text-gray-500">
              {isEnded
                ? formatDuration(conversation.duration_seconds)
                : formatDuration(elapsed)}
            </span>
            {conversation.direction === 'inbound' ? (
              <ArrowDownLeft className="size-3 text-green-600" />
            ) : (
              <ArrowUpRight className="size-3 text-blue-600" />
            )}
          </div>
        </div>

        <span className="text-[11px] font-mono text-gray-500 truncate">{phoneNumber}</span>

        <div className="flex items-center gap-1.5">
          <Badge variant="secondary" className={cn('h-4 text-[10px]', stateClass)}>
            {conversation.state.replace(/_/g, ' ')}
          </Badge>
          <span className="text-[10px] text-gray-400 capitalize">
            {conversation.current_handler_type}
          </span>
        </div>
      </div>
    </button>
  )
}
