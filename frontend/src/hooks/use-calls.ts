import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'

export function useDialOutbound() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { to_number: string; customer_name?: string }) =>
      api.post('/calls/outbound', body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['conversations'] }),
  })
}

export function useCallAction(conversationId: string) {
  const qc = useQueryClient()
  return {
    hold: useMutation({ mutationFn: () => api.post(`/calls/${conversationId}/hold`), onSuccess: () => qc.invalidateQueries({ queryKey: ['conversations'] }) }),
    unhold: useMutation({ mutationFn: () => api.post(`/calls/${conversationId}/unhold`), onSuccess: () => qc.invalidateQueries({ queryKey: ['conversations'] }) }),
    end: useMutation({ mutationFn: () => api.post(`/calls/${conversationId}/end`), onSuccess: () => qc.invalidateQueries({ queryKey: ['conversations'] }) }),
    forceEnd: useMutation({ mutationFn: () => api.post(`/calls/${conversationId}/force-end`), onSuccess: () => qc.invalidateQueries({ queryKey: ['conversations'] }) }),
    answer: useMutation({ mutationFn: () => api.post(`/calls/${conversationId}/answer`), onSuccess: () => qc.invalidateQueries({ queryKey: ['conversations'] }) }),
  }
}

export function useCampaignDial() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { campaign_id: string }) => api.post('/calls/outbound/campaign', body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['conversations'] }),
  })
}
