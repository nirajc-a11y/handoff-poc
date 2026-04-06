import { useState, useEffect } from 'react'
import { useAtom, useAtomValue, useSetAtom } from 'jotai'
import { useNavigate } from 'react-router-dom'
import { Phone, Menu, LogOut } from 'lucide-react'
import { tenantIdAtom, userIdAtom, isConnectedAtom } from '@/stores/auth'
import { mobileSidebarOpenAtom } from '@/stores/ui'
import { wsConnectedAtom, wsInitializedAtom } from '@/stores/ws'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { SoftphoneIndicator } from './softphone-indicator'

export function Header() {
  const tenantId = useAtomValue(tenantIdAtom)
  const setUserId = useSetAtom(userIdAtom)
  const [isConnected, setIsConnected] = useAtom(isConnectedAtom)
  const setTenantId = useSetAtom(tenantIdAtom)
  const setWsConnected = useSetAtom(wsConnectedAtom)
  const setWsInitialized = useSetAtom(wsInitializedAtom)
  const [mobileSidebarOpen, setMobileSidebarOpen] = useAtom(mobileSidebarOpenAtom)
  const navigate = useNavigate()
  const [clock, setClock] = useState(new Date())

  useEffect(() => {
    const timer = setInterval(() => setClock(new Date()), 1000)
    return () => clearInterval(timer)
  }, [])

  const handleDisconnect = () => {
    setIsConnected(false)
    setTenantId('')
    setUserId('')
    setWsConnected(false)
    setWsInitialized(false)
    navigate('/login', { replace: true })
  }

  // Truncate tenant ID for display: show first 8 and last 4 chars
  const displayTenant = tenantId
    ? `${tenantId.slice(0, 8)}…${tenantId.slice(-4)}`
    : ''

  return (
    <header className="flex h-12 shrink-0 items-center justify-between border-b border-border bg-white px-4">
      <div className="flex items-center gap-3">
        <Button
          variant="ghost"
          size="icon-sm"
          className="md:hidden"
          onClick={() => setMobileSidebarOpen(!mobileSidebarOpen)}
        >
          <Menu className="size-5" />
          <span className="sr-only">Toggle menu</span>
        </Button>
        <div className="flex items-center gap-2">
          <div className="flex size-8 items-center justify-center rounded-md bg-blue-600">
            <Phone className="size-4 text-white" />
          </div>
          <div className="hidden sm:block">
            <h1 className="text-sm font-semibold text-gray-900">Angel Tel</h1>
            <p className="text-xs text-gray-500">Operations Center</p>
          </div>
        </div>
      </div>

      <div className="flex items-center gap-2 sm:gap-4">
        {tenantId && (
          <span className="hidden sm:inline font-mono text-xs text-gray-500" title={tenantId}>
            {displayTenant}
          </span>
        )}

        <SoftphoneIndicator />

        <div className="hidden sm:flex items-center gap-2">
          <div
            className={cn(
              'size-2 rounded-full',
              isConnected ? 'bg-green-500' : 'bg-red-500'
            )}
          />
          <span className="text-xs text-gray-500">
            {isConnected ? 'Connected' : 'Disconnected'}
          </span>
        </div>

        <span className="hidden sm:inline font-mono text-sm text-gray-600">
          {clock.toLocaleTimeString('en-US', {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: false,
          })}
        </span>

        <Button
          variant="ghost"
          size="icon-sm"
          onClick={handleDisconnect}
          title="Disconnect"
        >
          <LogOut className="size-4" />
          <span className="sr-only">Disconnect</span>
        </Button>
      </div>
    </header>
  )
}
