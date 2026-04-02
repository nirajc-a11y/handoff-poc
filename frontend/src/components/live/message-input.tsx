import { useState, useCallback } from 'react'
import { Send } from 'lucide-react'
import type { Channel } from '@/lib/types'
import { api } from '@/lib/api'
import { useSendMessage } from '@/hooks/use-messages'
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

  if (channel === 'voice') {
    return (
      <div className="flex items-center justify-center border-t border-gray-200 bg-gray-50 px-4 py-3">
        <p className="text-xs text-gray-400">Voice call -- use softphone</p>
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
