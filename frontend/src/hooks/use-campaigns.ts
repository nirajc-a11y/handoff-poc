import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useAtomValue } from 'jotai'
import { api } from '@/lib/api'
import { tenantIdAtom } from '@/stores/auth'
import type { Campaign, CampaignLead } from '@/lib/types'

export function useCampaigns() {
  const tenantId = useAtomValue(tenantIdAtom)
  return useQuery<Campaign[]>({ queryKey: ['campaigns', tenantId], queryFn: () => api.get('/campaigns'), enabled: !!tenantId })
}

export function useCampaign(id: string | null) {
  return useQuery<Campaign>({ queryKey: ['campaigns', 'detail', id], queryFn: () => api.get(`/campaigns/${id}`), enabled: !!id })
}

export function useCampaignLeads(campaignId: string | null) {
  return useQuery<CampaignLead[]>({ queryKey: ['campaigns', 'leads', campaignId], queryFn: () => api.get(`/campaigns/${campaignId}/leads`), enabled: !!campaignId })
}

export function useCreateCampaign() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { name: string; type: string; config?: unknown }) => api.post('/campaigns', body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['campaigns'] }),
  })
}

export function useDeleteCampaign() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.delete(`/campaigns/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['campaigns'] }),
  })
}

export function useNextCampaignLead() {
  return useMutation({
    mutationFn: ({ campaignId, agentId }: { campaignId: string; agentId: string }) =>
      api.post(`/campaigns/${campaignId}/next-lead`, { agent_id: agentId }),
  })
}
