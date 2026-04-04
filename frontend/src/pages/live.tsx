import { useAtom } from 'jotai'
import { ArrowLeft } from 'lucide-react'
import { ConversationList } from '@/components/live/conversation-list'
import { ConversationDetail } from '@/components/live/conversation-detail'
import { PhonePanel } from '@/components/live/phone-panel'
import { LiveStatusBar } from '@/components/live/live-status-bar'
import { selectedConvIdAtom } from '@/stores/ui'
import { Button } from '@/components/ui/button'

export function LivePage() {
  const [selectedConvId, setSelectedConvId] = useAtom(selectedConvIdAtom)

  return (
    <div className="flex h-full flex-col">
      <LiveStatusBar />
      <div className="flex flex-1 overflow-hidden">
        {/* Conversation list: always visible on md+, hidden on mobile when a conversation is selected */}
        <div className={`w-full md:w-70 shrink-0 overflow-hidden ${selectedConvId ? 'hidden md:block' : 'block'}`}>
          <ConversationList />
        </div>

        {/* Conversation detail: always visible on md+, hidden on mobile when no conversation is selected */}
        <div className={`flex-1 overflow-hidden ${selectedConvId ? 'block' : 'hidden md:block'}`}>
          {/* Mobile back button */}
          <div className="flex items-center gap-2 border-b border-border p-2 md:hidden">
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={() => setSelectedConvId(null)}
            >
              <ArrowLeft className="size-4" />
              <span className="sr-only">Back to list</span>
            </Button>
            <span className="text-sm font-medium text-gray-700">Back to conversations</span>
          </div>
          <ConversationDetail />
        </div>

        {/* Phone panel: hidden on mobile */}
        <div className="hidden lg:block w-75 shrink-0 overflow-hidden">
          <PhonePanel />
        </div>
      </div>
    </div>
  )
}
