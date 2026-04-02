import { useMessages } from '@/hooks/use-messages'
import { formatTime } from '@/lib/utils'
import { ScrollArea } from '@/components/ui/scroll-area'

interface TranscriptPanelProps {
  conversationId: string
}

export function TranscriptPanel({ conversationId }: TranscriptPanelProps) {
  const { data: messages = [] } = useMessages(conversationId)

  const transcript = messages.filter((m) => m.content_type === 'text')

  if (transcript.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <p className="text-xs text-gray-400">No transcript available</p>
      </div>
    )
  }

  return (
    <ScrollArea className="flex-1">
      <div className="flex flex-col gap-2 p-4">
        {transcript.map((msg) => {
          const isCustomer = msg.sender_type === 'customer'
          const isAi = msg.sender_type === 'ai'
          const isAgent = msg.sender_type === 'agent'

          const badgeClass = isCustomer
            ? 'bg-gray-100 text-gray-600'
            : isAi
              ? 'bg-violet-100 text-violet-700'
              : isAgent
                ? 'bg-blue-100 text-blue-700'
                : 'bg-gray-100 text-gray-500'

          const rowAlign = isCustomer ? 'items-start' : 'items-end'

          return (
            <div key={msg.id} className={`flex flex-col gap-0.5 ${rowAlign}`}>
              <div className="flex items-center gap-1.5">
                <span className="text-[10px] text-gray-400 font-mono">
                  {formatTime(msg.created_at)}
                </span>
                <span
                  className={`rounded px-1.5 py-0.5 text-[10px] font-medium capitalize ${badgeClass}`}
                >
                  {msg.sender_type}
                </span>
              </div>
              <p
                className={`max-w-[85%] font-mono text-xs leading-relaxed text-gray-800 ${
                  isCustomer ? 'text-left' : 'text-right'
                }`}
              >
                {msg.content}
              </p>
            </div>
          )
        })}
      </div>
    </ScrollArea>
  )
}
