import { useState } from 'react'
import { useAtomValue } from 'jotai'
import { toast } from 'sonner'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { tenantIdAtom } from '@/stores/auth'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from '@/components/ui/dialog'

interface Props {
  open: boolean
  onClose: () => void
}

export function AgentForm({ open, onClose }: Props) {
  const tenantId = useAtomValue(tenantIdAtom)
  const qc = useQueryClient()

  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [team, setTeam] = useState('')
  const [skills, setSkills] = useState('')
  const [maxConcurrent, setMaxConcurrent] = useState(2)
  const [step, setStep] = useState<1 | 2>(1)
  const [userId, setUserId] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleStep1(e: React.FormEvent) {
    e.preventDefault()
    if (!name.trim() || !email.trim()) {
      toast.error('Name and email are required')
      return
    }
    setLoading(true)
    try {
      const user = await api.post<{ id: string }>(`/tenants/${tenantId}/users`, {
        email,
        name,
        role: 'agent',
      })
      setUserId(user.id)
      setStep(2)
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  async function handleStep2(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    try {
      const skillsList = skills
        .split(',')
        .map(s => s.trim())
        .filter(Boolean)

      await api.post(`/tenants/${tenantId}/agents`, {
        user_id: userId,
        skills: skillsList,
        max_concurrent: maxConcurrent,
        team: team || null,
      })

      toast.success('Agent created successfully')
      qc.invalidateQueries({ queryKey: ['agents'] })
      handleClose()
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  function handleClose() {
    setName('')
    setEmail('')
    setTeam('')
    setSkills('')
    setMaxConcurrent(2)
    setStep(1)
    setUserId('')
    onClose()
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) handleClose() }}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>
            Add Agent — Step {step} of 2:{' '}
            <span className="text-gray-500 font-normal">
              {step === 1 ? 'Create user' : 'Agent profile'}
            </span>
          </DialogTitle>
        </DialogHeader>

        {step === 1 ? (
          <form onSubmit={handleStep1} className="flex flex-col gap-3">
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-gray-700">Full Name</label>
              <Input
                placeholder="Jane Smith"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-gray-700">Email</label>
              <Input
                type="email"
                placeholder="jane@company.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            <DialogFooter className="mt-2">
              <Button type="submit" disabled={loading}>
                {loading ? 'Creating user…' : 'Next'}
              </Button>
            </DialogFooter>
          </form>
        ) : (
          <form onSubmit={handleStep2} className="flex flex-col gap-3">
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-gray-700">Team</label>
              <Input
                placeholder="Sales, Support…"
                value={team}
                onChange={(e) => setTeam(e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-gray-700">Skills (comma-separated)</label>
              <Input
                placeholder="english, billing, tech-support"
                value={skills}
                onChange={(e) => setSkills(e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-gray-700">Max Concurrent Conversations</label>
              <Input
                type="number"
                min={1}
                max={20}
                value={maxConcurrent}
                onChange={(e) => setMaxConcurrent(Number(e.target.value))}
              />
            </div>
            <DialogFooter className="mt-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => setStep(1)}
                disabled={loading}
              >
                Back
              </Button>
              <Button type="submit" disabled={loading}>
                {loading ? 'Creating agent…' : 'Create Agent'}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  )
}
