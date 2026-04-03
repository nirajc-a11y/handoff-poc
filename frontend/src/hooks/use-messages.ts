import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { Message } from '@/lib/types'

export function useMessages(conversationId: string | null) {
  return useQuery<Message[]>({
    queryKey: ['messages', conversationId],
    queryFn: () => api.get(`/conversations/${conversationId}/messages`),
    enabled: !!conversationId,
  })
}

export function useSendMessage(conversationId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { content: string; content_type?: string; sender_type?: string }) =>
      api.post(`/conversations/${conversationId}/messages`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['messages', conversationId] }),
  })
}
