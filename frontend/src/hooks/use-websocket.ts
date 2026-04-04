import { useEffect } from 'react'
import { useAtom, useAtomValue, useSetAtom } from 'jotai'
import { useQueryClient } from '@tanstack/react-query'
import { wsManager } from '@/lib/ws'
import { wsConnectedAtom, wsEventsAtom, wsExhaustedAtom } from '@/stores/ws'
import { tenantIdAtom, isConnectedAtom } from '@/stores/auth'
import { selectedConvIdAtom } from '@/stores/ui'
import type { WSEvent } from '@/lib/types'
import type { Message, QueueStats, Conversation } from '@/lib/types'
import type { PaginatedConversations } from '@/hooks/use-conversations'

export function useWebSocket() {
  const [tenantId] = useAtom(tenantIdAtom)
  const isConnected = useAtomValue(isConnectedAtom)
  const [, setConnected] = useAtom(wsConnectedAtom)
  const [, setEvents] = useAtom(wsEventsAtom)
  const [, setExhausted] = useAtom(wsExhaustedAtom)
  const setSelectedConvId = useSetAtom(selectedConvIdAtom)
  const qc = useQueryClient()

  // Clear selected conversation and stale queries when tenant changes
  useEffect(() => {
    setSelectedConvId(null)
    setEvents([])
  }, [tenantId, setSelectedConvId, setEvents])

  useEffect(() => {
    if (!tenantId || !isConnected) return
    wsManager.connect(
      tenantId,
      (connected) => {
        setConnected(connected)
        if (connected) setExhausted(false)
      },
      () => setExhausted(true),
    )
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
        // Optimistically update the state in cache so the UI reflects the
        // transition immediately without waiting for the refetch round-trip.
        if (event.type === 'conversation.state_changed' && event.data?.conversation_id) {
          const convId = event.data.conversation_id as string
          const toState = event.data.to_state as string | undefined
          if (toState) {
            qc.setQueryData<Conversation>(
              ['conversations', 'detail', convId],
              (old) => old ? { ...old, state: toState } : old,
            )
            qc.setQueryData<PaginatedConversations>(
              ['conversations', tenantId, 'active', 50, 0],
              (old) => old ? {
                ...old,
                items: old.items.map((c) =>
                  c.id === convId ? { ...c, state: toState } : c,
                ),
              } : old,
            )
          }
        }
        // Always invalidate so the next background refetch gets fresh server data
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
  }, [tenantId, isConnected, setConnected, setExhausted, setEvents, qc])
}
