import { useAtom } from 'jotai'
import { Outlet } from 'react-router-dom'
import { sidebarCollapsedAtom } from '@/stores/ui'
import { useWebSocket } from '@/hooks/use-websocket'
import { ErrorBoundary } from '@/components/error-boundary'
import { Sidebar } from './sidebar'
import { Header } from './header'
import { OfflineIndicator } from '@/components/offline-indicator'

export function AppShell() {
  const [collapsed, setCollapsed] = useAtom(sidebarCollapsedAtom)

  useWebSocket()

  return (
    <div className="flex h-screen flex-col bg-background">
      <Header />
      <OfflineIndicator />
      <div className="flex flex-1 overflow-hidden">
        <Sidebar
          collapsed={collapsed}
          onToggle={() => setCollapsed(!collapsed)}
        />
        <main className="flex-1 overflow-hidden">
          <ErrorBoundary>
            <Outlet />
          </ErrorBoundary>
        </main>
      </div>
    </div>
  )
}
