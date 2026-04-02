import { useMemo } from 'react'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import { useConversations } from '@/hooks/use-conversations'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { formatDuration } from '@/lib/utils'

const MOCK_DATA = [
  { label: '08:00', avg: 185 },
  { label: '09:00', avg: 210 },
  { label: '10:00', avg: 175 },
  { label: '11:00', avg: 230 },
  { label: '12:00', avg: 195 },
  { label: '13:00', avg: 160 },
  { label: '14:00', avg: 220 },
  { label: '15:00', avg: 240 },
  { label: '16:00', avg: 205 },
  { label: '17:00', avg: 180 },
  { label: '18:00', avg: 155 },
  { label: '19:00', avg: 190 },
]

export function HandleTimeChart() {
  const { data: conversations = [] } = useConversations({ state: 'ended' })

  const chartData = useMemo(() => {
    const ended = conversations.filter(
      c => c.state === 'ended' && c.duration_seconds != null
    )
    if (ended.length === 0) return MOCK_DATA

    const now = new Date()
    const buckets: Record<number, number[]> = {}

    for (let i = 11; i >= 0; i--) {
      const h = new Date(now.getTime() - i * 60 * 60 * 1000).getHours()
      buckets[h] = []
    }

    for (const c of ended) {
      const h = new Date(c.started_at).getHours()
      if (h in buckets && c.duration_seconds != null) {
        buckets[h].push(c.duration_seconds)
      }
    }

    return Object.entries(buckets).map(([hour, durations]) => ({
      label: `${String(hour).padStart(2, '0')}:00`,
      avg:
        durations.length > 0
          ? Math.round(durations.reduce((s, d) => s + d, 0) / durations.length)
          : 0,
    }))
  }, [conversations])

  return (
    <Card>
      <CardHeader>
        <CardTitle>Avg Handle Time</CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={chartData} margin={{ top: 4, right: 8, bottom: 0, left: -16 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis
              dataKey="label"
              tick={{ fontSize: 11, fill: '#9ca3af' }}
              tickLine={false}
              axisLine={false}
            />
            <YAxis
              tick={{ fontSize: 11, fill: '#9ca3af' }}
              tickLine={false}
              axisLine={false}
              tickFormatter={(v) => formatDuration(v)}
            />
            <Tooltip
              formatter={(v) => [formatDuration(typeof v === 'number' ? v : 0), 'Avg Handle Time']}
              contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e5e7eb' }}
            />
            <Line
              type="monotone"
              dataKey="avg"
              stroke="#10b981"
              strokeWidth={2}
              dot={{ r: 3, fill: '#10b981' }}
              activeDot={{ r: 5 }}
            />
          </LineChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  )
}
