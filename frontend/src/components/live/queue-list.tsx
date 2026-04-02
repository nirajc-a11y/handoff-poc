import { useHandoffQueue } from '@/hooks/use-handoffs'
import { channelIcons, timeSince, formatDuration } from '@/lib/utils'
import { useSetAtom } from 'jotai'
import { selectedConvIdAtom } from '@/stores/ui'
import { Clock } from 'lucide-react'

export function QueueList() {
  const { data: queued = [], isLoading } = useHandoffQueue()
  const setSelected = useSetAtom(selectedConvIdAtom)

  if (isLoading) {
    return <p className="py-4 text-center text-xs text-gray-400">Loading…</p>
  }

  if (queued.length === 0) {
    return <p className="py-4 text-center text-xs text-gray-400">Queue is empty</p>
  }

  return (
    <div className="flex flex-col gap-1.5">
      {queued.map((conv) => {
        const waitSeconds = conv.queue_entered_at ? timeSince(conv.queue_entered_at) : 0
        return (
          <button
            key={conv.id}
            onClick={() => setSelected(conv.id)}
            className="flex items-center gap-2 rounded-lg border bg-white px-2.5 py-2 text-left transition-colors hover:bg-gray-50"
          >
            <span className="text-sm">{channelIcons[conv.channel] ?? '?'}</span>
            <div className="flex-1 min-w-0">
              <p className="text-xs font-medium text-gray-900 truncate">
                {conv.customer_name || conv.customer_identifier}
              </p>
              {conv.required_skills && conv.required_skills.length > 0 && (
                <p className="text-[10px] text-gray-400 truncate">
                  {conv.required_skills.join(', ')}
                </p>
              )}
            </div>
            <div className="flex items-center gap-1 text-[10px] text-gray-500 shrink-0">
              <Clock className="size-3" />
              <span className="font-mono tabular-nums">{formatDuration(waitSeconds)}</span>
            </div>
          </button>
        )
      })}
    </div>
  )
}
