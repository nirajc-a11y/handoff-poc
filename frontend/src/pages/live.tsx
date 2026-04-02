import { ConversationList } from '@/components/live/conversation-list'
import { ConversationDetail } from '@/components/live/conversation-detail'
import { RightPanel } from '@/components/live/right-panel'

export function LivePage() {
  return (
    <div className="relative h-full">
      <div className="absolute inset-0 grid grid-cols-[280px_1fr_260px]">
        <div className="relative overflow-hidden">
          <div className="absolute inset-0"><ConversationList /></div>
        </div>
        <div className="relative overflow-hidden">
          <div className="absolute inset-0"><ConversationDetail /></div>
        </div>
        <div className="relative overflow-hidden">
          <div className="absolute inset-0"><RightPanel /></div>
        </div>
      </div>
    </div>
  )
}
