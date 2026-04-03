import { useEffect } from 'react'
import { useAtom, useAtomValue, useSetAtom } from 'jotai'
import { useQueryClient } from '@tanstack/react-query'
import { wsManager } from '@/lib/ws'
import { wsConnectedAtom, wsEventsAtom } from '@/stores/ws'
import { tenantIdAtom, isConnectedAtom } from '@/stores/auth'
import { selectedConvIdAtom } from '@/stores/ui'
import type { WSEvent } from '@/lib/types'
import type { Message, QueueStats } from '@/lib/types'

export function useWebSocket() {
  const [tenantId] = useAtom(tenantIdAtom)
  const isConnected = useAtomValue(isConnectedAtom)
  const [, setConnected] = useAtom(wsConnectedAtom)
  const [, setEvents] = useAtom(wsEventsAtom)
  const setSelectedConvId = useSetAtom(selectedConvIdAtom)
  const qc = useQueryClient()

  // Clear selected conversation and stale queries when tenant changes
  useEffect(() => {
    setSelectedConvId(null)
    setEvents([])
  }, [tenantId, setSelectedConvId, setEvents])

  useEffect(() => {
    if (!tenantId || !isConnected) return
    wsManager.connect(tenantId, setConnected)
    const unsub = wsManager.subscribe((event: WSEvent) => {
      setEvents((prev) => [event, ...prev].slice(0, 100))

      // --- Conversation events: push data directly into cache ---
      if (event.type === 'conversation.message_added' && event.data?.conversation_id) {
        // If the event carries a full message object, append it to the cache
        if (event.data.message) {
          const msg = event.data.message as Message
          qc.setQueryData<Message[]>(
            ['messages', event.data.conversation_id],
            (old) => old ? [...old, msg] : [msg],
          )
        } else {
          qc.invalidateQueries({ queryKey: ['messages', event.data.conversation_id] })
        }
      }

      if (event.type.startsWith('conversation.') && event.type !== 'conversation.message_added') {
        // State change, handoff, recording — invalidate conversation queries
        qc.invalidateQueries({ queryKey: ['conversations'] })
        if (event.data?.conversation_id) {
          qc.invalidateQueries({ queryKey: ['conversations', 'detail', event.data.conversation_id] })
          qc.invalidateQueries({ queryKey: ['conversations', 'handoffs', event.data.conversation_id] })
        }
      }

      // --- Agent events: push directly ---
      if (event.type === 'agent.status_changed' && event.data?.agent_id) {
        // Invalidate agent lists so they refetch once
        qc.invalidateQueries({ queryKey: ['agents'] })
      }

      // --- Queue events: push full stats ---
      if (event.type === 'queue.stats_updated' && event.data) {
        const stats = event.data as unknown as QueueStats
        qc.setQueryData<QueueStats>(['queue-stats', tenantId], stats)
        // Also invalidate the handoff queue list
        qc.invalidateQueries({ queryKey: ['handoff-queue'] })
      }

      // --- Campaign events ---
      if (event.type.startsWith('campaign.')) {
        qc.invalidateQueries({ queryKey: ['campaigns'] })
      }
    })
    return () => { unsub(); wsManager.disconnect() }
  }, [tenantId, isConnected, setConnected, setEvents, qc])
}
