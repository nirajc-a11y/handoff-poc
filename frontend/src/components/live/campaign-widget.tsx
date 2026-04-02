import { useCampaigns } from '@/hooks/use-campaigns'
import { useCampaignDial } from '@/hooks/use-calls'
import { Button } from '@/components/ui/button'
import { Phone } from 'lucide-react'
import { toast } from 'sonner'

export function CampaignWidget() {
  const { data: campaigns = [] } = useCampaigns()
  const campaignDial = useCampaignDial()

  const activeCampaign = campaigns.find((c) => c.status === 'active')

  if (!activeCampaign) {
    return <p className="py-4 text-center text-xs text-gray-400">No active campaigns</p>
  }

  const config = activeCampaign.config as Record<string, unknown>
  const totalLeads = (config?.total_leads as number) ?? 0
  const dialedLeads = (config?.dialed_leads as number) ?? 0
  const progress = totalLeads > 0 ? Math.round((dialedLeads / totalLeads) * 100) : 0

  const handleDial = async () => {
    try {
      await campaignDial.mutateAsync({ campaign_id: activeCampaign.id })
      toast.success('Dialing next lead')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Campaign dial failed')
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="truncate text-xs font-medium text-gray-700">{activeCampaign.name}</span>
        <span className="text-[10px] text-gray-400">{progress}%</span>
      </div>

      {/* Simple progress bar */}
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-gray-100">
        <div
          className="h-full rounded-full bg-blue-500 transition-all"
          style={{ width: `${progress}%` }}
        />
      </div>

      <div className="flex justify-between text-[10px] text-gray-400">
        <span>{dialedLeads} dialed</span>
        <span>{totalLeads} total</span>
      </div>

      <Button
        size="sm"
        variant="outline"
        className="w-full"
        onClick={handleDial}
        disabled={campaignDial.isPending}
      >
        <Phone className="size-3" />
        {campaignDial.isPending ? 'Dialing...' : 'Dial Next Lead'}
      </Button>
    </div>
  )
}
