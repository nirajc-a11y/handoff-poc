import { useAtom } from 'jotai'
import { selectedConvIdAtom } from '@/stores/ui'
import { useActiveConversations, useConversations } from '@/hooks/use-conversations'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { ScrollArea } from '@/components/ui/scroll-area'
import { ConversationCard } from './conversation-card'

export function ConversationList() {
  const [selectedId, setSelectedId] = useAtom(selectedConvIdAtom)
  const { data: active = [] } = useActiveConversations()
  const { data: ended = [] } = useConversations({ state: 'ended' })

  const nonEnded = active.filter((c) => c.state !== 'ended')
  const queued = active.filter((c) => c.state === 'queued_for_human')

  return (
    <div className="flex h-full flex-col border-r border-gray-200 bg-white">
      <Tabs defaultValue="active" className="flex h-full flex-col gap-0">
        <div className="shrink-0 border-b border-gray-200 px-2 pt-2">
          <TabsList variant="line" className="w-full">
            <TabsTrigger value="active" className="flex-1 text-xs">
              Active ({nonEnded.length})
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
              {nonEnded.length === 0 ? (
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
            </div>
          </ScrollArea>
        </TabsContent>

        <TabsContent value="queued" className="flex-1 overflow-hidden">
          <ScrollArea className="h-full">
            <div className="flex flex-col gap-0.5 p-1">
              {queued.length === 0 ? (
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
              {ended.length === 0 ? (
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
