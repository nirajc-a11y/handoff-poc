import { useState } from 'react'
import { useAtom } from 'jotai'
import { selectedConvIdAtom } from '@/stores/ui'
import { useActiveConversations, useConversations } from '@/hooks/use-conversations'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { ScrollArea } from '@/components/ui/scroll-area'
import { ConversationCard } from './conversation-card'
import { ConversationListSkeleton } from './conversation-list-skeleton'

const PAGE_SIZE = 50

export function ConversationList() {
  const [selectedId, setSelectedId] = useAtom(selectedConvIdAtom)
  const [activeLimit, setActiveLimit] = useState(PAGE_SIZE)
  const { data: activeData, isLoading: isLoadingActive } = useActiveConversations(activeLimit)
  const { data: ended = [], isLoading: isLoadingEnded } = useConversations({ state: 'ended' })

  const active = activeData?.items ?? []
  const activeTotal = activeData?.total ?? 0
  const nonEnded = active.filter((c) => c.state !== 'ended')
  const queued = active.filter((c) => c.state === 'queued_for_human')
  const hasMoreActive = activeTotal > activeLimit

  return (
    <div className="flex h-full flex-col border-r border-border bg-white">
      <Tabs defaultValue="active" className="flex h-full flex-col gap-0">
        <div className="shrink-0 border-b border-border px-2 pt-2">
          <TabsList variant="line" className="w-full">
            <TabsTrigger value="active" className="flex-1 text-xs">
              Active ({activeTotal})
            </TabsTrigger>
            <TabsTrigger value="queued" className="flex-1 text-xs">
              Queued ({queued.length})
            </TabsTrigger>
            <TabsTrigger value="completed" className="flex-1 text-xs">
              Completed ({ended.length})
            </TabsTrigger>
          </TabsList>
        </div>

        <TabsContent value="active" className="flex-1 overflow-hidden">
          <ScrollArea className="h-full">
            <div className="flex flex-col gap-0.5 p-1">
              {isLoadingActive ? (
                <ConversationListSkeleton count={5} />
              ) : nonEnded.length === 0 ? (
                <p className="p-4 text-center text-xs text-gray-400">No active conversations</p>
              ) : (
                nonEnded.map((c) => (
                  <ConversationCard
                    key={c.id}
                    conversation={c}
                    selected={selectedId === c.id}
                    onClick={() => setSelectedId(c.id)}
                  />
                ))
              )}
              {hasMoreActive && (
                <button
                  onClick={() => setActiveLimit((prev) => prev + PAGE_SIZE)}
                  className="mx-auto my-2 rounded-md border border-border px-3 py-1.5 text-xs text-gray-500 hover:bg-gray-50"
                >
                  Load more ({activeTotal - activeLimit} remaining)
                </button>
              )}
            </div>
          </ScrollArea>
        </TabsContent>

        <TabsContent value="queued" className="flex-1 overflow-hidden">
          <ScrollArea className="h-full">
            <div className="flex flex-col gap-0.5 p-1">
              {isLoadingActive ? (
                <ConversationListSkeleton count={3} />
              ) : queued.length === 0 ? (
                <p className="p-4 text-center text-xs text-gray-400">No queued conversations</p>
              ) : (
                queued.map((c) => (
                  <ConversationCard
                    key={c.id}
                    conversation={c}
                    selected={selectedId === c.id}
                    onClick={() => setSelectedId(c.id)}
                  />
                ))
              )}
            </div>
          </ScrollArea>
        </TabsContent>

        <TabsContent value="completed" className="flex-1 overflow-hidden">
          <ScrollArea className="h-full">
            <div className="flex flex-col gap-0.5 p-1">
              {isLoadingEnded ? (
                <ConversationListSkeleton count={5} />
              ) : ended.length === 0 ? (
                <p className="p-4 text-center text-xs text-gray-400">No completed conversations</p>
              ) : (
                ended.map((c) => (
                  <ConversationCard
                    key={c.id}
                    conversation={c}
                    selected={selectedId === c.id}
                    onClick={() => setSelectedId(c.id)}
                  />
                ))
              )}
            </div>
          </ScrollArea>
        </TabsContent>
      </Tabs>
    </div>
  )
}
