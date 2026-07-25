/**
 * The realtime socket state machine: ticket-per-connect, subscribe-on-open, event parsing,
 * and reconnect-with-backoff. A fake transport stands in for the WebSocket so the behaviour
 * is tested without any network or real timers.
 */

import type { RealtimeEvent } from '@study-league/api-client';

import { RealtimeClient, type RealtimeSocket } from '../RealtimeClient';
import { realtimeUrl } from '../useRealtime';

class FakeSocket implements RealtimeSocket {
  sent: string[] = [];
  closed = false;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: ((error: unknown) => void) | null = null;

  constructor(readonly url: string) {}

  send(data: string): void {
    this.sent.push(data);
  }

  close(): void {
    this.closed = true;
  }
}

function build(overrides: { mintTicket?: () => Promise<string> } = {}) {
  const sockets: FakeSocket[] = [];
  const events: RealtimeEvent[] = [];
  const scheduled: (() => void)[] = [];

  const client = new RealtimeClient({
    url: 'ws://host/api/v1/realtime',
    mintTicket: overrides.mintTicket ?? (() => Promise.resolve('TICKET')),
    onEvent: (event) => events.push(event),
    socketFactory: (url) => {
      const socket = new FakeSocket(url);
      sockets.push(socket);
      return socket;
    },
    backoffMs: () => 1,
    schedule: (fn) => scheduled.push(fn),
  });

  return { client, sockets, events, scheduled };
}

describe('realtimeUrl', () => {
  it('converts an http api base into a ws socket url', () => {
    expect(realtimeUrl('http://localhost:8000/api/v1')).toBe('ws://localhost:8000/api/v1/realtime');
    expect(realtimeUrl('https://api.example.com/api/v1')).toBe(
      'wss://api.example.com/api/v1/realtime',
    );
  });
});

describe('RealtimeClient', () => {
  it('opens with a freshly minted ticket in the query string', async () => {
    const { client, sockets } = build();
    await client.connect();

    expect(sockets).toHaveLength(1);
    expect(sockets[0]!.url).toBe('ws://host/api/v1/realtime?token=TICKET');
    client.close();
  });

  it('subscribes to the configured channels once open', async () => {
    const { client, sockets } = build();
    client.setChannels(['friends', 'group:g1']);
    await client.connect();
    sockets[0]!.onopen?.();

    expect(JSON.parse(sockets[0]!.sent[0]!)).toEqual({
      op: 'subscribe',
      channels: ['friends', 'group:g1'],
    });
    client.close();
  });

  it('re-subscribes immediately when channels change while connected', async () => {
    const { client, sockets } = build();
    client.setChannels(['friends']);
    await client.connect();
    sockets[0]!.onopen?.();

    client.setChannels(['friends', 'group:new']);
    const last = JSON.parse(sockets[0]!.sent[sockets[0]!.sent.length - 1]!);
    expect(last.channels).toEqual(['friends', 'group:new']);
    client.close();
  });

  it('forwards parsed events and ignores malformed frames', async () => {
    const { client, sockets, events } = build();
    await client.connect();

    sockets[0]!.onmessage?.({ data: 'not json' });
    sockets[0]!.onmessage?.({ data: JSON.stringify({ nope: true }) });
    sockets[0]!.onmessage?.({
      data: JSON.stringify({ event: 'pong' }),
    });

    expect(events).toEqual([{ event: 'pong' }]);
    client.close();
  });

  it('reconnects after an unexpected close', async () => {
    const { client, sockets, scheduled } = build();
    await client.connect();
    sockets[0]!.onclose?.();

    expect(scheduled).toHaveLength(1);
    scheduled[0]!(); // run the scheduled reconnect
    await Promise.resolve(); // let the async connect settle
    await Promise.resolve();

    expect(sockets).toHaveLength(2);
    client.close();
  });

  it('does not reconnect after a deliberate close', async () => {
    const { client, sockets, scheduled } = build();
    await client.connect();
    client.close();

    expect(sockets[0]!.closed).toBe(true);
    expect(scheduled).toHaveLength(0);
  });

  it('schedules a retry when the ticket cannot be minted', async () => {
    const { client, sockets, scheduled } = build({
      mintTicket: () => Promise.reject(new Error('offline')),
    });
    await client.connect();

    expect(sockets).toHaveLength(0);
    expect(scheduled).toHaveLength(1);
    client.close();
  });
});
