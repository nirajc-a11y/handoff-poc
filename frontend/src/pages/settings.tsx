import { TenantConfig } from '@/components/settings/tenant-config'
import { ProviderConfig } from '@/components/settings/provider-config'
import { AIConfig } from '@/components/settings/ai-config'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { Settings } from 'lucide-react'

export function SettingsPage() {
  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Page header */}
      <div className="flex items-center gap-2 border-b bg-background px-6 py-4 shrink-0">
        <Settings className="size-5 text-muted-foreground" />
        <h1 className="font-heading text-base font-medium">Settings</h1>
      </div>

      {/* Tabs content */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        <Tabs defaultValue="general">
          <TabsList>
            <TabsTrigger value="general">General</TabsTrigger>
            <TabsTrigger value="providers">Providers</TabsTrigger>
            <TabsTrigger value="ai">AI</TabsTrigger>
          </TabsList>

          <TabsContent value="general" className="mt-4">
            <TenantConfig />
          </TabsContent>

          <TabsContent value="providers" className="mt-4">
            <ProviderConfig />
          </TabsContent>

          <TabsContent value="ai" className="mt-4">
            <AIConfig />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  )
}
