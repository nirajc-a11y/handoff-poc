import { useState } from 'react'
import { useAtom, useAtomValue } from 'jotai'
import { sidebarCollapsedAtom } from '@/stores/ui'
import { tenantIdAtom, isConnectedAtom } from '@/stores/auth'
import { useWebSocket } from '@/hooks/use-websocket'
import { ErrorBoundary } from '@/components/error-boundary'
import { Sidebar } from './sidebar'
import { Header } from './header'
import { OfflineIndicator } from '@/components/offline-indicator'
import { LivePage } from '@/pages/live'
import { AnalyticsPage } from '@/pages/analytics'
import { CampaignsPage } from '@/pages/campaigns'
import { AgentsPage } from '@/pages/agents'
import { LeadsPage } from '@/pages/leads'
import { HistoryPage } from '@/pages/history'
import { IVRPage } from '@/pages/ivr'
import { SettingsPage } from '@/pages/settings'

function PagePlaceholder({ name }: { name: string }) {
  return (
    <div className="flex h-full items-center justify-center">
      <p className="text-sm text-gray-400">{name} page -- coming soon</p>
    </div>
  )
}

export function AppShell() {
  const [currentPage, setCurrentPage] = useState('live')
  const [collapsed, setCollapsed] = useAtom(sidebarCollapsedAtom)
  const tenantId = useAtomValue(tenantIdAtom)
  const isConnected = useAtomValue(isConnectedAtom)

  useWebSocket()

  const renderPage = () => {
    switch (currentPage) {
      case 'live':
        return <LivePage />
      case 'analytics':
        return <AnalyticsPage />
      case 'campaigns':
        return <CampaignsPage />
      case 'leads':
        return <LeadsPage />
      case 'agents':
        return <AgentsPage />
      case 'history':
        return <HistoryPage />
      case 'ivr':
        return <IVRPage />
      case 'settings':
        return <SettingsPage />
      default:
        return <PagePlaceholder name={currentPage} />
    }
  }

  return (
    <div className="flex h-screen flex-col bg-background">
      <Header />
      <OfflineIndicator />
      <div className="flex flex-1 overflow-hidden">
        <Sidebar
          currentPage={currentPage}
          onNavigate={setCurrentPage}
          collapsed={collapsed}
          onToggle={() => setCollapsed(!collapsed)}
        />
        <main className="flex-1 overflow-hidden">
          <ErrorBoundary>
          {tenantId && isConnected ? (
            renderPage()
          ) : (
            <div className="flex h-full items-center justify-center">
              <p className="text-sm text-gray-400">
                Enter a Tenant ID and click Connect to get started
              </p>
            </div>
          )}
          </ErrorBoundary>
        </main>
      </div>
    </div>
  )
}
