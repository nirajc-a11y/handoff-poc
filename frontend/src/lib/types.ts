export type Channel = 'voice' | 'whatsapp' | 'email' | 'sms'
export type Direction = 'inbound' | 'outbound'
export type HandlerType = 'ivr' | 'ai' | 'human' | 'system'
export type ConversationState =
  | 'initiated' | 'ringing' | 'ivr' | 'ai_handling'
  | 'queued_for_human' | 'human_handling' | 'on_hold'
  | 'transferred' | 'wrap_up' | 'ended' | 'failed'
export type AgentStatusType = 'available' | 'on_call' | 'in_wrap' | 'busy' | 'offline'

export interface Conversation {
  id: string; tenant_id: string; channel: Channel; direction: Direction
  state: ConversationState; sub_state: string | null
  customer_identifier: string; customer_name: string | null
  current_handler_type: HandlerType; current_handler_id: string | null
  lead_id: string | null; campaign_lead_id: string | null
  queue_entered_at: string | null; queue_priority: number
  required_skills: string[] | null
  started_at: string; answered_at: string | null; ended_at: string | null
  duration_seconds: number | null
  disposition: string | null; disposition_notes: string | null
  ai_confidence_score: number | null; ai_escalation_reason: string | null
  recording_url: string | null
  context: Record<string, unknown>
  created_at: string; updated_at: string
}

export interface Message {
  id: string; conversation_id: string; tenant_id: string
  sender_type: 'customer' | 'agent' | 'ai' | 'system' | 'ivr'
  sender_id: string | null
  content_type: 'text' | 'audio' | 'image' | 'file' | 'dtmf' | 'system_event'
  content: string | null; metadata: Record<string, unknown>
  email_message_id: string | null; email_subject: string | null
  created_at: string
}

export interface Agent {
  id: string; user_id: string; tenant_id: string
  skills: string[]; max_concurrent: number; team: string | null
  name: string; email: string; status: AgentStatus
}

export interface AgentStatus {
  status: AgentStatusType; current_conversations: number
  last_status_change: string | null
}

export interface Campaign {
  id: string; tenant_id: string; name: string
  status: 'draft' | 'active' | 'paused' | 'completed'
  type: string; start_date: string | null; end_date: string | null
  config: Record<string, unknown>; created_at: string
}

export interface CampaignLead {
  id: string; campaign_id: string; lead_id: string
  assigned_agent_id: string | null; status: string
  attempt_count: number; disposition: string | null; notes: string | null
}

export interface Lead {
  id: string; tenant_id: string; name: string | null
  phone: string | null; email: string | null
  whatsapp_number: string | null; metadata: Record<string, unknown>
}

export interface HandoffEvent {
  id: string; conversation_id: string; event_type: string
  from_handler_type: string | null; from_handler_id: string | null
  to_handler_type: string | null; to_handler_id: string | null
  from_state: string | null; to_state: string | null
  reason: string | null; context_snapshot: Record<string, unknown> | null
  metadata: Record<string, unknown>; created_at: string
}

export interface IVRMenu {
  id: string; tenant_id: string; name: string; is_root: boolean
  welcome_message: string | null; config: Record<string, unknown>
  options: IVRMenuOption[]
}

export interface IVRMenuOption {
  id: string; menu_id: string; digit: string; label: string | null
  action_type: 'submenu' | 'ai_handoff' | 'human_queue' | 'play_message' | 'hangup'
  target_id: string | null; target_config: Record<string, unknown>; sort_order: number
}

export interface Tenant {
  id: string; name: string; slug: string; status: string; config: Record<string, unknown>
}

export interface QueueStats {
  queue_depth: number; avg_wait_seconds: number; by_skill: Record<string, number>
}

export interface WSEvent {
  type: string; event_id: string; timestamp: string; data: Record<string, unknown>
}
