import { useState } from 'react'
import { useAtom, useSetAtom } from 'jotai'
import { tenantIdAtom, isConnectedAtom } from '@/stores/auth'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'

export function TenantSelector() {
  const [tenantId, setTenantId] = useAtom(tenantIdAtom)
  const setConnected = useSetAtom(isConnectedAtom)
  const [inputValue, setInputValue] = useState(tenantId)

  const handleConnect = () => {
    const trimmed = inputValue.trim()
    if (trimmed) {
      setTenantId(trimmed)
      setConnected(true)
    }
  }

  return (
    <div className="flex items-center gap-2">
      <Input
        placeholder="Tenant ID"
        value={inputValue}
        onChange={(e) => setInputValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') handleConnect()
        }}
        className="h-7 w-48 text-xs"
      />
      <Button size="xs" onClick={handleConnect}>
        Connect
      </Button>
    </div>
  )
}
