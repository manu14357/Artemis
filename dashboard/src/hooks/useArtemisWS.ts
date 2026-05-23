/**
 * useArtemisWS — WebSocket hook that subscribes to ws://host/ws and
 * returns the latest threat snapshot as a reactive array.
 *
 * Next.js note: this hook must only be used in 'use client' components.
 */
import { useEffect, useRef, useState } from 'react';
import type { Threat } from '../types';

// NEXT_PUBLIC_* vars are inlined at build time; the fallback covers local dev.
const HUB_WS_URL =
  process.env.NEXT_PUBLIC_HUB_WS_URL ?? 'ws://localhost:8080/ws';
const RECONNECT_DELAY_MS = 2000;

export function useArtemisWS() {
  const [threats, setThreats]     = useState<Threat[]>([]);
  const [connected, setConnected] = useState(false);
  const wsRef    = useRef<WebSocket | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const activeRef = useRef(true);

  useEffect(() => {
    activeRef.current = true;

    function connect() {
      if (!activeRef.current) return;

      // Guard: close any stale socket before creating a new one
      const prev = wsRef.current;
      if (prev && prev.readyState !== WebSocket.CLOSED) {
        prev.close();
      }

      const ws = new WebSocket(HUB_WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        if (!activeRef.current) { ws.close(); return; }
        setConnected(true);
      };

      ws.onmessage = (evt) => {
        try {
          const data = JSON.parse(evt.data as string) as Threat[];
          if (Array.isArray(data)) setThreats(data);
        } catch {
          // malformed frame — discard silently
        }
      };

      ws.onerror = () => {
        // onerror is always followed by onclose; let onclose drive reconnect
        ws.close();
      };

      ws.onclose = () => {
        setConnected(false);
        if (activeRef.current) {
          timerRef.current = setTimeout(connect, RECONNECT_DELAY_MS);
        }
      };
    }

    connect();

    return () => {
      activeRef.current = false;
      if (timerRef.current) clearTimeout(timerRef.current);
      wsRef.current?.close();
    };
  }, []);

  function ping() {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send('ping');
    }
  }

  return { threats, connected, ping };
}
