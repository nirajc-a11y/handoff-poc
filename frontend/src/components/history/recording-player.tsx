import { Headphones } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { formatTime } from '@/lib/utils'
import type { Message } from '@/lib/types'

interface RecordingPlayerProps {
  messages: Message[]
}

export function RecordingPlayer({ messages }: RecordingPlayerProps) {
  const recordings = messages.filter((m) => m.content_type === 'audio' && m.content)

  if (recordings.length === 0) {
    return (
      <Card size="sm">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm">
            <Headphones className="size-4" />
            Recordings
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-xs text-muted-foreground">No recordings available</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm">
          <Headphones className="size-4" />
          Recordings ({recordings.length})
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex flex-col gap-3">
          {recordings.map((msg) => {
            const duration =
              typeof msg.metadata?.duration === 'number'
                ? msg.metadata.duration as number
                : null

            return (
              <div
                key={msg.id}
                className="flex flex-col gap-1.5 rounded-lg border bg-muted/30 p-3"
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs text-muted-foreground">
                    {formatTime(msg.created_at)}
                  </span>
                  {duration != null && (
                    <span className="text-xs text-muted-foreground">
                      {Math.floor(duration / 60)}:{String(duration % 60).padStart(2, '0')}
                    </span>
                  )}
                </div>
                <audio
                  controls
                  src={msg.content!}
                  className="w-full h-8"
                  style={{ height: 32 }}
                />
              </div>
            )
          })}
        </div>
      </CardContent>
    </Card>
  )
}
