import { useState } from 'react'
import { CampaignTable } from '@/components/campaigns/campaign-table'
import { CampaignForm } from '@/components/campaigns/campaign-form'
import { LeadTable } from '@/components/campaigns/lead-table'
import { LeadUpload } from '@/components/campaigns/lead-upload'
import { AssignDialog } from '@/components/campaigns/assign-dialog'
import { useNextCampaignLead } from '@/hooks/use-campaigns'
import { useAtomValue } from 'jotai'
import { userIdAtom } from '@/stores/auth'
import { Button } from '@/components/ui/button'
import { toast } from 'sonner'
import type { Campaign } from '@/lib/types'
import { Upload, Users, SkipForward } from 'lucide-react'

export function CampaignsPage() {
  const [selectedCampaign, setSelectedCampaign] = useState<Campaign | null>(null)
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [showLeadUpload, setShowLeadUpload] = useState(false)
  const [showAssign, setShowAssign] = useState(false)
  const nextLead = useNextCampaignLead()
  const userId = useAtomValue(userIdAtom)

  const handleNextLead = async () => {
    if (!selectedCampaign || !userId) return
    try {
      await nextLead.mutateAsync({ campaignId: selectedCampaign.id, agentId: userId })
      toast.success('Next lead retrieved')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'No more leads available')
    }
  }

  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto bg-background p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Campaigns</h1>
          <p className="text-sm text-gray-500 mt-0.5">Manage outbound campaigns and leads</p>
        </div>
        {selectedCampaign && (
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowLeadUpload(true)}
            >
              <Upload size={14} />
              Upload Leads
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowAssign(true)}
            >
              <Users size={14} />
              Assign Leads
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={handleNextLead}
              disabled={nextLead.isPending}
            >
              <SkipForward size={14} />
              {nextLead.isPending ? 'Loading…' : 'Next Lead'}
            </Button>
          </div>
        )}
      </div>

      <CampaignTable
        selectedId={selectedCampaign?.id ?? null}
        onSelect={setSelectedCampaign}
        onCreateClick={() => setShowCreateForm(true)}
      />

      {selectedCampaign && (
        <LeadTable campaign={selectedCampaign} />
      )}

      <CampaignForm
        open={showCreateForm}
        onClose={() => setShowCreateForm(false)}
      />

      {selectedCampaign && (
        <>
          <LeadUpload
            campaign={selectedCampaign}
            open={showLeadUpload}
            onClose={() => setShowLeadUpload(false)}
          />
          <AssignDialog
            campaign={selectedCampaign}
            open={showAssign}
            onClose={() => setShowAssign(false)}
          />
        </>
      )}
    </div>
  )
}
