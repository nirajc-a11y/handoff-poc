import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { Message } from '@/lib/types'

export function useEmailThread(conversationId: string | null) {
  return useQuery<Message[]>({
    queryKey: ['email-thread', conversationId],
    queryFn: () => api.get(`/channels/email/${conversationId}/thread`),
    enabled: !!conversationId,
  })
}
