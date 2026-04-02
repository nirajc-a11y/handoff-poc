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
import { Badge } from '@/components/ui/badge'
import { toast } from 'sonner'
import { Building2 } from 'lucide-react'

export function TenantConfig() {
  const tenantId = useAtomValue(tenantIdAtom)
  const { data: tenant, isLoading, refetch } = useQuery<Tenant>({
    queryKey: ['tenant', tenantId],
    queryFn: () => api.get(`/tenants/${tenantId}`),
    enabled: !!tenantId,
  })

  const [name, setName] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (tenant) {
      setName(tenant.name)
    }
  }, [tenant])

  const handleSave = async () => {
    if (!tenantId) return
    setSaving(true)
    try {
      await api.patch(`/tenants/${tenantId}`, { name })
      await refetch()
      toast.success('Tenant settings saved')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  if (!tenantId) {
    return (
      <Card>
        <CardContent>
          <p className="text-sm text-muted-foreground py-4">No tenant selected.</p>
        </CardContent>
      </Card>
    )
  }

  if (isLoading) {
    return (
      <Card>
        <CardContent>
          <p className="text-sm text-muted-foreground py-4">Loading...</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Building2 className="size-4" />
          Tenant Information
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex flex-col gap-4 max-w-sm">
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground">Status:</span>
            <Badge
              variant={tenant?.status === 'active' ? 'default' : 'secondary'}
              className="capitalize"
            >
              {tenant?.status ?? '—'}
            </Badge>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="tenant-name">Name</Label>
            <Input
              id="tenant-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Tenant name"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="tenant-slug">Slug</Label>
            <Input
              id="tenant-slug"
              value={tenant?.slug ?? ''}
              disabled
              className="opacity-60"
            />
            <p className="text-xs text-muted-foreground">Slug cannot be changed after creation.</p>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>Tenant ID</Label>
            <Input value={tenantId} disabled className="font-mono text-xs opacity-60" />
          </div>

          <Button onClick={handleSave} disabled={saving} className="self-start">
            {saving ? 'Saving…' : 'Save Changes'}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
