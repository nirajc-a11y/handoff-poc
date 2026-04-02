import { useMessages } from '@/hooks/use-messages'
import { formatTime } from '@/lib/utils'
import { ScrollArea } from '@/components/ui/scroll-area'

interface TranscriptPanelProps {
  conversationId: string
}

export function TranscriptPanel({ conversationId }: TranscriptPanelProps) {
  const { data: messages = [] } = useMessages(conversationId)

  const transcriptions = messages.filter(
    (m) => (m.metadata as Record<string, unknown>)?.type === 'transcription'
  )

  if (transcriptions.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <p className="text-xs text-gray-400">No transcription available</p>
      </div>
    )
  }

  return (
    <ScrollArea className="flex-1">
      <div className="flex flex-col gap-1 p-4">
        {transcriptions.map((msg) => (
          <div key={msg.id} className="flex gap-2 font-mono text-xs">
            <span className="shrink-0 text-gray-400">{formatTime(msg.created_at)}</span>
            <span className="capitalize text-gray-500">[{msg.sender_type}]</span>
            <span className="text-gray-700">{msg.content}</span>
          </div>
        ))}
      </div>
    </ScrollArea>
  )
}
