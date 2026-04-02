import { ConversationList } from '@/components/live/conversation-list'
import { ConversationDetail } from '@/components/live/conversation-detail'
import { PhonePanel } from '@/components/live/phone-panel'
import { LiveStatusBar } from '@/components/live/live-status-bar'

export function LivePage() {
  return (
    <div className="flex h-full flex-col">
      <LiveStatusBar />
      <div className="flex flex-1 overflow-hidden">
        <div className="w-70 shrink-0 overflow-hidden">
          <ConversationList />
        </div>
        <div className="flex-1 overflow-hidden">
          <ConversationDetail />
        </div>
        <div className="w-75 shrink-0 overflow-hidden">
          <PhonePanel />
        </div>
      </div>
    </div>
  )
}
