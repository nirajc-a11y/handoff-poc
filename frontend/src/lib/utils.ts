import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatDuration(seconds: number | null): string {
  if (seconds == null || seconds < 0) return '--:--'
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

export function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-US', {
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  })
}

export function timeSince(iso: string): number {
  return Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
}

export const stateColors: Record<string, string> = {
  initiated: 'bg-gray-100 text-gray-700',
  ringing: 'bg-blue-100 text-blue-700',
  ivr: 'bg-blue-100 text-blue-700',
  ai_handling: 'bg-violet-100 text-violet-700',
  queued_for_human: 'bg-orange-100 text-orange-700',
  human_handling: 'bg-green-100 text-green-700',
  on_hold: 'bg-yellow-100 text-yellow-700',
  transferred: 'bg-indigo-100 text-indigo-700',
  wrap_up: 'bg-amber-100 text-amber-700',
  ended: 'bg-gray-100 text-gray-500',
  failed: 'bg-red-100 text-red-700',
}

export const channelIcons: Record<string, string> = {
  voice: '📞', whatsapp: '💬', email: '📧', sms: '📱',
}

export const agentStatusColors: Record<string, string> = {
  available: 'bg-green-500', on_call: 'bg-red-500', in_wrap: 'bg-yellow-500',
  busy: 'bg-orange-500', offline: 'bg-gray-400',
}
