import { useState } from 'react'
import { useAvailableAgents } from '@/hooks/use-agents'
import { useTransfer } from '@/hooks/use-handoffs'
import { cn, agentStatusColors } from '@/lib/utils'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Switch } from '@/components/ui/switch'
import { Label } from '@/components/ui/label'
import { ScrollArea } from '@/components/ui/scroll-area'
import { toast } from 'sonner'

interface TransferDialogProps {
  conversationId: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function TransferDialog({ conversationId, open, onOpenChange }: TransferDialogProps) {
  const { data: agents = [] } = useAvailableAgents()
  const transfer = useTransfer()
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null)
  const [warm, setWarm] = useState(false)

  const handleTransfer = async () => {
    if (!selectedAgentId) return
    try {
      await transfer.mutateAsync({
        conversation_id: conversationId,
        target_agent_id: selectedAgentId,
        warm,
      })
      toast.success('Transfer initiated')
      onOpenChange(false)
      setSelectedAgentId(null)
      setWarm(false)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Transfer failed')
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Transfer Conversation</DialogTitle>
          <DialogDescription>Select an agent to transfer to</DialogDescription>
        </DialogHeader>

        <ScrollArea className="max-h-60">
          <div className="flex flex-col gap-1">
            {agents.length === 0 ? (
              <p className="p-4 text-center text-xs text-gray-400">No available agents</p>
            ) : (
              agents.map((agent) => (
                <button
                  key={agent.id}
                  onClick={() => setSelectedAgentId(agent.id)}
                  className={cn(
                    'flex items-center gap-3 rounded-md p-2 text-left transition-colors',
                    selectedAgentId === agent.id
                      ? 'bg-blue-50 ring-1 ring-blue-200'
                      : 'hover:bg-gray-50'
                  )}
                >
                  <div
                    className={cn(
                      'size-2 shrink-0 rounded-full',
                      agentStatusColors[agent.status.status] ?? 'bg-gray-400'
                    )}
                  />
                  <div className="flex flex-1 flex-col gap-0.5 overflow-hidden">
                    <span className="truncate text-sm font-medium text-gray-900">
                      {agent.name}
                    </span>
                    <span className="text-[10px] text-gray-500">{agent.team ?? 'No team'}</span>
                    {agent.skills.length > 0 && (
                      <div className="flex flex-wrap gap-1">
                        {agent.skills.map((skill) => (
                          <Badge key={skill} variant="secondary" className="h-4 text-[10px]">
                            {skill}
                          </Badge>
                        ))}
                      </div>
                    )}
                  </div>
                  <span className="text-[10px] capitalize text-gray-400">
                    {agent.status.status.replace(/_/g, ' ')}
                  </span>
                </button>
              ))
            )}
          </div>
        </ScrollArea>

        <div className="flex items-center gap-2">
          <Switch checked={warm} onCheckedChange={setWarm} id="warm-transfer" />
          <Label htmlFor="warm-transfer" className="text-xs">
            Warm transfer
          </Label>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={handleTransfer} disabled={!selectedAgentId || transfer.isPending}>
            {transfer.isPending ? 'Transferring...' : 'Transfer'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
