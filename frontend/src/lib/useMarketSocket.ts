"use client";

import { useEffect, useRef, useState } from "react";
import { WS_URL } from "./api";
import type { WsMessage } from "./types";

export interface LiveQuote {
  source_id: string;
  source_symbol: string;
  observed_at: string;
  last_price: number | null;
  close_price?: number | null;
  price_change?: number | null;
  price_change_percent: number | null;
  volume: number | null;
  value?: number | null;
  transaction_count?: number | null;
  // Collector-specific context with no dedicated field (a contract's
  // display name, a market's open/closed status text, etc.) - display
  // only, shape varies per source_id/source_symbol. See docs/DATA_SOURCES.md.
  raw?: Record<string, unknown> | null;
}

export type ConnectionState = "connecting" | "open" | "closed";

interface MarketSocketState {
  connectionState: ConnectionState;
  quotes: Map<string, LiveQuote>;
  lastMessageAt: number | null;
  serverTime: string | null;
}

const MAX_BACKOFF_MS = 15000;
const HEARTBEAT_MS = 10000;
// If NOTHING arrives (not even a "pong") for this long - whether that's
// the initial snapshot right after connecting, or a heartbeat reply
// later - force a reconnect rather than sitting on a socket that looks
// "open" but is actually stuck. Longer than two heartbeat intervals so a
// single missed beat doesn't false-positive (it used to be 20s against a
// 25s ping, so a quiet market - the server only pushes changes - dropped
// and re-snapshotted every client every 20s), but bounded so a stall
// (observed in practice: collectors hammering a dead upstream network
// can transiently starve the server enough that a brand-new connection's
// first snapshot never arrives) self-heals instead of leaving the UI
// showing "connected" with no data forever.
const STALE_CONNECTION_MS = 25000;

export function quoteKey(sourceId: string, sourceSymbol: string): string {
  return `${sourceId}:${sourceSymbol}`;
}

// Human-readable contract name where the source provides one (IEE trade
// board rows: `contract`; TSETMC order-book rows: `title`), e.g.
// "بارپايه ماهانه 14050801" - symbols like IEE_POWER_CONTRACT_6289... alone
// don't tell a reader which contract they're looking at.
export function quoteDisplayName(quote: LiveQuote): string | null {
  const raw = quote.raw as { contract?: unknown; title?: unknown } | null | undefined;
  const name = raw?.contract ?? raw?.title;
  return typeof name === "string" && name ? name : null;
}

export function useMarketSocket(): MarketSocketState {
  const [connectionState, setConnectionState] = useState<ConnectionState>("connecting");
  const [quotes, setQuotes] = useState<Map<string, LiveQuote>>(new Map());
  const [lastMessageAt, setLastMessageAt] = useState<number | null>(null);
  const [serverTime, setServerTime] = useState<string | null>(null);

  const attemptRef = useRef(0);
  const socketRef = useRef<WebSocket | null>(null);
  const heartbeatRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const staleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const unmountedRef = useRef(false);

  useEffect(() => {
    unmountedRef.current = false;

    const connect = () => {
      if (unmountedRef.current) return;
      setConnectionState("connecting");

      const socket = new WebSocket(WS_URL);
      socketRef.current = socket;

      const resetStaleTimer = () => {
        if (staleTimerRef.current) clearTimeout(staleTimerRef.current);
        staleTimerRef.current = setTimeout(() => {
          socket.close(); // triggers onclose -> the usual backoff-reconnect path
        }, STALE_CONNECTION_MS);
      };

      socket.onopen = () => {
        attemptRef.current = 0;
        setConnectionState("open");
        resetStaleTimer();
        heartbeatRef.current = setInterval(() => {
          if (socket.readyState === WebSocket.OPEN) socket.send("ping");
        }, HEARTBEAT_MS);
      };

      socket.onmessage = (event) => {
        resetStaleTimer();
        if (event.data === "pong") return;
        let message: WsMessage;
        try {
          message = JSON.parse(event.data);
        } catch {
          return;
        }

        setLastMessageAt(Date.now());
        setServerTime(message.server_time);

        setQuotes((prev) => {
          const next = new Map(prev);
          for (const q of message.quotes) {
            const key = quoteKey(q.source_id, q.source_symbol);
            const existing = prev.get(key);
            // The socket joins the broadcast list before its snapshot is
            // read, so a live push can arrive first; the snapshot's older
            // row for that symbol must not overwrite the newer pushed one.
            if (existing && new Date(existing.observed_at).getTime() > new Date(q.observed_at).getTime()) continue;
            next.set(key, { ...existing, ...q });
          }
          return next;
        });
      };

      socket.onclose = () => {
        setConnectionState("closed");
        if (heartbeatRef.current) clearInterval(heartbeatRef.current);
        if (staleTimerRef.current) clearTimeout(staleTimerRef.current);
        if (unmountedRef.current) return;

        const attempt = attemptRef.current + 1;
        attemptRef.current = attempt;
        const backoff = Math.min(MAX_BACKOFF_MS, 500 * 2 ** attempt);
        const jitter = Math.random() * backoff * 0.2;
        reconnectTimerRef.current = setTimeout(connect, backoff + jitter);
      };

      socket.onerror = () => {
        socket.close();
      };
    };

    connect();

    return () => {
      unmountedRef.current = true;
      if (heartbeatRef.current) clearInterval(heartbeatRef.current);
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      if (staleTimerRef.current) clearTimeout(staleTimerRef.current);
      socketRef.current?.close();
    };
  }, []);

  return { connectionState, quotes, lastMessageAt, serverTime };
}
