import { ConversationList } from '@/components/live/conversation-list'
import { ConversationDetail } from '@/components/live/conversation-detail'
import { RightPanel } from '@/components/live/right-panel'

export function LivePage() {
  return (
    <div className="grid h-[calc(100vh-64px)] grid-cols-[280px_1fr_260px]">
      <ConversationList />
      <ConversationDetail />
      <RightPanel />
    </div>
  )
}
