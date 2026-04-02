import { useAtomValue } from 'jotai'
import { Phone } from 'lucide-react'
import { plivoRegisteredAtom, plivoOnCallAtom, plivoRingingAtom } from '@/stores/softphone'
import { cn } from '@/lib/utils'

export function SoftphoneIndicator() {
  const registered = useAtomValue(plivoRegisteredAtom)
  const onCall = useAtomValue(plivoOnCallAtom)
  const ringing = useAtomValue(plivoRingingAtom)

  return (
    <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
      <Phone className="size-3.5" />
      <span
        className={cn(
          'size-1.5 rounded-full',
          onCall ? 'bg-green-500' : ringing ? 'bg-blue-500 animate-pulse' : registered ? 'bg-green-400' : 'bg-gray-300'
        )}
      />
      <span>{onCall ? 'On Call' : ringing ? 'Ringing' : registered ? 'Ready' : 'Offline'}</span>
    </div>
  )
}
