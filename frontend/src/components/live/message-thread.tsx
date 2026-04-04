import { useEffect, useRef } from 'react'
import { useMessages } from '@/hooks/use-messages'
import { cn, formatTime } from '@/lib/utils'
import { MessageThreadSkeleton } from './message-thread-skeleton'

interface MessageThreadProps {
  conversationId: string
  /** Hide system audio messages (e.g. full-call recording already shown in header) */
  hideRecordings?: boolean
}

export function MessageThread({ conversationId, hideRecordings }: MessageThreadProps) {
  const { data: raw = [], isLoading } = useMessages(conversationId)
  const messages = hideRecordings
    ? raw.filter((m) => !(m.content_type === 'audio' && (m.sender_type === 'system' || m.sender_type === 'ivr')))
    : raw
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    // Scroll only the closest scrollable parent, not the whole page
    const el = bottomRef.current?.closest('[data-scroll-container]') as HTMLElement | null
    if (el) el.scrollTop = el.scrollHeight
  }, [messages.length])

  if (isLoading) {
    return <MessageThreadSkeleton count={4} />
  }

  if (messages.length === 0) {
    return (
      <div className="flex h-32 items-center justify-center">
        <p className="text-xs text-gray-400">No messages yet</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-3 px-4 py-3">
      {messages.map((msg) => {
        const isCustomer = msg.sender_type === 'customer'
        const isAi = msg.sender_type === 'ai'
        const isSystem = msg.sender_type === 'system' || msg.sender_type === 'ivr'

        if (isSystem) {
          return (
            <div key={msg.id} className="flex flex-col items-center gap-0.5">
              <span className="text-[10px] text-gray-400">{formatTime(msg.created_at)}</span>
              <div className="max-w-[80%] rounded-md bg-amber-50 px-3 py-1.5 text-center text-xs text-amber-700">
                <span className="text-[10px] font-medium uppercase text-amber-500">
                  {msg.sender_type}
                </span>
                {msg.content_type === 'audio' && msg.content ? (
                  <audio controls src={msg.content} className="mt-1 h-8 max-w-full" />
                ) : (
                  <p className="mt-0.5">{msg.content}</p>
                )}
              </div>
            </div>
          )
        }

        const align = isCustomer ? 'items-start' : 'items-end'
        const bubbleBg = isCustomer
          ? 'bg-gray-100 text-gray-900'
          : isAi
            ? 'bg-violet-100 text-violet-900'
            : 'bg-blue-100 text-blue-900'

        return (
          <div key={msg.id} className={cn('flex flex-col gap-0.5', align)}>
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] font-medium capitalize text-gray-500">
                {msg.sender_type}
              </span>
              <span className="text-[10px] text-gray-400">{formatTime(msg.created_at)}</span>
            </div>
            <div className={cn('max-w-[75%] rounded-lg px-3 py-2 text-sm', bubbleBg)}>
              {msg.content_type === 'audio' && msg.content ? (
                <audio controls src={msg.content} className="h-8 max-w-full" />
              ) : (
                <p className="whitespace-pre-wrap">{msg.content}</p>
              )}
            </div>
          </div>
        )
      })}
      <div ref={bottomRef} />
    </div>
  )
}
