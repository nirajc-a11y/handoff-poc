import { useState } from 'react'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { useAgents } from '@/hooks/use-agents'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from '@/components/ui/dialog'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import type { Campaign } from '@/lib/types'

interface Props {
  campaign: Campaign
  open: boolean
  onClose: () => void
}

export function AssignDialog({ campaign, open, onClose }: Props) {
  const { data: agents = [] } = useAgents()
  const [agentId, setAgentId] = useState('')
  const [count, setCount] = useState(10)
  const [loading, setLoading] = useState(false)

  const availableAgents = agents.filter(a => a.status.status !== 'offline')

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!agentId) {
      toast.error('Select an agent')
      return
    }
    setLoading(true)
    try {
      await api.post(`/campaigns/${campaign.id}/assign`, {
        agent_id: agentId,
        count,
      })
      toast.success(`Assigned ${count} leads to agent`)
      onClose()
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>Assign Leads — {campaign.name}</DialogTitle>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-gray-700">Agent</label>
            <Select value={agentId} onValueChange={(v) => setAgentId(v ?? '')}>
              <SelectTrigger className="w-full">
                <SelectValue placeholder="Select agent…" />
              </SelectTrigger>
              <SelectContent>
                {availableAgents.length === 0 && (
                  <SelectItem value="__none__" disabled>No available agents</SelectItem>
                )}
                {availableAgents.map(a => (
                  <SelectItem key={a.id} value={a.id}>
                    {a.name} — {a.status.status}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-gray-700">Lead Count</label>
            <Input
              type="number"
              min={1}
              max={500}
              value={count}
              onChange={(e) => setCount(Number(e.target.value))}
            />
          </div>

          <DialogFooter className="mt-2">
            <Button type="submit" disabled={loading}>
              {loading ? 'Assigning…' : 'Assign'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
