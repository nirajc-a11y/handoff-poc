import type { WSEvent } from './types'

type EventHandler = (event: WSEvent) => void

export class WebSocketManager {
  private ws: WebSocket | null = null
  private url = ''
  private handlers: EventHandler[] = []
  private reconnectTimeout: ReturnType<typeof setTimeout> | null = null
  private reconnectDelay = 1000
  private onStatusChange: ((connected: boolean) => void) | null = null

  connect(tenantId: string, onStatus?: (connected: boolean) => void) {
    this.onStatusChange = onStatus ?? null
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    this.url = `${protocol}//${location.host}/api/v1/ws/dashboard?tenant_id=${tenantId}`
    this._connect()
  }

  private _connect() {
    this.ws?.close()
    this.ws = new WebSocket(this.url)
    this.ws.onopen = () => { this.reconnectDelay = 1000; this.onStatusChange?.(true) }
    this.ws.onmessage = (e) => {
      try { const data: WSEvent = JSON.parse(e.data as string); this.handlers.forEach(h => h(data)) } catch { /* ignore parse errors */ }
    }
    this.ws.onclose = () => { this.onStatusChange?.(false); this._scheduleReconnect() }
    this.ws.onerror = () => this.ws?.close()
  }

  private _scheduleReconnect() {
    if (this.reconnectTimeout) return
    this.reconnectTimeout = setTimeout(() => {
      this.reconnectTimeout = null
      this.reconnectDelay = Math.min(this.reconnectDelay * 2, 30000)
      this._connect()
    }, this.reconnectDelay)
  }

  subscribe(handler: EventHandler) {
    this.handlers.push(handler)
    return () => { this.handlers = this.handlers.filter(h => h !== handler) }
  }

  disconnect() {
    if (this.reconnectTimeout) clearTimeout(this.reconnectTimeout)
    this.reconnectTimeout = null
    this.ws?.close()
    this.ws = null
    this.onStatusChange?.(false)
  }
}

export const wsManager = new WebSocketManager()
