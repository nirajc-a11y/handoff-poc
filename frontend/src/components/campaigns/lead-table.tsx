import { useCampaignLeads } from '@/hooks/use-campaigns'
import { useAgents } from '@/hooks/use-agents'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import type { Campaign } from '@/lib/types'

interface Props {
  campaign: Campaign
}

const statusColor: Record<string, string> = {
  pending: 'bg-gray-100 text-gray-600',
  assigned: 'bg-blue-100 text-blue-700',
  in_progress: 'bg-yellow-100 text-yellow-700',
  completed: 'bg-green-100 text-green-700',
  failed: 'bg-red-100 text-red-700',
  skipped: 'bg-gray-100 text-gray-400',
}

export function LeadTable({ campaign }: Props) {
  const { data: leads = [], isLoading } = useCampaignLeads(campaign.id)
  const { data: agents = [] } = useAgents()

  const agentMap = Object.fromEntries(agents.map(a => [a.id, a.name]))

  return (
    <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
        <h2 className="text-sm font-medium text-gray-900">
          Leads — <span className="text-gray-500">{campaign.name}</span>
        </h2>
        <span className="text-xs text-gray-400">{leads.length} leads</span>
      </div>

      {isLoading ? (
        <p className="py-8 text-center text-sm text-gray-400">Loading…</p>
      ) : leads.length === 0 ? (
        <p className="py-8 text-center text-sm text-gray-400">No leads in this campaign</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Lead ID</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Assigned Agent</TableHead>
              <TableHead>Attempts</TableHead>
              <TableHead>Disposition</TableHead>
              <TableHead>Notes</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {leads.map((lead) => (
              <TableRow key={lead.id}>
                <TableCell className="font-mono text-xs text-gray-500">
                  {lead.lead_id.slice(0, 8)}…
                </TableCell>
                <TableCell>
                  <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${statusColor[lead.status] ?? 'bg-gray-100 text-gray-600'}`}>
                    {lead.status}
                  </span>
                </TableCell>
                <TableCell className="text-gray-600">
                  {lead.assigned_agent_id ? (agentMap[lead.assigned_agent_id] ?? lead.assigned_agent_id.slice(0, 8) + '…') : '—'}
                </TableCell>
                <TableCell className="text-gray-500">{lead.attempt_count}</TableCell>
                <TableCell className="text-gray-500">{lead.disposition ?? '—'}</TableCell>
                <TableCell className="max-w-xs truncate text-gray-400">{lead.notes ?? '—'}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  )
}
