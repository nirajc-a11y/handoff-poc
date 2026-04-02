import { useMemo } from 'react'
import { PieChart, Pie, Cell, Tooltip, Legend, ResponsiveContainer } from 'recharts'
import { useAgents } from '@/hooks/use-agents'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

const COLORS = ['#6366f1', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4', '#ec4899']

const MOCK_DATA = [
  { name: 'Alice M.', value: 80 },
  { name: 'Bob K.', value: 50 },
  { name: 'Carol P.', value: 100 },
  { name: 'Dan W.', value: 25 },
]

export function AgentUtilChart() {
  const { data: agents = [] } = useAgents()

  const chartData = useMemo(() => {
    if (agents.length === 0) return MOCK_DATA
    return agents
      .filter(a => a.status.status !== 'offline')
      .map(a => ({
        name: a.name,
        value: a.max_concurrent > 0
          ? Math.round((a.status.current_conversations / a.max_concurrent) * 100)
          : 0,
      }))
  }, [agents])

  return (
    <Card>
      <CardHeader>
        <CardTitle>Agent Utilization</CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={200}>
          <PieChart>
            <Pie
              data={chartData}
              cx="50%"
              cy="45%"
              innerRadius={50}
              outerRadius={80}
              paddingAngle={3}
              dataKey="value"
            >
              {chartData.map((_, index) => (
                <Cell key={index} fill={COLORS[index % COLORS.length]} />
              ))}
            </Pie>
            <Tooltip
              formatter={(v) => [`${v}%`, 'Utilization']}
              contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e5e7eb' }}
            />
            <Legend
              formatter={(value) => <span style={{ fontSize: 11, color: '#6b7280' }}>{value}</span>}
            />
          </PieChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  )
}
