import { useAgents } from '@/hooks/use-agents'
import { Button } from '@/components/ui/button'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { cn, agentStatusColors } from '@/lib/utils'
import type { Agent } from '@/lib/types'
import { UserPlus } from 'lucide-react'

interface Props {
  selectedId: string | null
  onSelect: (agent: Agent) => void
  onAddClick: () => void
}

export function AgentTable({ selectedId, onSelect, onAddClick }: Props) {
  const { data: agents = [], isLoading } = useAgents()

  return (
    <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
        <h2 className="text-sm font-medium text-gray-900">Agents</h2>
        <Button size="sm" onClick={onAddClick}>
          <UserPlus size={14} />
          Add Agent
        </Button>
      </div>

      {isLoading ? (
        <p className="py-10 text-center text-sm text-gray-400">Loading…</p>
      ) : agents.length === 0 ? (
        <p className="py-10 text-center text-sm text-gray-400">No agents found</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Email</TableHead>
              <TableHead>Team</TableHead>
              <TableHead>Skills</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Active Convs.</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {agents.map((agent) => {
              const statusColor = agentStatusColors[agent.status.status] ?? 'bg-gray-400'
              return (
                <TableRow
                  key={agent.id}
                  className={`cursor-pointer ${selectedId === agent.id ? 'bg-indigo-50' : ''}`}
                  onClick={() => onSelect(agent)}
                >
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <div className="flex size-7 items-center justify-center rounded-full bg-gray-200 text-xs font-medium text-gray-600 shrink-0">
                        {(agent.name || 'A').charAt(0).toUpperCase()}
                      </div>
                      <span className="font-medium text-gray-900">{agent.name}</span>
                    </div>
                  </TableCell>
                  <TableCell className="text-gray-500">{agent.email}</TableCell>
                  <TableCell className="text-gray-500">{agent.team ?? '—'}</TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {agent.skills.length === 0 ? (
                        <span className="text-gray-400 text-xs">—</span>
                      ) : (
                        agent.skills.map(skill => (
                          <span
                            key={skill}
                            className="rounded-md bg-indigo-50 px-1.5 py-0.5 text-xs text-indigo-700"
                          >
                            {skill}
                          </span>
                        ))
                      )}
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-1.5">
                      <div className={cn('size-2 rounded-full', statusColor)} />
                      <span className="text-xs text-gray-600 capitalize">
                        {agent.status.status.replace('_', ' ')}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell className="text-gray-500">
                    {agent.status.current_conversations} / {agent.max_concurrent}
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      )}
    </div>
  )
}
