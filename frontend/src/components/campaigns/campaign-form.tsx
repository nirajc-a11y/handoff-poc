import { useState } from 'react'
import { toast } from 'sonner'
import { useCreateCampaign } from '@/hooks/use-campaigns'
import { api } from '@/lib/api'
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
  open: boolean
  onClose: () => void
  campaign?: Campaign | null
}

const CAMPAIGN_TYPES = [
  { value: 'outbound_call', label: 'Outbound Call' },
  { value: 'outbound_sms', label: 'Outbound SMS' },
  { value: 'outbound_whatsapp', label: 'Outbound WhatsApp' },
  { value: 'outbound_email', label: 'Outbound Email' },
]

export function CampaignForm({ open, onClose, campaign }: Props) {
  const isEdit = !!campaign
  const createCampaign = useCreateCampaign()

  const [name, setName] = useState(campaign?.name ?? '')
  const [type, setType] = useState(campaign?.type ?? 'outbound_call')
  const [startDate, setStartDate] = useState(campaign?.start_date?.slice(0, 10) ?? '')
  const [endDate, setEndDate] = useState(campaign?.end_date?.slice(0, 10) ?? '')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!name.trim()) {
      toast.error('Name is required')
      return
    }
    setLoading(true)
    try {
      if (isEdit && campaign) {
        await api.patch(`/campaigns/${campaign.id}`, {
          name,
          type,
          start_date: startDate || null,
          end_date: endDate || null,
        })
        toast.success('Campaign updated')
      } else {
        await createCampaign.mutateAsync({
          name,
          type,
          config: { start_date: startDate || null, end_date: endDate || null },
        })
        toast.success('Campaign created')
      }
      onClose()
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{isEdit ? 'Edit Campaign' : 'Create Campaign'}</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-gray-700">Name</label>
            <Input
              placeholder="Campaign name"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-gray-700">Type</label>
            <Select value={type} onValueChange={(v) => setType(v ?? 'outbound_call')}>
              <SelectTrigger className="w-full">
                <SelectValue placeholder="Select type" />
              </SelectTrigger>
              <SelectContent>
                {CAMPAIGN_TYPES.map((t) => (
                  <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-gray-700">Start Date</label>
              <Input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-gray-700">End Date</label>
              <Input
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
              />
            </div>
          </div>

          <DialogFooter className="mt-2">
            <Button type="submit" disabled={loading}>
              {loading ? 'Saving…' : isEdit ? 'Update' : 'Create'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
