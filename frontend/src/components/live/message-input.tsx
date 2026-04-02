import { useState, useCallback, useRef } from 'react'
import { Send, Mic, Square } from 'lucide-react'
import { useAtomValue } from 'jotai'
import type { Channel } from '@/lib/types'
import { api } from '@/lib/api'
import { tenantIdAtom, userIdAtom } from '@/stores/auth'
import { useSendMessage } from '@/hooks/use-messages'
import { useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { toast } from 'sonner'

interface MessageInputProps {
  conversationId: string
  channel: Channel
}

export function MessageInput({ conversationId, channel }: MessageInputProps) {
  const [content, setContent] = useState('')
  const sendMessage = useSendMessage(conversationId)
  const tenantId = useAtomValue(tenantIdAtom)
  const userId = useAtomValue(userIdAtom)

  const handleSend = useCallback(async () => {
    const text = content.trim()
    if (!text) return

    try {
      if (channel === 'whatsapp') {
        await api.post('/channels/whatsapp/send', {
          conversation_id: conversationId,
          content: text,
        })
      } else if (channel === 'email') {
        await api.post('/channels/email/send', {
          conversation_id: conversationId,
          body_html: text,
        })
      } else if (channel === 'sms') {
        await api.post('/channels/sms/send', {
          conversation_id: conversationId,
          content: text,
        })
      } else {
        await sendMessage.mutateAsync({ content: text, content_type: 'text', sender_type: 'agent' })
      }
      setContent('')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to send message')
    }
  }, [content, channel, conversationId, sendMessage])

  const [recording, setRecording] = useState(false)
  const mediaRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const qc = useQueryClient()

  const startRecording = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const recorder = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' })
      chunksRef.current = []
      recorder.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data) }
      recorder.onstop = async () => {
        stream.getTracks().forEach(t => t.stop())
        const blob = new Blob(chunksRef.current, { type: 'audio/webm' })
        const form = new FormData()
        form.append('file', blob, 'recording.webm')
        try {
          await fetch(`/api/v1/conversations/${conversationId}/audio-message`, {
            method: 'POST',
            headers: { 'X-Tenant-Id': tenantId || '', 'X-User-Id': userId || '' },
            body: form,
          })
          qc.invalidateQueries({ queryKey: ['messages', conversationId] })
          toast.success('Voice note saved')
        } catch {
          toast.error('Failed to upload recording')
        }
      }
      recorder.start()
      mediaRef.current = recorder
      setRecording(true)
    } catch {
      toast.error('Microphone access denied')
    }
  }, [conversationId, qc])

  const stopRecording = useCallback(() => {
    mediaRef.current?.stop()
    mediaRef.current = null
    setRecording(false)
  }, [])

  if (channel === 'voice') {
    return (
      <div className="flex items-center justify-center gap-3 border-t border-gray-200 bg-gray-50 px-4 py-2.5">
        <Button
          variant={recording ? 'destructive' : 'outline'}
          size="sm"
          onClick={recording ? stopRecording : startRecording}
          className="gap-1.5"
        >
          {recording ? <Square className="size-3" /> : <Mic className="size-3" />}
          {recording ? 'Stop Recording' : 'Record Voice Note'}
        </Button>
        {recording && <span className="text-xs text-red-500 animate-pulse">Recording...</span>}
      </div>
    )
  }

  return (
    <div className="flex items-end gap-2 border-t border-gray-200 bg-white p-3">
      <Textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            handleSend()
          }
        }}
        placeholder={`Message via ${channel}...`}
        className="min-h-8 resize-none text-sm"
        rows={1}
      />
      <Button
        size="icon-sm"
        onClick={handleSend}
        disabled={!content.trim()}
      >
        <Send className="size-3.5" />
      </Button>
    </div>
  )
}
