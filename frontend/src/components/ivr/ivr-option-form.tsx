import { useState } from 'react'
import { toast } from 'sonner'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

type ActionType = 'submenu' | 'ai_handoff' | 'human_queue' | 'play_message' | 'hangup'

interface IVROptionFormProps {
  menuId: string
  open: boolean
  onClose: () => void
}

const actionTypeColors: Record<ActionType, string> = {
  submenu: 'text-blue-700',
  ai_handoff: 'text-violet-700',
  human_queue: 'text-green-700',
  play_message: 'text-amber-700',
  hangup: 'text-red-700',
}

export function IVROptionForm({ menuId, open, onClose }: IVROptionFormProps) {
  const qc = useQueryClient()
  const [digit, setDigit] = useState('')
  const [label, setLabel] = useState('')
  const [actionType, setActionType] = useState<ActionType>('ai_handoff')
  const [queueName, setQueueName] = useState('')
  const [language, setLanguage] = useState('en')
  const [greeting, setGreeting] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const handleClose = () => {
    setDigit('')
    setLabel('')
    setActionType('ai_handoff')
    setQueueName('')
    setLanguage('en')
    setGreeting('')
    onClose()
  }

  const handleSubmit = async () => {
    if (!digit.trim()) {
      toast.error('Digit is required')
      return
    }

    const targetConfig: Record<string, unknown> = {}
    if (actionType === 'ai_handoff') {
      targetConfig.queue_name = queueName
      targetConfig.language = language
      targetConfig.greeting = greeting
    } else if (actionType === 'human_queue') {
      targetConfig.queue_name = queueName
    }

    setSubmitting(true)
    try {
      await api.post(`/ivr/menus/${menuId}/options`, {
        digit: digit.trim(),
        label: label.trim() || undefined,
        action_type: actionType,
        target_config: targetConfig,
      })
      toast.success('Option added')
      qc.invalidateQueries({ queryKey: ['ivr-menus'] })
      handleClose()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to add option')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(open) => { if (!open) handleClose() }}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Add IVR Option</DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-4">
          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="digit">Digit</Label>
              <Input
                id="digit"
                maxLength={1}
                placeholder="e.g. 1"
                value={digit}
                onChange={(e) => setDigit(e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="label">Label</Label>
              <Input
                id="label"
                placeholder="e.g. Sales"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
              />
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>Action Type</Label>
            <Select value={actionType} onValueChange={(v) => v && setActionType(v as ActionType)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="submenu">Submenu</SelectItem>
                <SelectItem value="ai_handoff">AI Handoff</SelectItem>
                <SelectItem value="human_queue">Human Queue</SelectItem>
                <SelectItem value="play_message">Play Message</SelectItem>
                <SelectItem value="hangup">Hangup</SelectItem>
              </SelectContent>
            </Select>
            {actionType in actionTypeColors && (
              <p className={`text-xs ${actionTypeColors[actionType]}`}>
                {actionType === 'ai_handoff' && 'Routes to AI agent'}
                {actionType === 'human_queue' && 'Routes to human agent queue'}
                {actionType === 'submenu' && 'Navigates to a sub-menu'}
                {actionType === 'play_message' && 'Plays a recorded message'}
                {actionType === 'hangup' && 'Ends the call'}
              </p>
            )}
          </div>

          {(actionType === 'ai_handoff' || actionType === 'human_queue') && (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="queue_name">Queue Name</Label>
              <Input
                id="queue_name"
                placeholder="e.g. sales, support"
                value={queueName}
                onChange={(e) => setQueueName(e.target.value)}
              />
            </div>
          )}

          {actionType === 'ai_handoff' && (
            <>
              <div className="flex flex-col gap-1.5">
                <Label>Language</Label>
                <Select value={language} onValueChange={(v) => v && setLanguage(v)}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="en">English</SelectItem>
                    <SelectItem value="mr">Marathi</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor="greeting">AI Greeting</Label>
                <Textarea
                  id="greeting"
                  placeholder="Hello! How can I help you today?"
                  rows={3}
                  value={greeting}
                  onChange={(e) => setGreeting(e.target.value)}
                />
              </div>
            </>
          )}
        </div>

        <DialogFooter showCloseButton>
          <Button onClick={handleSubmit} disabled={submitting}>
            {submitting ? 'Adding…' : 'Add Option'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
