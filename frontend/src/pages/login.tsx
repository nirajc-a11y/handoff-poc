import { useState } from 'react'
import { useAtom, useAtomValue, useSetAtom } from 'jotai'
import { Navigate, useNavigate } from 'react-router-dom'
import { Phone } from 'lucide-react'
import { tenantIdAtom, userIdAtom, isConnectedAtom } from '@/stores/auth'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

export function LoginPage() {
  const tenantId = useAtomValue(tenantIdAtom)
  const isConnected = useAtomValue(isConnectedAtom)

  const [, setTenantId] = useAtom(tenantIdAtom)
  const [, setUserId] = useAtom(userIdAtom)
  const setConnected = useSetAtom(isConnectedAtom)
  const navigate = useNavigate()

  const [tenantInput, setTenantInput] = useState(tenantId)
  const [userInput, setUserInput] = useState('')
  const [error, setError] = useState('')

  if (tenantId && isConnected) {
    return <Navigate to="/live" replace />
  }

  const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

  const handleConnect = () => {
    const trimmedTenant = tenantInput.trim()
    const trimmedUser = userInput.trim()

    if (!trimmedTenant || !trimmedUser) {
      setError('Both Tenant ID and User ID are required.')
      return
    }
    if (!UUID_RE.test(trimmedTenant)) {
      setError('Tenant ID must be a valid UUID (e.g. from the seed output).')
      return
    }
    if (!UUID_RE.test(trimmedUser)) {
      setError('User ID must be a valid UUID (e.g. from the seed output).')
      return
    }

    setTenantId(trimmedTenant)
    setUserId(trimmedUser)
    setConnected(true)
    navigate('/live', { replace: true })
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleConnect()
  }

  return (
    <div className="flex h-screen items-center justify-center bg-gray-50">
      <div className="w-full max-w-sm rounded-xl border border-border bg-white p-8 shadow-sm">
        <div className="mb-6 flex flex-col items-center gap-3">
          <div className="flex size-12 items-center justify-center rounded-xl bg-blue-600">
            <Phone className="size-6 text-white" />
          </div>
          <div className="text-center">
            <h1 className="text-xl font-semibold text-gray-900">Angel Tel</h1>
            <p className="text-sm text-gray-500">Operations Center</p>
          </div>
        </div>

        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="tenant-id">Tenant ID</Label>
            <Input
              id="tenant-id"
              placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
              value={tenantInput}
              onChange={(e) => setTenantInput(e.target.value)}
              onKeyDown={handleKeyDown}
              className="font-mono text-sm"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="user-id">User ID</Label>
            <Input
              id="user-id"
              placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
              value={userInput}
              onChange={(e) => setUserInput(e.target.value)}
              onKeyDown={handleKeyDown}
              className="font-mono text-sm"
            />
            <p className="text-xs text-gray-400">Use the agent UUID from the seed output, not a name.</p>
          </div>

          {error && (
            <p className="text-sm text-red-500">{error}</p>
          )}

          <Button onClick={handleConnect} className="w-full mt-1">
            Connect
          </Button>
        </div>
      </div>
    </div>
  )
}
