import { useMemo } from 'react'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import { useConversations } from '@/hooks/use-conversations'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

function buildHourlyData(conversations: { started_at: string }[]) {
  const now = new Date()
  const buckets: Record<number, number> = {}

  // Initialize last 12 hours
  for (let i = 11; i >= 0; i--) {
    const h = new Date(now.getTime() - i * 60 * 60 * 1000)
    buckets[h.getHours()] = 0
  }

  for (const c of conversations) {
    const h = new Date(c.started_at).getHours()
    if (h in buckets) {
      buckets[h] = (buckets[h] ?? 0) + 1
    }
  }

  return Object.entries(buckets).map(([hour, count]) => ({
    hour: `${String(hour).padStart(2, '0')}:00`,
    calls: count,
  }))
}

// Mock data for when there are no conversations
const MOCK_DATA = [
  { hour: '08:00', calls: 12 },
  { hour: '09:00', calls: 28 },
  { hour: '10:00', calls: 45 },
  { hour: '11:00', calls: 38 },
  { hour: '12:00', calls: 22 },
  { hour: '13:00', calls: 31 },
  { hour: '14:00', calls: 52 },
  { hour: '15:00', calls: 47 },
  { hour: '16:00', calls: 35 },
  { hour: '17:00', calls: 19 },
  { hour: '18:00', calls: 8 },
  { hour: '19:00', calls: 4 },
]

export function CallsChart() {
  const { data: conversations = [] } = useConversations()

  const chartData = useMemo(() => {
    if (conversations.length === 0) return MOCK_DATA
    return buildHourlyData(conversations)
  }, [conversations])

  return (
    <Card>
      <CardHeader>
        <CardTitle>Call Volume</CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={chartData} margin={{ top: 4, right: 8, bottom: 0, left: -16 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis
              dataKey="hour"
              tick={{ fontSize: 11, fill: '#9ca3af' }}
              tickLine={false}
              axisLine={false}
            />
            <YAxis
              tick={{ fontSize: 11, fill: '#9ca3af' }}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip
              contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e5e7eb' }}
            />
            <Bar dataKey="calls" fill="#6366f1" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  )
}
