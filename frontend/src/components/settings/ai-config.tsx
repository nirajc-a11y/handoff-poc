import { useState, useEffect } from 'react'
import { useAtomValue } from 'jotai'
import { useQuery } from '@tanstack/react-query'
import { tenantIdAtom } from '@/stores/auth'
import { api } from '@/lib/api'
import type { Tenant } from '@/lib/types'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { toast } from 'sonner'
import { Bot, Zap, Phone } from 'lucide-react'

const SUPPORTED_LANGUAGES = [
  { code: 'en', label: 'English' },
  { code: 'mr', label: 'Marathi' },
]

const VOICE_AI_MODES = [
  {
    value: 'plivo',
    label: 'Standard (Plivo TTS)',
    description: 'Record + transcribe + LLM + Plivo text-to-speech. ~5s response time.',
    icon: Phone,
  },
  {
    value: 'livekit',
    label: 'Real-time (Sarvam AI)',
    description: 'Live audio streaming with natural Indian voices. ~1-2s response time.',
    icon: Zap,
  },
] as const

const SARVAM_SPEAKERS = [
  { value: 'ritu', label: 'Ritu (Female)' },
  { value: 'aditya', label: 'Aditya (Male)' },
  { value: 'priya', label: 'Priya (Female)' },
  { value: 'rahul', label: 'Rahul (Male)' },
] as const

export function AIConfig() {
  const tenantId = useAtomValue(tenantIdAtom)
  const { data: tenant, isLoading, refetch } = useQuery<Tenant>({
    queryKey: ['tenant', tenantId],
    queryFn: () => api.get(`/tenants/${tenantId}`),
    enabled: !!tenantId,
  })

  const [voiceAiMode, setVoiceAiMode] = useState<'plivo' | 'livekit'>('plivo')
  const [sarvamSpeaker, setSarvamSpeaker] = useState<string>('ritu')
  const [confidenceThreshold, setConfidenceThreshold] = useState(0.7)
  const [groqModel, setGroqModel] = useState('llama3-8b-8192')
  const [systemPrompt, setSystemPrompt] = useState('')
  const [languages, setLanguages] = useState<string[]>(['en'])
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (tenant?.config) {
      const cfg = tenant.config
      if (cfg.voice_ai_mode === 'plivo' || cfg.voice_ai_mode === 'livekit') {
        setVoiceAiMode(cfg.voice_ai_mode)
      }
      const validSpeakers = SARVAM_SPEAKERS.map(s => s.value) as readonly string[]
      if (typeof cfg.sarvam_speaker === 'string' && validSpeakers.includes(cfg.sarvam_speaker)) {
        setSarvamSpeaker(cfg.sarvam_speaker)
      }
      if (typeof cfg.ai_confidence_threshold === 'number') {
        setConfidenceThreshold(cfg.ai_confidence_threshold as number)
      }
      if (typeof cfg.groq_model === 'string') {
        setGroqModel(cfg.groq_model as string)
      }
      if (typeof cfg.ai_system_prompt === 'string') {
        setSystemPrompt(cfg.ai_system_prompt as string)
      }
      if (Array.isArray(cfg.supported_languages)) {
        setLanguages(cfg.supported_languages as string[])
      }
    }
  }, [tenant])

  const toggleLanguage = (code: string) => {
    setLanguages((prev) =>
      prev.includes(code) ? prev.filter((l) => l !== code) : [...prev, code]
    )
  }

  const handleSave = async () => {
    if (!tenantId) return
    setSaving(true)
    try {
      await api.patch(`/tenants/${tenantId}`, {
        config: {
          ...tenant?.config,
          voice_ai_mode: voiceAiMode,
          sarvam_speaker: sarvamSpeaker,
          ai_confidence_threshold: confidenceThreshold,
          groq_model: groqModel,
          ai_system_prompt: systemPrompt,
          supported_languages: languages,
        },
      })
      await refetch()
      toast.success('AI configuration saved')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to save AI config')
    } finally {
      setSaving(false)
    }
  }

  if (!tenantId || isLoading) {
    return (
      <Card>
        <CardContent>
          <p className="text-sm text-muted-foreground py-4">{isLoading ? 'Loading...' : 'No tenant selected.'}</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Bot className="size-4" />
          AI Configuration
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex flex-col gap-5 max-w-lg">
          {/* Voice AI Mode */}
          <div className="flex flex-col gap-3">
            <Label>Voice AI Mode</Label>
            <div className="flex flex-col gap-2">
              {VOICE_AI_MODES.map((mode) => {
                const Icon = mode.icon
                return (
                  <label
                    key={mode.value}
                    className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                      voiceAiMode === mode.value
                        ? 'border-primary bg-primary/5'
                        : 'border-border hover:border-muted-foreground/30'
                    }`}
                  >
                    <input
                      type="radio"
                      name="voice_ai_mode"
                      value={mode.value}
                      checked={voiceAiMode === mode.value}
                      onChange={(e) => setVoiceAiMode(e.target.value as 'plivo' | 'livekit')}
                      className="mt-1 accent-primary"
                    />
                    <div className="flex flex-col gap-0.5">
                      <span className="text-sm font-medium flex items-center gap-1.5">
                        <Icon className="size-3.5" />
                        {mode.label}
                      </span>
                      <span className="text-xs text-muted-foreground">{mode.description}</span>
                    </div>
                  </label>
                )
              })}
            </div>
          </div>

          {/* Sarvam Speaker (only when livekit mode) */}
          {voiceAiMode === 'livekit' && (
            <div className="flex flex-col gap-2">
              <Label>Sarvam Voice</Label>
              <div className="flex items-center gap-3">
                {SARVAM_SPEAKERS.map((spk) => (
                  <label
                    key={spk.value}
                    className="flex items-center gap-2 cursor-pointer select-none"
                  >
                    <input
                      type="radio"
                      name="sarvam_speaker"
                      value={spk.value}
                      checked={sarvamSpeaker === spk.value}
                      onChange={(e) => setSarvamSpeaker(e.target.value)}
                      className="accent-primary"
                    />
                    <span className="text-sm">{spk.label}</span>
                  </label>
                ))}
              </div>
              <p className="text-xs text-muted-foreground">
                The Sarvam AI voice used for real-time text-to-speech.
              </p>
            </div>
          )}

          {/* Confidence threshold */}
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <Label htmlFor="confidence">Confidence Threshold</Label>
              <span className="text-sm font-medium tabular-nums">{confidenceThreshold.toFixed(1)}</span>
            </div>
            <input
              id="confidence"
              type="range"
              min={0}
              max={1}
              step={0.1}
              value={confidenceThreshold}
              onChange={(e) => setConfidenceThreshold(Number(e.target.value))}
              className="w-full h-2 bg-muted rounded-full appearance-none cursor-pointer accent-primary"
            />
            <div className="flex justify-between text-xs text-muted-foreground">
              <span>0.0 (Low)</span>
              <span>1.0 (High)</span>
            </div>
            <p className="text-xs text-muted-foreground">
              AI escalates to human when confidence drops below this threshold.
            </p>
          </div>

          {/* Groq model */}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="groq-model">Groq Model</Label>
            <Input
              id="groq-model"
              value={groqModel}
              onChange={(e) => setGroqModel(e.target.value)}
              placeholder="e.g. llama3-8b-8192"
            />
            <p className="text-xs text-muted-foreground">
              The Groq model ID used for AI conversation handling.
            </p>
          </div>

          {/* System prompt */}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="system-prompt">AI System Prompt</Label>
            <Textarea
              id="system-prompt"
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              placeholder="You are a helpful customer service agent for..."
              rows={6}
              className="resize-y"
            />
            <p className="text-xs text-muted-foreground">
              This prompt defines the AI agent's persona and behavior.
            </p>
          </div>

          {/* Supported languages */}
          <div className="flex flex-col gap-2">
            <Label>Supported Languages</Label>
            <div className="flex items-center gap-3">
              {SUPPORTED_LANGUAGES.map((lang) => (
                <label
                  key={lang.code}
                  className="flex items-center gap-2 cursor-pointer select-none"
                >
                  <input
                    type="checkbox"
                    checked={languages.includes(lang.code)}
                    onChange={() => toggleLanguage(lang.code)}
                    className="rounded border-input accent-primary"
                  />
                  <span className="text-sm">{lang.label}</span>
                </label>
              ))}
            </div>
          </div>

          <Button onClick={handleSave} disabled={saving} className="self-start">
            {saving ? 'Saving…' : 'Save AI Config'}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
