import { useState } from 'react'
import { Users, Clock, Target, Activity } from 'lucide-react'
import { useAgents } from '@/hooks/use-agents'
import { useQueueStats } from '@/hooks/use-queue-stats'
import { useCampaigns } from '@/hooks/use-campaigns'
import { formatDuration } from '@/lib/utils'
import { Separator } from '@/components/ui/separator'
import { EventFeed } from './event-feed'

export function LiveStatusBar() {
  const { data: agents = [] } = useAgents()
  const { data: queueStats } = useQueueStats()
  const { data: campaigns = [] } = useCampaigns()
  const [showEvents, setShowEvents] = useState(false)

  const online = agents.filter(a => a.status.status !== 'offline').length
  const activeCampaign = campaigns.find(c => c.status === 'active')

  return (
    <div className="relative shrink-0">
      <div className="flex items-center gap-4 border-b border-border bg-card px-4 py-1.5 text-xs text-muted-foreground">
        <div className="flex items-center gap-1.5">
          <Users className="size-3.5" />
          <span className="font-medium text-foreground">{online}</span>
          <span>/ {agents.length} agents</span>
        </div>

        <Separator orientation="vertical" className="h-3.5" />

        <div className="flex items-center gap-1.5">
          <Clock className="size-3.5" />
          <span className="font-medium text-foreground">{queueStats?.queue_depth ?? 0}</span>
          <span>queued</span>
          {(queueStats?.avg_wait_seconds ?? 0) > 0 && (
            <span className="text-muted-foreground/60">
              avg {formatDuration(Math.round(queueStats?.avg_wait_seconds ?? 0))}
            </span>
          )}
        </div>

        <Separator orientation="vertical" className="h-3.5" />

        <div className="flex items-center gap-1.5">
          <Target className="size-3.5" />
          {activeCampaign ? (
            <span className="truncate max-w-32">{activeCampaign.name}</span>
          ) : (
            <span>No active campaign</span>
          )}
        </div>

        <div className="flex-1" />

        <button
          onClick={() => setShowEvents(s => !s)}
          className={`flex items-center gap-1 transition-colors ${showEvents ? 'text-foreground' : 'hover:text-foreground'}`}
        >
          <Activity className="size-3.5" />
          Events
        </button>
      </div>

      {showEvents && (
        <div className="absolute right-0 top-full z-40 w-80 border border-border bg-card shadow-lg rounded-sm">
          <div className="p-3">
            <EventFeed />
          </div>
        </div>
      )}
    </div>
  )
}
