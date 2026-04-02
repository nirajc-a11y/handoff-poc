import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

interface SoftphoneLoginProps {
  onLogin: (user: string, pass: string) => void
  onLogout: () => void
  isRegistered: boolean
}

export function SoftphoneLogin({ onLogin, onLogout, isRegistered }: SoftphoneLoginProps) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')

  if (isRegistered) {
    return (
      <div className="flex items-center justify-between gap-2 px-3 py-2">
        <div className="flex items-center gap-2">
          <span className="inline-block size-2 rounded-full bg-green-500" />
          <span className="text-xs font-medium text-gray-700">Registered</span>
        </div>
        <Button variant="outline" size="xs" onClick={onLogout}>
          Logout
        </Button>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-2 px-3 py-2">
      <Input
        placeholder="SIP Username"
        value={username}
        onChange={e => setUsername(e.target.value)}
        autoComplete="username"
      />
      <Input
        type="password"
        placeholder="Password"
        value={password}
        onChange={e => setPassword(e.target.value)}
        autoComplete="current-password"
        onKeyDown={e => {
          if (e.key === 'Enter' && username && password) onLogin(username, password)
        }}
      />
      <Button
        className={cn('w-full')}
        size="sm"
        disabled={!username || !password}
        onClick={() => onLogin(username, password)}
      >
        Login
      </Button>
    </div>
  )
}
