import { useAtom } from 'jotai'
import { NavLink } from 'react-router-dom'
import {
  Phone,
  BarChart3,
  Megaphone,
  Users,
  Contact,
  History,
  GitBranch,
  Settings,
  PanelLeftClose,
  PanelLeft,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import {
  Sheet,
  SheetContent,
  SheetTitle,
} from '@/components/ui/sheet'
import { mobileSidebarOpenAtom } from '@/stores/ui'

const navItems = [
  { path: '/live', label: 'Live', icon: Phone },
  { path: '/analytics', label: 'Analytics', icon: BarChart3 },
  { path: '/campaigns', label: 'Campaigns', icon: Megaphone },
  { path: '/leads', label: 'Leads', icon: Contact },
  { path: '/agents', label: 'Agents', icon: Users },
  { path: '/history', label: 'History', icon: History },
  { path: '/ivr', label: 'IVR', icon: GitBranch },
  { path: '/settings', label: 'Settings', icon: Settings },
] as const

interface SidebarProps {
  collapsed: boolean
  onToggle: () => void
}

function SidebarNav({
  collapsed,
  onItemClick,
}: {
  collapsed: boolean
  onItemClick?: () => void
}) {
  return (
    <nav className="flex flex-1 flex-col gap-1 px-2">
      <TooltipProvider>
        {navItems.map((item) => {
          const Icon = item.icon

          const link = (
            <NavLink
              key={item.path}
              to={item.path}
              onClick={onItemClick}
              className={({ isActive }) =>
                cn(
                  'flex w-full items-center gap-3 rounded-sm px-2.5 py-2 text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-blue-50 text-blue-700'
                    : 'text-gray-600 hover:bg-muted hover:text-gray-900'
                )
              }
            >
              <Icon className="size-4 shrink-0" />
              {!collapsed && <span>{item.label}</span>}
            </NavLink>
          )

          if (collapsed) {
            return (
              <Tooltip key={item.path}>
                <TooltipTrigger render={<div />}>
                  {link}
                </TooltipTrigger>
                <TooltipContent side="right">{item.label}</TooltipContent>
              </Tooltip>
            )
          }

          return link
        })}
      </TooltipProvider>
    </nav>
  )
}

export function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const [mobileSidebarOpen, setMobileSidebarOpen] = useAtom(mobileSidebarOpenAtom)

  return (
    <>
      {/* Desktop sidebar */}
      <div
        className={cn(
          'hidden md:flex h-full flex-col border-r border-border bg-white transition-all duration-200',
          collapsed ? 'w-14' : 'w-52'
        )}
      >
        <div className="flex items-center justify-end p-2">
          <Button variant="ghost" size="icon-sm" onClick={onToggle}>
            {collapsed ? <PanelLeft className="size-4" /> : <PanelLeftClose className="size-4" />}
          </Button>
        </div>

        <SidebarNav collapsed={collapsed} />
      </div>

      {/* Mobile sidebar (sheet/drawer) */}
      <Sheet open={mobileSidebarOpen} onOpenChange={setMobileSidebarOpen}>
        <SheetContent side="left" className="w-64 p-0" showCloseButton>
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          <div className="flex h-full flex-col pt-12">
            <SidebarNav
              collapsed={false}
              onItemClick={() => setMobileSidebarOpen(false)}
            />
          </div>
        </SheetContent>
      </Sheet>
    </>
  )
}
