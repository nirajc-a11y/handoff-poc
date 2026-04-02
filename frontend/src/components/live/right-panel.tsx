import { ScrollArea } from '@/components/ui/scroll-area'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { AgentGrid } from './agent-grid'
import { OutboundDialer } from './outbound-dialer'
import { CampaignWidget } from './campaign-widget'
import { QueueList } from './queue-list'
import { EventFeed } from './event-feed'
import { SoftphonePanel } from '@/components/softphone/softphone-panel'

export function RightPanel() {
  return (
    <ScrollArea className="h-full border-l border-gray-200 bg-white">
      <div className="flex flex-col gap-3 p-3">
        <Card size="sm">
          <CardHeader className="pb-0">
            <CardTitle className="text-xs font-semibold text-gray-600">Agents</CardTitle>
          </CardHeader>
          <CardContent>
            <AgentGrid />
          </CardContent>
        </Card>

        <Card size="sm">
          <CardHeader className="pb-0">
            <CardTitle className="text-xs font-semibold text-gray-600">Queue</CardTitle>
          </CardHeader>
          <CardContent>
            <QueueList />
          </CardContent>
        </Card>

        <Card size="sm">
          <CardHeader className="pb-0">
            <CardTitle className="text-xs font-semibold text-gray-600">Softphone</CardTitle>
          </CardHeader>
          <CardContent>
            <SoftphonePanel />
          </CardContent>
        </Card>

        <Card size="sm">
          <CardHeader className="pb-0">
            <CardTitle className="text-xs font-semibold text-gray-600">Outbound Dialer</CardTitle>
          </CardHeader>
          <CardContent>
            <OutboundDialer />
          </CardContent>
        </Card>

        <Card size="sm">
          <CardHeader className="pb-0">
            <CardTitle className="text-xs font-semibold text-gray-600">Campaign</CardTitle>
          </CardHeader>
          <CardContent>
            <CampaignWidget />
          </CardContent>
        </Card>

        <Card size="sm">
          <CardHeader className="pb-0">
            <CardTitle className="text-xs font-semibold text-gray-600">Event Feed</CardTitle>
          </CardHeader>
          <CardContent>
            <EventFeed />
          </CardContent>
        </Card>
      </div>
    </ScrollArea>
  )
}
