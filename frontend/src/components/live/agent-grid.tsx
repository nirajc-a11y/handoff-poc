import { useAgents } from '@/hooks/use-agents'
import { cn, agentStatusColors } from '@/lib/utils'

export function AgentGrid() {
  const { data: agents = [] } = useAgents()

  if (agents.length === 0) {
    return <p className="py-4 text-center text-xs text-gray-400">No agents</p>
  }

  return (
    <div className="grid grid-cols-2 gap-1.5">
      {agents.map((agent) => {
        const initial = (agent.name || 'A').charAt(0).toUpperCase()
        const statusColor = agentStatusColors[agent.status.status] ?? 'bg-gray-400'

        return (
          <div
            key={agent.id}
            className="flex items-center gap-2 rounded-md border border-gray-100 bg-gray-50 p-2"
          >
            <div className="relative">
              <div className="flex size-7 items-center justify-center rounded-full bg-gray-200 text-xs font-medium text-gray-600">
                {initial}
              </div>
              <div
                className={cn(
                  'absolute -bottom-0.5 -right-0.5 size-2.5 rounded-full border-2 border-white',
                  statusColor
                )}
              />
            </div>
            <div className="flex flex-col overflow-hidden">
              <span className="truncate text-[11px] font-medium text-gray-800">
                {agent.name}
              </span>
              <span className="text-[10px] text-gray-400">
                {agent.status.current_conversations} conv
              </span>
            </div>
          </div>
        )
      })}
    </div>
  )
}
