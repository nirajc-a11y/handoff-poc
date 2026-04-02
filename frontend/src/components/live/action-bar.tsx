import { useState } from 'react'
import {
  Pause,
  Play,
  ArrowRightLeft,
  ArrowUp,
  PhoneOff,
  PhoneMissed,
  ClipboardCheck,
} from 'lucide-react'
import type { Conversation } from '@/lib/types'
import { useCallAction } from '@/hooks/use-calls'
import { useEscalate } from '@/hooks/use-handoffs'
import { Button } from '@/components/ui/button'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { TransferDialog } from './transfer-dialog'
import { DispositionDialog } from './disposition-dialog'
import { toast } from 'sonner'

interface ActionBarProps {
  conversation: Conversation
}

export function ActionBar({ conversation }: ActionBarProps) {
  const actions = useCallAction(conversation.id)
  const escalate = useEscalate()
  const [transferOpen, setTransferOpen] = useState(false)
  const [dispositionOpen, setDispositionOpen] = useState(false)

  const isEnded = conversation.state === 'ended' || conversation.state === 'failed'
  const isOnHold = conversation.state === 'on_hold'
  const isHumanHandling = conversation.current_handler_type === 'human'
  const canForceEnd = ['ivr', 'ai_handling', 'queued_for_human', 'on_hold'].includes(conversation.state)

  const handleHold = async () => {
    try {
      await actions.hold.mutateAsync()
      toast.success('Call placed on hold')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Hold failed')
    }
  }

  const handleUnhold = async () => {
    try {
      await actions.unhold.mutateAsync()
      toast.success('Call resumed')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Unhold failed')
    }
  }

  const handleEnd = async () => {
    try {
      await actions.end.mutateAsync()
      toast.success('Call ended')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'End call failed')
    }
  }

  const handleForceEnd = async () => {
    try {
      await actions.forceEnd.mutateAsync()
      toast.success('Call marked as ended')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Force end failed')
    }
  }

  const handleEscalate = async () => {
    try {
      await escalate.mutateAsync({ conversation_id: conversation.id })
      toast.success('Escalation requested')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Escalation failed')
    }
  }

  return (
    <TooltipProvider>
      <div className="flex items-center gap-1 border-t border-gray-200 bg-white px-3 py-2">
        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                variant="outline"
                size="icon-sm"
                onClick={handleHold}
                disabled={isEnded || isOnHold}
              />
            }
          >
            <Pause className="size-3.5" />
          </TooltipTrigger>
          <TooltipContent>Hold</TooltipContent>
        </Tooltip>

        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                variant="outline"
                size="icon-sm"
                onClick={handleUnhold}
                disabled={isEnded || !isOnHold}
              />
            }
          >
            <Play className="size-3.5" />
          </TooltipTrigger>
          <TooltipContent>Unhold</TooltipContent>
        </Tooltip>

        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                variant="outline"
                size="icon-sm"
                onClick={() => setTransferOpen(true)}
                disabled={isEnded}
              />
            }
          >
            <ArrowRightLeft className="size-3.5" />
          </TooltipTrigger>
          <TooltipContent>Transfer</TooltipContent>
        </Tooltip>

        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                variant="outline"
                size="icon-sm"
                onClick={handleEscalate}
                disabled={isEnded || isHumanHandling}
              />
            }
          >
            <ArrowUp className="size-3.5" />
          </TooltipTrigger>
          <TooltipContent>Escalate</TooltipContent>
        </Tooltip>

        <div className="flex-1" />

        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                variant="outline"
                size="icon-sm"
                className="text-green-600 hover:bg-green-50 hover:text-green-700"
                onClick={() => setDispositionOpen(true)}
              />
            }
          >
            <ClipboardCheck className="size-3.5" />
          </TooltipTrigger>
          <TooltipContent>Disposition</TooltipContent>
        </Tooltip>

        {canForceEnd && (
          <Tooltip>
            <TooltipTrigger
              render={
                <Button
                  variant="outline"
                  size="icon-sm"
                  className="text-orange-600 hover:bg-orange-50 hover:text-orange-700"
                  onClick={handleForceEnd}
                />
              }
            >
              <PhoneMissed className="size-3.5" />
            </TooltipTrigger>
            <TooltipContent>Mark as Ended</TooltipContent>
          </Tooltip>
        )}

        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                variant="outline"
                size="icon-sm"
                className="text-red-600 hover:bg-red-50 hover:text-red-700"
                onClick={handleEnd}
                disabled={isEnded}
              />
            }
          >
            <PhoneOff className="size-3.5" />
          </TooltipTrigger>
          <TooltipContent>End Call</TooltipContent>
        </Tooltip>

        <TransferDialog
          conversationId={conversation.id}
          open={transferOpen}
          onOpenChange={setTransferOpen}
        />
        <DispositionDialog
          conversationId={conversation.id}
          open={dispositionOpen}
          onOpenChange={setDispositionOpen}
        />
      </div>
    </TooltipProvider>
  )
}
