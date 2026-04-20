import type { WebSocketMessage } from '../types';

const WS_URL = 'wss://ws.voicechatbox.com';

type MessageHandler = (message: WebSocketMessage) => void;
type StatusHandler = (connected: boolean) => void;

const MAX_BACKOFF_MS = 30000;
const INITIAL_BACKOFF_MS = 1000;

export class WebSocketClient {
  private ws: WebSocket | null = null;
  private url: string;
  private token: string;
  private onMessage: MessageHandler;
  private onStatus: StatusHandler;
  private backoffMs = INITIAL_BACKOFF_MS;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private intentionallyClosed = false;

  constructor(
    token: string,
    onMessage: MessageHandler,
    onStatus: StatusHandler,
  ) {
    this.url = `${WS_URL}?token=${encodeURIComponent(token)}`;
    this.token = token;
    this.onMessage = onMessage;
    this.onStatus = onStatus;
  }

  connect(): void {
    this.intentionallyClosed = false;
    this.cleanup();

    try {
      this.ws = new WebSocket(this.url);

      this.ws.onopen = () => {
        this.backoffMs = INITIAL_BACKOFF_MS;
        this.onStatus(true);
      };

      this.ws.onmessage = (event) => {
        try {
          const message: WebSocketMessage = JSON.parse(event.data);
          this.onMessage(message);
        } catch {
          // ignore malformed messages
        }
      };

      this.ws.onclose = () => {
        this.onStatus(false);
        if (!this.intentionallyClosed) {
          this.scheduleReconnect();
        }
      };

      this.ws.onerror = () => {
        this.ws?.close();
      };
    } catch {
      this.scheduleReconnect();
    }
  }

  disconnect(): void {
    this.intentionallyClosed = true;
    this.cleanup();
  }

  send(action: string, payload: Record<string, unknown>): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ action, ...payload }));
    }
  }

  subscribe(sessionId: string): void {
    this.send('subscribe', { session_id: sessionId });
  }

  unsubscribe(sessionId: string): void {
    this.send('unsubscribe', { session_id: sessionId });
  }

  get isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  private scheduleReconnect(): void {
    if (this.intentionallyClosed) return;

    this.reconnectTimer = setTimeout(() => {
      this.connect();
    }, this.backoffMs);

    this.backoffMs = Math.min(this.backoffMs * 2, MAX_BACKOFF_MS);
  }

  private cleanup(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.onopen = null;
      this.ws.onmessage = null;
      this.ws.onclose = null;
      this.ws.onerror = null;
      if (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING) {
        this.ws.close();
      }
      this.ws = null;
    }
  }
}
