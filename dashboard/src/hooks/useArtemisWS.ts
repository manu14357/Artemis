/**
 * useArtemisWS — WebSocket hook that subscribes to ws://host/ws and
 * returns the latest threat snapshot as a reactive array.
 *
 * Reconnection: exponential backoff starting at 100 ms, capped at 30 s.
 * Max retries: 10 before giving up and calling onMaxRetries.
 * Heartbeat: sends "ping" every 15 s while connected.
 *
 * Next.js note: this hook must only be used in 'use client' components.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import type { Threat } from '../types';

// NEXT_PUBLIC_* vars are inlined at build time; the fallback covers local dev.
const HUB_WS_URL =
  process.env.NEXT_PUBLIC_HUB_WS_URL ?? 'ws://localhost:8080/ws';

const BACKOFF_BASE_MS    = 100;
const BACKOFF_MAX_MS     = 30_000;
const MAX_RETRIES        = 10;
const HEARTBEAT_INTERVAL = 15_000;   // ms
/** Max historical snapshots kept in memory (~1 h at 1 update/s). */
const MAX_HISTORY        = 3_600;

export interface ThreatSnapshot {
  ts: number;      // Unix epoch seconds
  threats: Threat[];
}

export function useArtemisWS(onMaxRetries?: () => void) {
  const [threats, setThreats]     = useState<Threat[]>([]);
  const [connected, setConnected] = useState(false);
  const wsRef         = useRef<WebSocket | null>(null);
  const timerRef      = useRef<ReturnType<typeof setTimeout> | null>(null);
  const heartbeatRef  = useRef<ReturnType<typeof setInterval> | null>(null);
  const activeRef     = useRef(true);
  const attemptRef    = useRef(0);
  /** Ring-buffer of past threat snapshots — mutations do NOT trigger re-renders. */
  const threatHistory = useRef<ThreatSnapshot[]>([]);
  const onMaxRetriesRef = useRef(onMaxRetries);
  onMaxRetriesRef.current = onMaxRetries;

  const clearHeartbeat = () => {
    if (heartbeatRef.current) {
      clearInterval(heartbeatRef.current);
      heartbeatRef.current = null;
    }
  };

  const startHeartbeat = (ws: WebSocket) => {
    clearHeartbeat();
    heartbeatRef.current = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send('ping');
      }
    }, HEARTBEAT_INTERVAL);
  };

  const connect = useCallback(() => {
    if (!activeRef.current) return;

    // Give up after MAX_RETRIES consecutive failures
    if (attemptRef.current >= MAX_RETRIES) {
      onMaxRetriesRef.current?.();
      return;
    }

    // Guard: close any stale socket before creating a new one
    const prev = wsRef.current;
    if (prev && prev.readyState !== WebSocket.CLOSED) {
      prev.close();
    }

    const ws = new WebSocket(HUB_WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      if (!activeRef.current) { ws.close(); return; }
      attemptRef.current = 0;   // reset backoff on successful connect
      setConnected(true);
      startHeartbeat(ws);
    };

    ws.onmessage = (evt) => {
      try {
        const data = JSON.parse(evt.data as string) as Threat[];
        if (Array.isArray(data)) {
          setThreats(data);
          // Append to ring buffer — do NOT setState to avoid re-renders per frame
          threatHistory.current.push({ ts: Date.now() / 1000, threats: data });
          if (threatHistory.current.length > MAX_HISTORY) {
            threatHistory.current.shift();
          }
        }
      } catch {
        // malformed frame — discard silently
      }
    };

    ws.onerror = () => {
      // onerror is always followed by onclose; let onclose drive reconnect
      ws.close();
    };

    ws.onclose = () => {
      clearHeartbeat();
      setConnected(false);
      if (activeRef.current) {
        attemptRef.current += 1;
        const delay = Math.min(
          BACKOFF_BASE_MS * 2 ** (attemptRef.current - 1),
          BACKOFF_MAX_MS,
        );
        timerRef.current = setTimeout(connect, delay);
      }
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    activeRef.current = true;
    attemptRef.current = 0;
    connect();

    return () => {
      activeRef.current = false;
      clearHeartbeat();
      if (timerRef.current) clearTimeout(timerRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  function ping() {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send('ping');
    }
  }

  return { threats, connected, ping, retries: attemptRef, threatHistory };
}
