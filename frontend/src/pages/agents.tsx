import { useState } from 'react'
import { AgentTable } from '@/components/agents/agent-table'
import { AgentForm } from '@/components/agents/agent-form'
import { AgentStats } from '@/components/agents/agent-stats'
import type { Agent } from '@/lib/types'

export function AgentsPage() {
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null)
  const [showForm, setShowForm] = useState(false)

  return (
    <div className="flex h-[calc(100vh-64px)] overflow-hidden bg-white">
      {/* Main area */}
      <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-6">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Agents</h1>
          <p className="text-sm text-gray-500 mt-0.5">Manage your agent workforce</p>
        </div>

        <AgentTable
          selectedId={selectedAgent?.id ?? null}
          onSelect={setSelectedAgent}
          onAddClick={() => setShowForm(true)}
        />
      </div>

      {/* Detail panel */}
      {selectedAgent && (
        <div className="w-72 shrink-0 overflow-y-auto border-l border-gray-100 bg-gray-50 p-4">
          <AgentStats agent={selectedAgent} />
        </div>
      )}

      <AgentForm
        open={showForm}
        onClose={() => setShowForm(false)}
      />
    </div>
  )
}
