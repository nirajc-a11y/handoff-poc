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

const navItems = [
  { key: 'live', label: 'Live', icon: Phone },
  { key: 'analytics', label: 'Analytics', icon: BarChart3 },
  { key: 'campaigns', label: 'Campaigns', icon: Megaphone },
  { key: 'leads', label: 'Leads', icon: Contact },
  { key: 'agents', label: 'Agents', icon: Users },
  { key: 'history', label: 'History', icon: History },
  { key: 'ivr', label: 'IVR', icon: GitBranch },
  { key: 'settings', label: 'Settings', icon: Settings },
] as const

interface SidebarProps {
  currentPage: string
  onNavigate: (page: string) => void
  collapsed: boolean
  onToggle: () => void
}

export function Sidebar({ currentPage, onNavigate, collapsed, onToggle }: SidebarProps) {
  return (
    <div
      className={cn(
        'flex h-full flex-col border-r border-border bg-white transition-all duration-200',
        collapsed ? 'w-14' : 'w-52'
      )}
    >
      <div className="flex items-center justify-end p-2">
        <Button variant="ghost" size="icon-sm" onClick={onToggle}>
          {collapsed ? <PanelLeft className="size-4" /> : <PanelLeftClose className="size-4" />}
        </Button>
      </div>

      <nav className="flex flex-1 flex-col gap-1 px-2">
        <TooltipProvider>
          {navItems.map((item) => {
            const Icon = item.icon
            const isActive = currentPage === item.key

            const button = (
              <button
                key={item.key}
                onClick={() => onNavigate(item.key)}
                className={cn(
                  'flex w-full items-center gap-3 rounded-sm px-2.5 py-2 text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-blue-50 text-blue-700'
                    : 'text-gray-600 hover:bg-muted hover:text-gray-900'
                )}
              >
                <Icon className="size-4 shrink-0" />
                {!collapsed && <span>{item.label}</span>}
              </button>
            )

            if (collapsed) {
              return (
                <Tooltip key={item.key}>
                  <TooltipTrigger render={<div />}>
                    {button}
                  </TooltipTrigger>
                  <TooltipContent side="right">{item.label}</TooltipContent>
                </Tooltip>
              )
            }

            return button
          })}
        </TooltipProvider>
      </nav>
    </div>
  )
}
