/**
 * The realtime socket, as a small state machine.
 *
 * Responsibilities kept here so no screen has to think about them: minting a fresh ticket
 * before every connect (they expire in a minute), re-subscribing on every open, parsing
 * frames, and reconnecting with capped exponential backoff. The socket is an *accelerator* —
 * if it never connects, the app still works on REST polling — so every failure path is
 * silent and simply schedules another attempt.
 *
 * The transport is injected, which keeps this unit-testable without a real WebSocket.
 */

import type { RealtimeEvent } from '@study-league/api-client';

/** The slice of the WebSocket API this client uses. */
export interface RealtimeSocket {
  send(data: string): void;
  close(): void;
  onopen: (() => void) | null;
  onmessage: ((event: { data: unknown }) => void) | null;
  onclose: (() => void) | null;
  onerror: ((error: unknown) => void) | null;
}

export type SocketFactory = (url: string) => RealtimeSocket;

export interface RealtimeClientOptions {
  /** Base socket URL, e.g. ws://host:8000/api/v1/realtime */
  url: string;
  /** Mints a fresh, short-lived ticket. Called before every connection attempt. */
  mintTicket: () => Promise<string>;
  onEvent: (event: RealtimeEvent) => void;
  socketFactory: SocketFactory;
  /** Overridable for tests; defaults to capped exponential backoff. */
  backoffMs?: (attempt: number) => number;
  /** Scheduler seam so tests do not depend on real timers. */
  schedule?: (fn: () => void, delayMs: number) => void;
}

const MAX_BACKOFF_MS = 30_000;

function defaultBackoff(attempt: number): number {
  // 1s, 2s, 4s … capped, with jitter so a server restart doesn't stampede.
  const base = Math.min(MAX_BACKOFF_MS, 1000 * 2 ** Math.max(0, attempt - 1));
  return Math.round(base * (0.5 + Math.random() * 0.5));
}

export class RealtimeClient {
  private readonly options: RealtimeClientOptions;
  private socket: RealtimeSocket | null = null;
  private channels: string[] = [];
  private attempt = 0;
  private stopped = false;

  constructor(options: RealtimeClientOptions) {
    this.options = options;
  }

  get isOpen(): boolean {
    return this.socket !== null;
  }

  /** Set the channels to subscribe to; re-sends immediately if already connected. */
  setChannels(channels: string[]): void {
    this.channels = [...channels];
    this.sendSubscribe();
  }

  async connect(): Promise<void> {
    if (this.stopped || this.socket) return;

    let ticket: string;
    try {
      ticket = await this.options.mintTicket();
    } catch {
      this.scheduleReconnect();
      return;
    }
    if (this.stopped) return;

    const separator = this.options.url.includes('?') ? '&' : '?';
    const socket = this.options.socketFactory(
      `${this.options.url}${separator}token=${encodeURIComponent(ticket)}`,
    );
    this.socket = socket;

    socket.onopen = () => {
      this.attempt = 0;
      this.sendSubscribe();
    };
    socket.onmessage = (message) => this.handleMessage(message.data);
    socket.onerror = () => {
      // `onclose` always follows; reconnection is handled there.
    };
    socket.onclose = () => {
      this.socket = null;
      this.scheduleReconnect();
    };
  }

  close(): void {
    this.stopped = true;
    const socket = this.socket;
    this.socket = null;
    if (socket) {
      socket.onclose = null; // a deliberate close must not trigger a reconnect
      socket.close();
    }
  }

  private handleMessage(data: unknown): void {
    if (typeof data !== 'string') return;
    let parsed: unknown;
    try {
      parsed = JSON.parse(data);
    } catch {
      return; // a malformed frame is dropped, never thrown
    }
    if (parsed && typeof parsed === 'object' && 'event' in parsed) {
      this.options.onEvent(parsed as RealtimeEvent);
    }
  }

  private sendSubscribe(): void {
    if (!this.socket || this.channels.length === 0) return;
    try {
      this.socket.send(JSON.stringify({ op: 'subscribe', channels: this.channels }));
    } catch {
      // The close handler will reconnect.
    }
  }

  private scheduleReconnect(): void {
    if (this.stopped) return;
    this.attempt += 1;
    const delay = (this.options.backoffMs ?? defaultBackoff)(this.attempt);
    const schedule = this.options.schedule ?? ((fn, ms) => setTimeout(fn, ms));
    schedule(() => {
      void this.connect();
    }, delay);
  }
}
