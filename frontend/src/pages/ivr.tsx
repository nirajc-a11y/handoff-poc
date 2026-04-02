import { useState } from 'react'
import { useIVRMenus, useCreateIVRMenu } from '@/hooks/use-ivr'
import { IVRTree } from '@/components/ivr/ivr-tree'
import { IVRPreview } from '@/components/ivr/ivr-preview'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Switch } from '@/components/ui/switch'
import { toast } from 'sonner'
import { ListTree, Plus } from 'lucide-react'

export function IVRPage() {
  const { data: menus = [] } = useIVRMenus()
  const createMenu = useCreateIVRMenu()
  const [createOpen, setCreateOpen] = useState(false)

  const [menuName, setMenuName] = useState('')
  const [welcomeMessage, setWelcomeMessage] = useState('')
  const [isRoot, setIsRoot] = useState(false)

  const handleCreateMenu = async () => {
    if (!menuName.trim()) {
      toast.error('Menu name is required')
      return
    }
    try {
      await createMenu.mutateAsync({
        name: menuName.trim(),
        welcome_message: welcomeMessage.trim() || undefined,
        is_root: isRoot,
      })
      toast.success('Menu created')
      setMenuName('')
      setWelcomeMessage('')
      setIsRoot(false)
      setCreateOpen(false)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to create menu')
    }
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Page header */}
      <div className="flex items-center justify-between border-b bg-background px-6 py-4 shrink-0">
        <div className="flex items-center gap-2">
          <ListTree className="size-5 text-muted-foreground" />
          <h1 className="font-heading text-base font-medium">IVR Builder</h1>
        </div>
        <Button onClick={() => setCreateOpen(true)} className="gap-1.5">
          <Plus className="size-4" />
          Create Menu
        </Button>
      </div>

      {/* Main content */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left: IVR Tree (~60%) */}
        <div className="flex flex-col w-[60%] border-r overflow-y-auto p-4 gap-2">
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-1">
            Menus
          </p>
          <IVRTree />
        </div>

        {/* Right: Preview (~40%) */}
        <div className="flex flex-col w-[40%] overflow-y-auto p-4">
          <IVRPreview menus={menus} />
        </div>
      </div>

      {/* Create menu dialog */}
      <Dialog open={createOpen} onOpenChange={(open) => { if (!open) setCreateOpen(false) }}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Create IVR Menu</DialogTitle>
          </DialogHeader>

          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="menu-name">Menu Name</Label>
              <Input
                id="menu-name"
                placeholder="e.g. Main Menu, Sales Sub-Menu"
                value={menuName}
                onChange={(e) => setMenuName(e.target.value)}
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="welcome-msg">Welcome Message</Label>
              <Textarea
                id="welcome-msg"
                placeholder="Welcome to our service. Press 1 for Sales..."
                rows={3}
                value={welcomeMessage}
                onChange={(e) => setWelcomeMessage(e.target.value)}
              />
            </div>

            <div className="flex items-center gap-3">
              <Switch
                checked={isRoot}
                onCheckedChange={setIsRoot}
                id="is-root"
              />
              <Label htmlFor="is-root" className="cursor-pointer">
                Root menu (played first when customer calls)
              </Label>
            </div>
          </div>

          <DialogFooter showCloseButton>
            <Button
              onClick={handleCreateMenu}
              disabled={createMenu.isPending}
            >
              {createMenu.isPending ? 'Creating…' : 'Create Menu'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
