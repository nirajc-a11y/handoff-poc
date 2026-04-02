import { useActiveConversations } from '@/hooks/use-conversations'
import { useQueueStats } from '@/hooks/use-queue-stats'
import { useAgents } from '@/hooks/use-agents'
import { useCampaigns } from '@/hooks/use-campaigns'
import { Card, CardContent } from '@/components/ui/card'
import { PhoneCall, Clock, UserCheck, Target } from 'lucide-react'
import { formatDuration } from '@/lib/utils'

interface MetricCardProps {
  label: string
  value: string | number
  icon: React.ReactNode
  sub?: string
}

function MetricCard({ label, value, icon, sub }: MetricCardProps) {
  return (
    <Card className="flex-1 min-w-0">
      <CardContent className="flex items-center gap-3 py-4">
        <div className="flex size-10 items-center justify-center rounded-md bg-muted text-muted-foreground shrink-0">
          {icon}
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-xs text-gray-500 truncate">{label}</p>
          <p className="text-2xl font-semibold text-gray-900 leading-tight">{value}</p>
          {sub && <p className="text-xs text-gray-400 mt-0.5 truncate">{sub}</p>}
        </div>
      </CardContent>
    </Card>
  )
}

export function MetricsRow() {
  const { data: activeCalls = [] } = useActiveConversations()
  const { data: queueStats } = useQueueStats()
  const { data: agents = [] } = useAgents()
  const { data: campaigns = [] } = useCampaigns()

  const queueDepth = queueStats?.queue_depth ?? 0
  const avgWaitSecs = queueStats?.avg_wait_seconds ?? 0
  const agentsOnline = agents.filter(a => a.status.status !== 'offline').length
  const activeCampaigns = campaigns.filter(c => c.status === 'active').length

  return (
    <div className="flex gap-4">
      <MetricCard
        label="Active Calls"
        value={activeCalls.length}
        icon={<PhoneCall size={18} />}
        sub="right now"
      />
      <MetricCard
        label="Queue Depth"
        value={queueDepth}
        icon={<Clock size={18} />}
        sub="waiting"
      />
      <MetricCard
        label="Avg Wait"
        value={formatDuration(avgWaitSecs)}
        icon={<Clock size={18} />}
        sub="seconds"
      />
      <MetricCard
        label="Agents Online"
        value={`${agentsOnline} / ${agents.length}`}
        icon={<UserCheck size={18} />}
        sub="of total"
      />
      <MetricCard
        label="Active Campaigns"
        value={activeCampaigns}
        icon={<Target size={18} />}
        sub={`of ${campaigns.length} total`}
      />
    </div>
  )
}
