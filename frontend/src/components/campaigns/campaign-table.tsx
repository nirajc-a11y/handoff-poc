import { useState } from 'react'
import { useCampaigns, useDeleteCampaign } from '@/hooks/use-campaigns'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from '@/components/ui/dialog'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { toast } from 'sonner'
import type { Campaign } from '@/lib/types'
import { Plus, Trash2 } from 'lucide-react'

interface Props {
  selectedId: string | null
  onSelect: (campaign: Campaign) => void
  onCreateClick: () => void
}

const statusColor: Record<string, string> = {
  draft: 'bg-gray-100 text-gray-600',
  active: 'bg-green-100 text-green-700',
  paused: 'bg-yellow-100 text-yellow-700',
  completed: 'bg-blue-100 text-blue-600',
}

const typeLabel: Record<string, string> = {
  outbound_call: 'Voice',
  outbound_sms: 'SMS',
  outbound_whatsapp: 'WhatsApp',
  outbound_email: 'Email',
}

function formatDate(d: string | null) {
  if (!d) return '—'
  return new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

export function CampaignTable({ selectedId, onSelect, onCreateClick }: Props) {
  const { data: campaigns = [], isLoading } = useCampaigns()
  const deleteCampaign = useDeleteCampaign()
  const [deleteTarget, setDeleteTarget] = useState<Campaign | null>(null)

  const handleDelete = async () => {
    if (!deleteTarget) return
    try {
      await deleteCampaign.mutateAsync(deleteTarget.id)
      toast.success(`Campaign "${deleteTarget.name}" deleted`)
      if (selectedId === deleteTarget.id) onSelect(null as unknown as Campaign)
      setDeleteTarget(null)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to delete campaign')
    }
  }

  return (
    <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
        <h2 className="text-sm font-medium text-gray-900">Campaigns</h2>
        <Button size="sm" onClick={onCreateClick}>
          <Plus size={14} />
          Create Campaign
        </Button>
      </div>

      {isLoading ? (
        <p className="py-10 text-center text-sm text-gray-400">Loading…</p>
      ) : campaigns.length === 0 ? (
        <p className="py-10 text-center text-sm text-gray-400">No campaigns yet</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Start Date</TableHead>
              <TableHead>End Date</TableHead>
              <TableHead>Created</TableHead>
              <TableHead className="w-16"></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {campaigns.map((c) => (
              <TableRow
                key={c.id}
                className={`cursor-pointer ${selectedId === c.id ? 'bg-indigo-50' : ''}`}
                onClick={() => onSelect(c)}
              >
                <TableCell className="font-medium text-gray-900">{c.name}</TableCell>
                <TableCell>
                  <span className="rounded-md bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
                    {typeLabel[c.type] ?? c.type}
                  </span>
                </TableCell>
                <TableCell>
                  <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${statusColor[c.status] ?? 'bg-gray-100 text-gray-600'}`}>
                    {c.status}
                  </span>
                </TableCell>
                <TableCell className="text-gray-500">{formatDate(c.start_date)}</TableCell>
                <TableCell className="text-gray-500">{formatDate(c.end_date)}</TableCell>
                <TableCell className="text-gray-400">{formatDate(c.created_at)}</TableCell>
                <TableCell>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    className="text-red-500 hover:text-red-700"
                    onClick={(e) => { e.stopPropagation(); setDeleteTarget(c) }}
                  >
                    <Trash2 className="size-3.5" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      <Dialog open={!!deleteTarget} onOpenChange={(o) => { if (!o) setDeleteTarget(null) }}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Delete Campaign</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-gray-600">
            Delete &quot;{deleteTarget?.name}&quot;? This action cannot be undone.
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>Cancel</Button>
            <Button variant="destructive" onClick={handleDelete} disabled={deleteCampaign.isPending}>
              {deleteCampaign.isPending ? 'Deleting…' : 'Delete'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
