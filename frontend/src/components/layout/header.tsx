import { useState, useEffect } from 'react'
import { useAtomValue } from 'jotai'
import { Phone } from 'lucide-react'
import { isConnectedAtom } from '@/stores/auth'
import { cn } from '@/lib/utils'
import { TenantSelector } from './tenant-selector'
import { SoftphoneIndicator } from './softphone-indicator'

export function Header() {
  const isConnected = useAtomValue(isConnectedAtom)
  const [clock, setClock] = useState(new Date())

  useEffect(() => {
    const timer = setInterval(() => setClock(new Date()), 1000)
    return () => clearInterval(timer)
  }, [])

  return (
    <header className="flex h-12 shrink-0 items-center justify-between border-b border-border bg-white px-4">
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2">
          <div className="flex size-8 items-center justify-center rounded-md bg-blue-600">
            <Phone className="size-4 text-white" />
          </div>
          <div>
            <h1 className="text-sm font-semibold text-gray-900">Angel Tel</h1>
            <p className="text-xs text-gray-500">Operations Center</p>
          </div>
        </div>
      </div>

      <div className="flex items-center gap-4">
        <TenantSelector />

        <SoftphoneIndicator />

        <div className="flex items-center gap-2">
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

        <span className="font-mono text-sm text-gray-600">
          {clock.toLocaleTimeString('en-US', {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: false,
          })}
        </span>
      </div>
    </header>
  )
}
