import { useState, useEffect, useRef } from 'react'
import { Phone, Delete, ChevronDown } from 'lucide-react'
import { useDialOutbound } from '@/hooks/use-calls'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { toast } from 'sonner'

const COUNTRY_CODES = [
  { code: '+91', flag: '\u{1F1EE}\u{1F1F3}', name: 'India' },
  { code: '+1', flag: '\u{1F1FA}\u{1F1F8}', name: 'US' },
  { code: '+44', flag: '\u{1F1EC}\u{1F1E7}', name: 'UK' },
  { code: '+61', flag: '\u{1F1E6}\u{1F1FA}', name: 'Australia' },
  { code: '+971', flag: '\u{1F1E6}\u{1F1EA}', name: 'UAE' },
  { code: '+65', flag: '\u{1F1F8}\u{1F1EC}', name: 'Singapore' },
  { code: '+49', flag: '\u{1F1E9}\u{1F1EA}', name: 'Germany' },
  { code: '+33', flag: '\u{1F1EB}\u{1F1F7}', name: 'France' },
  { code: '+81', flag: '\u{1F1EF}\u{1F1F5}', name: 'Japan' },
  { code: '+86', flag: '\u{1F1E8}\u{1F1F3}', name: 'China' },
  { code: '+55', flag: '\u{1F1E7}\u{1F1F7}', name: 'Brazil' },
  { code: '+27', flag: '\u{1F1FF}\u{1F1E6}', name: 'South Africa' },
]

const KEYS = [
  [{ digit: '1', sub: '' }, { digit: '2', sub: 'ABC' }, { digit: '3', sub: 'DEF' }],
  [{ digit: '4', sub: 'GHI' }, { digit: '5', sub: 'JKL' }, { digit: '6', sub: 'MNO' }],
  [{ digit: '7', sub: 'PQRS' }, { digit: '8', sub: 'TUV' }, { digit: '9', sub: 'WXYZ' }],
  [{ digit: '*', sub: '' }, { digit: '0', sub: '+' }, { digit: '#', sub: '' }],
]

function formatDisplay(digits: string): string {
  // Format Indian numbers: XXXXX XXXXX
  if (digits.length <= 5) return digits
  if (digits.length <= 10) return digits.slice(0, 5) + ' ' + digits.slice(5)
  return digits
}

export function OutboundDialer() {
  const [phoneNumber, setPhoneNumber] = useState('')
  const [name, setName] = useState('')
  const [country, setCountry] = useState(COUNTRY_CODES[0])
  const [showCountryPicker, setShowCountryPicker] = useState(false)
  const dial = useDialOutbound()
  const containerRef = useRef<HTMLDivElement>(null)
  const pickerRef = useRef<HTMLDivElement>(null)

  const appendDigit = (digit: string) => {
    setPhoneNumber(prev => prev + digit)
  }

  const backspace = () => {
    setPhoneNumber(prev => prev.slice(0, -1))
  }

  const handleDial = async () => {
    const num = phoneNumber.trim()
    if (!num) return
    const fullNumber = country.code + num
    try {
      await dial.mutateAsync({
        to_number: fullNumber,
        customer_name: name.trim() || undefined,
      })
      toast.success(`Dialing ${fullNumber}`)
      setPhoneNumber('')
      setName('')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Dial failed')
    }
  }

  // Close country picker on outside click
  useEffect(() => {
    if (!showCountryPicker) return
    const handleClick = (e: MouseEvent) => {
      if (pickerRef.current && !pickerRef.current.contains(e.target as Node)) {
        setShowCountryPicker(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [showCountryPicker])

  // Keyboard support
  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement) return
      if (showCountryPicker) return
      if (/^[0-9*#]$/.test(e.key)) {
        e.preventDefault()
        appendDigit(e.key)
      } else if (e.key === 'Backspace') {
        e.preventDefault()
        backspace()
      } else if (e.key === 'Enter' && phoneNumber.trim()) {
        e.preventDefault()
        handleDial()
      }
    }

    container.addEventListener('keydown', handleKeyDown)
    return () => container.removeEventListener('keydown', handleKeyDown)
  })

  return (
    <div ref={containerRef} tabIndex={-1} className="flex flex-col gap-3 outline-none">
      {/* Display area */}
      <div className="flex flex-col items-center gap-1 py-2">
        {/* Country code selector */}
        <div className="relative" ref={pickerRef}>
          <button
            onClick={() => setShowCountryPicker(s => !s)}
            className="flex items-center gap-1 rounded-sm px-2 py-1 text-xs text-muted-foreground hover:bg-muted transition-colors"
          >
            <span className="text-sm">{country.flag}</span>
            <span className="font-mono font-medium text-foreground">{country.code}</span>
            <ChevronDown className="size-3" />
          </button>

          {showCountryPicker && (
            <div className="absolute left-1/2 top-full z-50 mt-1 -translate-x-1/2 w-48 max-h-52 overflow-y-auto border border-border bg-card shadow-lg rounded-sm">
              {COUNTRY_CODES.map(c => (
                <button
                  key={c.code}
                  onClick={() => {
                    setCountry(c)
                    setShowCountryPicker(false)
                  }}
                  className={`flex w-full items-center gap-2 px-3 py-1.5 text-xs transition-colors hover:bg-muted ${
                    c.code === country.code ? 'bg-muted font-medium' : ''
                  }`}
                >
                  <span className="text-sm">{c.flag}</span>
                  <span className="flex-1 text-left">{c.name}</span>
                  <span className="font-mono text-muted-foreground">{c.code}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Number display */}
        <div className="flex items-center gap-2 w-full px-2">
          <div className="flex-1 min-w-0 text-center min-h-8 flex items-center justify-center">
            {phoneNumber ? (
              <span className="font-mono text-2xl font-semibold tracking-wide text-foreground">
                {formatDisplay(phoneNumber)}
              </span>
            ) : (
              <span className="text-sm text-muted-foreground/60">Enter number</span>
            )}
          </div>
          {phoneNumber && (
            <button
              onClick={backspace}
              className="shrink-0 rounded-sm p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
            >
              <Delete className="size-4" />
            </button>
          )}
        </div>
      </div>

      {/* Number pad grid */}
      <div className="grid grid-cols-3 gap-1">
        {KEYS.flat().map(({ digit, sub }) => (
          <button
            key={digit}
            onClick={() => appendDigit(digit)}
            className="flex h-14 flex-col items-center justify-center rounded-sm bg-muted/60 hover:bg-muted transition-colors active:scale-[0.96] active:bg-accent"
          >
            <span className="text-xl font-semibold leading-none text-foreground">{digit}</span>
            {sub && (
              <span className="mt-0.5 text-[8px] font-medium tracking-[0.2em] text-muted-foreground/70">{sub}</span>
            )}
          </button>
        ))}
      </div>

      {/* Name input */}
      <Input
        placeholder="Name (optional)"
        value={name}
        onChange={e => setName(e.target.value)}
        className="h-8 text-xs"
      />

      {/* Call button */}
      <Button
        className="w-full h-12 bg-green-600 hover:bg-green-700 text-white rounded-sm text-sm font-semibold gap-2"
        onClick={handleDial}
        disabled={!phoneNumber.trim() || dial.isPending}
      >
        <Phone className="size-4" />
        {dial.isPending ? 'Dialing...' : `Call ${country.code} ${formatDisplay(phoneNumber) || ''}`}
      </Button>
    </div>
  )
}
