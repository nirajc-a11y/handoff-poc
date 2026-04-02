import { useState, useEffect } from 'react'
import { useAtomValue } from 'jotai'
import { useQuery } from '@tanstack/react-query'
import { tenantIdAtom } from '@/stores/auth'
import { api } from '@/lib/api'
import type { Tenant } from '@/lib/types'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { toast } from 'sonner'
import { Phone, Lock } from 'lucide-react'

type Provider = 'mock' | 'twilio' | 'plivo'

export function ProviderConfig() {
  const tenantId = useAtomValue(tenantIdAtom)
  const { data: tenant, isLoading, refetch } = useQuery<Tenant>({
    queryKey: ['tenant', tenantId],
    queryFn: () => api.get(`/tenants/${tenantId}`),
    enabled: !!tenantId,
  })

  const [provider, setProvider] = useState<Provider>('mock')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (tenant?.config) {
      const p = (tenant.config.telephony_provider as string | undefined) ?? 'mock'
      setProvider(p as Provider)
    }
  }, [tenant])

  const handleSave = async () => {
    if (!tenantId) return
    setSaving(true)
    try {
      await api.patch(`/tenants/${tenantId}`, {
        config: { ...tenant?.config, telephony_provider: provider },
      })
      await refetch()
      toast.success('Provider updated')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to update provider')
    } finally {
      setSaving(false)
    }
  }

  if (!tenantId || isLoading) {
    return (
      <Card>
        <CardContent>
          <p className="text-sm text-muted-foreground py-4">{isLoading ? 'Loading...' : 'No tenant selected.'}</p>
        </CardContent>
      </Card>
    )
  }

  const twilioAccountSid = tenant?.config?.twilio_account_sid as string | undefined
  const plivoAuthId = tenant?.config?.plivo_auth_id as string | undefined

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Phone className="size-4" />
          Telephony Provider
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex flex-col gap-4 max-w-sm">
          <div className="flex flex-col gap-1.5">
            <Label>Provider</Label>
            <Select value={provider} onValueChange={(v) => setProvider(v as Provider)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="mock">Mock (Development)</SelectItem>
                <SelectItem value="twilio">Twilio</SelectItem>
                <SelectItem value="plivo">Plivo</SelectItem>
              </SelectContent>
            </Select>
            {provider === 'mock' && (
              <p className="text-xs text-muted-foreground">
                Uses simulated calls. No real telephony. Safe for testing.
              </p>
            )}
          </div>

          {provider === 'twilio' && (
            <div className="rounded-xl border bg-muted/30 p-3 flex flex-col gap-3">
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <Lock className="size-3" />
                Credentials are stored securely and not editable here.
              </div>
              <div className="flex flex-col gap-1.5">
                <Label className="text-xs">Account SID</Label>
                <Input
                  value={twilioAccountSid ? maskCredential(twilioAccountSid) : '(not configured)'}
                  disabled
                  className="font-mono text-xs opacity-60"
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label className="text-xs">Auth Token</Label>
                <Input
                  value="••••••••••••••••••••••••••••••••"
                  disabled
                  className="font-mono text-xs opacity-60"
                />
              </div>
            </div>
          )}

          {provider === 'plivo' && (
            <div className="rounded-xl border bg-muted/30 p-3 flex flex-col gap-3">
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <Lock className="size-3" />
                Credentials are stored securely and not editable here.
              </div>
              <div className="flex flex-col gap-1.5">
                <Label className="text-xs">Auth ID</Label>
                <Input
                  value={plivoAuthId ? maskCredential(plivoAuthId) : '(not configured)'}
                  disabled
                  className="font-mono text-xs opacity-60"
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label className="text-xs">Auth Token</Label>
                <Input
                  value="••••••••••••••••••••••••••••••••"
                  disabled
                  className="font-mono text-xs opacity-60"
                />
              </div>
            </div>
          )}

          <Button onClick={handleSave} disabled={saving} className="self-start">
            {saving ? 'Updating…' : 'Update Provider'}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

function maskCredential(value: string): string {
  if (value.length <= 8) return '••••••••'
  return value.slice(0, 4) + '•'.repeat(value.length - 8) + value.slice(-4)
}
