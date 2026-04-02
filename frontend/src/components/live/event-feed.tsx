import { useAtom } from 'jotai'
import { wsEventsAtom } from '@/stores/ws'
import { formatTime } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Trash2 } from 'lucide-react'

const eventTypeColors: Record<string, string> = {
  'conversation.created': 'bg-blue-100 text-blue-700',
  'conversation.state_changed': 'bg-yellow-100 text-yellow-700',
  'conversation.ended': 'bg-gray-100 text-gray-600',
  'handoff.escalated': 'bg-orange-100 text-orange-700',
  'handoff.transferred': 'bg-indigo-100 text-indigo-700',
  'agent.status_changed': 'bg-green-100 text-green-700',
  'queue.updated': 'bg-purple-100 text-purple-700',
  'campaign.lead_dialed': 'bg-teal-100 text-teal-700',
}

export function EventFeed() {
  const [events, setEvents] = useAtom(wsEventsAtom)
  const displayed = events.slice(0, 50)

  return (
    <div className="flex flex-col gap-2">
      {events.length > 0 && (
        <div className="flex justify-end">
          <Button
            variant="ghost"
            size="xs"
            className="text-gray-400"
            onClick={() => setEvents([])}
          >
            <Trash2 className="size-3" />
            Clear
          </Button>
        </div>
      )}

      {displayed.length === 0 ? (
        <p className="py-4 text-center text-xs text-gray-400">Waiting for events...</p>
      ) : (
        <ScrollArea className="max-h-48">
          <div className="flex flex-col gap-1">
            {displayed.map((event) => {
              const colorClass = eventTypeColors[event.type] ?? 'bg-gray-100 text-gray-600'
              const data = event.data as Record<string, unknown>
              const from = data?.from_handler_type as string | undefined
              const to = data?.to_handler_type as string | undefined

              return (
                <div
                  key={event.event_id}
                  className="flex flex-col gap-0.5 rounded-md border border-gray-50 bg-gray-50 p-1.5"
                >
                  <div className="flex items-center gap-1.5">
                    <span className="text-[9px] tabular-nums text-gray-400">
                      {formatTime(event.timestamp)}
                    </span>
                    <Badge variant="secondary" className={`h-3.5 text-[9px] ${colorClass}`}>
                      {event.type.split('.').pop()}
                    </Badge>
                  </div>
                  {from && to && (
                    <span className="text-[10px] text-gray-500">
                      {from} → {to}
                    </span>
                  )}
                </div>
              )
            })}
          </div>
        </ScrollArea>
      )}
    </div>
  )
}
