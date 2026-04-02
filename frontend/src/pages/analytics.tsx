import { MetricsRow } from '@/components/analytics/metrics-row'
import { CallsChart } from '@/components/analytics/calls-chart'
import { HandleTimeChart } from '@/components/analytics/handle-time-chart'
import { AgentUtilChart } from '@/components/analytics/agent-util-chart'
import { HandoffRates } from '@/components/analytics/handoff-rates'

export function AnalyticsPage() {
  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto bg-background p-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-900">Analytics</h1>
        <p className="text-sm text-gray-500 mt-0.5">Real-time platform overview</p>
      </div>

      <MetricsRow />

      <div className="grid grid-cols-2 gap-4 flex-1">
        <CallsChart />
        <HandleTimeChart />
        <AgentUtilChart />
        <HandoffRates />
      </div>
    </div>
  )
}
