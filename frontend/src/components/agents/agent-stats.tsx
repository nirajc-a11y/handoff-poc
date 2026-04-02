import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { formatDuration, cn, agentStatusColors } from '@/lib/utils'
import type { Agent } from '@/lib/types'
import { BarChart, Bar, XAxis, YAxis, ResponsiveContainer, Tooltip } from 'recharts'
import { Phone, Clock, Activity } from 'lucide-react'

interface AgentStatsData {
  calls_today: number
  avg_handle_time: number
  conversations_by_state: Record<string, number>
}

interface Props {
  agent: Agent
}

export function AgentStats({ agent }: Props) {
  const { data: stats, isLoading } = useQuery<AgentStatsData>({
    queryKey: ['agents', agent.id, 'stats'],
    queryFn: () => api.get(`/agents/${agent.id}/stats`),
    retry: false,
  })

  const statusColor = agentStatusColors[agent.status.status] ?? 'bg-gray-400'

  const stateChartData = stats?.conversations_by_state
    ? Object.entries(stats.conversations_by_state).map(([state, count]) => ({
        state: state.replace('_', ' '),
        count,
      }))
    : []

  return (
    <div className="flex flex-col gap-3">
      {/* Agent header */}
      <Card>
        <CardContent className="flex items-center gap-3 py-4">
          <div className="relative">
            <div className="flex size-12 items-center justify-center rounded-full bg-indigo-100 text-indigo-700 text-lg font-semibold">
              {(agent.name || 'A').charAt(0).toUpperCase()}
            </div>
            <div className={cn('absolute -bottom-0.5 -right-0.5 size-3 rounded-full border-2 border-white', statusColor)} />
          </div>
          <div>
            <p className="font-semibold text-gray-900">{agent.name}</p>
            <p className="text-xs text-gray-500">{agent.email}</p>
            <p className="text-xs text-gray-400 mt-0.5 capitalize">
              {agent.status.status.replace('_', ' ')} — {agent.team ?? 'No team'}
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Skills */}
      {agent.skills.length > 0 && (
        <div className="flex flex-wrap gap-1.5 px-1">
          {agent.skills.map(skill => (
            <span key={skill} className="rounded-md bg-indigo-50 px-2 py-0.5 text-xs text-indigo-700 border border-indigo-100">
              {skill}
            </span>
          ))}
        </div>
      )}

      {/* Stats */}
      {isLoading ? (
        <p className="py-4 text-center text-sm text-gray-400">Loading stats…</p>
      ) : !stats ? (
        <p className="py-4 text-center text-xs text-gray-400">Stats unavailable</p>
      ) : (
        <>
          <div className="grid grid-cols-3 gap-2">
            <Card>
              <CardContent className="flex flex-col items-center gap-1 py-4">
                <Phone size={16} className="text-indigo-500" />
                <p className="text-xl font-semibold text-gray-900">{stats.calls_today}</p>
                <p className="text-xs text-gray-500">Today</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="flex flex-col items-center gap-1 py-4">
                <Clock size={16} className="text-emerald-500" />
                <p className="text-xl font-semibold text-gray-900">{formatDuration(stats.avg_handle_time)}</p>
                <p className="text-xs text-gray-500">Avg AHT</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="flex flex-col items-center gap-1 py-4">
                <Activity size={16} className="text-amber-500" />
                <p className="text-xl font-semibold text-gray-900">{agent.status.current_conversations}</p>
                <p className="text-xs text-gray-500">Active</p>
              </CardContent>
            </Card>
          </div>

          {stateChartData.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Conversations by State</CardTitle>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={120}>
                  <BarChart data={stateChartData} margin={{ top: 0, right: 4, bottom: 0, left: -20 }}>
                    <XAxis dataKey="state" tick={{ fontSize: 10, fill: '#9ca3af' }} tickLine={false} axisLine={false} />
                    <YAxis tick={{ fontSize: 10, fill: '#9ca3af' }} tickLine={false} axisLine={false} />
                    <Tooltip contentStyle={{ fontSize: 11, borderRadius: 8, border: '1px solid #e5e7eb' }} />
                    <Bar dataKey="count" fill="#6366f1" radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  )
}
