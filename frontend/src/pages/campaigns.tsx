import { useState } from 'react'
import { CampaignTable } from '@/components/campaigns/campaign-table'
import { CampaignForm } from '@/components/campaigns/campaign-form'
import { LeadTable } from '@/components/campaigns/lead-table'
import { LeadUpload } from '@/components/campaigns/lead-upload'
import { AssignDialog } from '@/components/campaigns/assign-dialog'
import { Button } from '@/components/ui/button'
import type { Campaign } from '@/lib/types'
import { Upload, Users } from 'lucide-react'

export function CampaignsPage() {
  const [selectedCampaign, setSelectedCampaign] = useState<Campaign | null>(null)
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [showLeadUpload, setShowLeadUpload] = useState(false)
  const [showAssign, setShowAssign] = useState(false)

  return (
    <div className="flex h-[calc(100vh-64px)] flex-col gap-4 overflow-y-auto bg-white p-6">
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
