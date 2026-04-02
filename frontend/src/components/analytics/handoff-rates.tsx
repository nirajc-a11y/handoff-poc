import { PieChart, Pie, Cell, Tooltip, Legend, ResponsiveContainer } from 'recharts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

const HANDOFF_DATA = [
  { name: 'AI → Human', value: 45 },
  { name: 'IVR → AI', value: 30 },
  { name: 'Transfer', value: 25 },
]

const COLORS = ['#6366f1', '#10b981', '#f59e0b']

export function HandoffRates() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Handoff Types</CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={200}>
          <PieChart>
            <Pie
              data={HANDOFF_DATA}
              cx="50%"
              cy="45%"
              outerRadius={80}
              paddingAngle={3}
              dataKey="value"
              label={({ value }) => `${value}%`}
              labelLine={false}
            >
              {HANDOFF_DATA.map((_, index) => (
                <Cell key={index} fill={COLORS[index % COLORS.length]} />
              ))}
            </Pie>
            <Tooltip
              formatter={(v) => [`${v}%`, 'Share']}
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
