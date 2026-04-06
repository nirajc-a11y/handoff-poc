import type { WSEvent } from './types'

type EventHandler = (event: WSEvent) => void

export class WebSocketManager {
  private ws: WebSocket | null = null
  private url = ''
  private handlers: EventHandler[] = []
  private reconnectTimeout: ReturnType<typeof setTimeout> | null = null
  private reconnectDelay = 1000
  private retryCount = 0
  private maxRetries = 15
  private onStatusChange: ((connected: boolean) => void) | null = null
  private onMaxRetriesReached: (() => void) | null = null
  private intentionalDisconnect = false

  connect(tenantId: string, onStatus?: (connected: boolean) => void, onMaxRetries?: () => void) {
    this.onStatusChange = onStatus ?? null
    this.onMaxRetriesReached = onMaxRetries ?? null
    this.retryCount = 0
    this.intentionalDisconnect = false
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    this.url = `${protocol}//${location.host}/api/v1/ws/dashboard?tenant_id=${tenantId}`
    this._connect()
  }

  private _connect() {
    this.intentionalDisconnect = false
    this.ws?.close()
    this.ws = new WebSocket(this.url)
    this.ws.onopen = () => { this.reconnectDelay = 1000; this.retryCount = 0; this.onStatusChange?.(true) }
    this.ws.onmessage = (e) => {
      try {
        const data: WSEvent = JSON.parse(e.data as string)
        this.handlers.forEach(h => h(data))
      } catch (err) {
        console.warn('[ws] Failed to parse message:', err, e.data)
      }
    }
    this.ws.onclose = () => {
      if (this.intentionalDisconnect) return
      this.onStatusChange?.(false)
      this._scheduleReconnect()
    }
    this.ws.onerror = () => this.ws?.close()
  }

  private _scheduleReconnect() {
    if (this.reconnectTimeout) return
    this.retryCount++
    if (this.retryCount >= this.maxRetries) {
      this.onMaxRetriesReached?.()
      return
    }
    this.reconnectTimeout = setTimeout(() => {
      this.reconnectTimeout = null
      this.reconnectDelay = Math.min(this.reconnectDelay * 2, 30000)
      this._connect()
    }, this.reconnectDelay)
  }

  reconnect() {
    this.retryCount = 0
    this._connect()
  }

  get exhausted(): boolean {
    return this.retryCount >= this.maxRetries
  }

  subscribe(handler: EventHandler) {
    this.handlers.push(handler)
    return () => { this.handlers = this.handlers.filter(h => h !== handler) }
  }

  disconnect() {
    this.intentionalDisconnect = true
    if (this.reconnectTimeout) clearTimeout(this.reconnectTimeout)
    this.reconnectTimeout = null
    this.ws?.close()
    this.ws = null
  }
}

export const wsManager = new WebSocketManager()
