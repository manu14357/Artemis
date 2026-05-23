'use client';
/**
 * NodeStatus.tsx
 * Grid of sensor-node health cards, polled from GET /nodes every 5 s.
 * Uses an AbortController so in-flight fetches are cancelled on unmount.
 */
import { useEffect, useRef, useState } from 'react';
import type { NodeStatus as NS } from '../types';

// NEXT_PUBLIC_* vars are inlined at build time; fallback covers local dev.
const HUB_URL =
  process.env.NEXT_PUBLIC_HUB_URL ?? 'http://localhost:8080';

function usePollNodes(intervalMs = 5000): NS[] {
  const [nodes, setNodes] = useState<NS[]>([]);
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    async function fetchNodes() {
      // Cancel any previous in-flight request before starting a new one
      controllerRef.current?.abort();
      controllerRef.current = new AbortController();
      try {
        const r = await fetch(`${HUB_URL}/nodes`, {
          signal: controllerRef.current.signal,
        });
        if (r.ok) setNodes((await r.json()) as NS[]);
      } catch (err) {
        // AbortError is expected on unmount / interval reset — ignore silently.
        // Any other error means the hub is unreachable.
        if (err instanceof Error && err.name !== 'AbortError') {
          // hub offline — keep stale nodes displayed
        }
      }
    }

    fetchNodes();
    const id = setInterval(fetchNodes, intervalMs);

    return () => {
      clearInterval(id);
      controllerRef.current?.abort();
    };
  }, [intervalMs]);

  return nodes;
}

function Pill({ label, ok }: { label: string; ok: boolean }) {
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '2px 7px',
        borderRadius: 12,
        fontSize: 10,
        fontWeight: 700,
        marginRight: 4,
        marginBottom: 2,
        background: ok ? '#14532d' : '#1e293b',
        color: ok ? '#86efac' : '#475569',
        letterSpacing: 0.5,
      }}
    >
      {label.toUpperCase()}
    </span>
  );
}

export default function NodeStatus() {
  const nodes = usePollNodes();

  if (nodes.length === 0) {
    return (
      <div style={{ color: '#64748b', padding: 16, textAlign: 'center' }}>
        No nodes connected
      </div>
    );
  }

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
        gap: 10,
      }}
    >
      {nodes.map((n) => (
        <div
          key={n.node_id}
          style={{
            background: '#0d1117',
            border: `1px solid ${n.online ? '#1d4ed8' : '#374151'}`,
            borderRadius: 8,
            padding: 12,
          }}
        >
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              marginBottom: 6,
            }}
          >
            <span style={{ fontWeight: 700, fontSize: 13 }}>{n.node_id}</span>
            <span
              style={{ fontSize: 11, color: n.online ? '#22c55e' : '#ef4444' }}
            >
              {n.online ? '● ONLINE' : '○ OFFLINE'}
            </span>
          </div>
          <div style={{ fontSize: 11, color: '#64748b', marginBottom: 6 }}>
            {n.location.lat.toFixed(4)}, {n.location.lon.toFixed(4)} ·{' '}
            {n.location.alt_m}m
          </div>
          <div style={{ marginBottom: 6 }}>
            {['rf', 'acoustic', 'radar', 'optical'].map((s) => (
              <Pill key={s} label={s} ok={n.sensors_active.includes(s)} />
            ))}
          </div>
          <div style={{ display: 'flex', gap: 12, fontSize: 11, color: '#94a3b8' }}>
            <span>CPU {n.cpu_percent.toFixed(0)}%</span>
            <span>MEM {n.mem_percent.toFixed(0)}%</span>
          </div>
        </div>
      ))}
    </div>
  );
}
