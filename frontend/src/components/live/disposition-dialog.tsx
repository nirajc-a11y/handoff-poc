import { useState } from 'react'
import { api } from '@/lib/api'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { toast } from 'sonner'

const dispositionOptions = [
  'interested',
  'callback',
  'not_interested',
  'resolved',
  'follow_up',
  'wrong_number',
  'voicemail',
] as const

interface DispositionDialogProps {
  conversationId: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function DispositionDialog({ conversationId, open, onOpenChange }: DispositionDialogProps) {
  const [disposition, setDisposition] = useState<string>('')
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async () => {
    if (!disposition) return
    setSubmitting(true)
    try {
      await api.post(`/conversations/${conversationId}/disposition`, {
        disposition,
        notes: notes.trim() || null,
      })
      toast.success('Disposition saved')
      onOpenChange(false)
      setDisposition('')
      setNotes('')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to save disposition')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>Set Disposition</DialogTitle>
          <DialogDescription>Classify the outcome of this conversation</DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label className="text-xs">Disposition</Label>
            <Select value={disposition} onValueChange={(v) => setDisposition(v ?? '')}>
              <SelectTrigger className="w-full">
                <SelectValue placeholder="Select disposition" />
              </SelectTrigger>
              <SelectContent>
                {dispositionOptions.map((opt) => (
                  <SelectItem key={opt} value={opt}>
                    {opt.replace(/_/g, ' ')}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label className="text-xs">Notes</Label>
            <Textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Optional notes..."
              rows={3}
              className="text-sm"
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={!disposition || submitting}>
            {submitting ? 'Saving...' : 'Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
