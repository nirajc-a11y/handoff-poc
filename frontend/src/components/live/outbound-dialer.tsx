import { useState } from 'react'
import { Phone } from 'lucide-react'
import { useDialOutbound } from '@/hooks/use-calls'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { toast } from 'sonner'

export function OutboundDialer() {
  const [phoneNumber, setPhoneNumber] = useState('')
  const [name, setName] = useState('')
  const dial = useDialOutbound()

  const handleDial = async () => {
    const num = phoneNumber.trim()
    if (!num) return
    try {
      await dial.mutateAsync({
        to_number: num,
        customer_name: name.trim() || undefined,
      })
      toast.success(`Dialing ${num}`)
      setPhoneNumber('')
      setName('')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Dial failed')
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <Input
        placeholder="Phone number"
        value={phoneNumber}
        onChange={(e) => setPhoneNumber(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') handleDial()
        }}
        className="h-7 text-xs"
      />
      <Input
        placeholder="Name (optional)"
        value={name}
        onChange={(e) => setName(e.target.value)}
        className="h-7 text-xs"
      />
      <Button
        size="sm"
        className="w-full bg-green-600 hover:bg-green-700"
        onClick={handleDial}
        disabled={!phoneNumber.trim() || dial.isPending}
      >
        <Phone className="size-3.5" />
        {dial.isPending ? 'Dialing...' : 'Dial'}
      </Button>
    </div>
  )
}
