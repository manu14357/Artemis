'use client';
/**
 * NodeStatus.tsx
 * Grid of sensor-node health cards, polled from GET /nodes every 5 s.
 * Uses an AbortController so in-flight fetches are cancelled on unmount.
 */
import { useEffect, useRef, useState } from 'react';
import type { NodeStatus as NS, SensorLayer } from '../types';

const HUB_URL =
  process.env.NEXT_PUBLIC_HUB_URL ?? 'http://localhost:8080';

function timeAgo(epochSeconds: number): string {
  const diff = Math.floor(Date.now() / 1000 - epochSeconds);
  if (diff < 0)  return 'just now';
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return `${Math.floor(diff / 3600)}h ago`;
}

function usePollNodes(intervalMs = 5000): NS[] {
  const [nodes, setNodes] = useState<NS[]>([]);
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    async function fetchNodes() {
      controllerRef.current?.abort();
      controllerRef.current = new AbortController();
      try {
        const r = await fetch(`${HUB_URL}/nodes`, {
          signal: controllerRef.current.signal,
        });
        if (r.ok) setNodes((await r.json()) as NS[]);
      } catch (err) {
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

const LAYER_COLOUR: Record<SensorLayer, string> = {
  rf:       '#1d4ed8',
  acoustic: '#15803d',
  radar:    '#b45309',
  optical:  '#7c3aed',
};

function Pill({ label, ok }: { label: string; ok: boolean }) {
  const colour = LAYER_COLOUR[label as SensorLayer] ?? '#334155';
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
        background: ok ? colour : '#1e293b',
        color: ok ? '#fff' : '#475569',
        opacity: ok ? 1 : 0.5,
        letterSpacing: 0.5,
      }}
    >
      {label.toUpperCase()}
    </span>
  );
}

function CpuBar({ pct, label }: { pct: number; label: string }) {
  const colour = pct > 85 ? '#ef4444' : pct > 60 ? '#eab308' : '#22c55e';
  return (
    <div style={{ flex: 1 }}>
      <div style={{ fontSize: 10, color: '#64748b', marginBottom: 2 }}>{label} {Math.round(pct)}%</div>
      <div style={{ height: 3, background: '#1e293b', borderRadius: 2, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: colour }} />
      </div>
    </div>
  );
}

export default function NodeStatus() {
  const nodes = usePollNodes();
  // Re-render every 10s so time-ago strings update
  const [, tick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => tick(t => t + 1), 10_000);
    return () => clearInterval(id);
  }, []);

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
      {nodes.map((n) => {
        const stale = !n.online || (Date.now() / 1000 - n.last_heartbeat) > 30;
        return (
          <div
            key={n.node_id}
            style={{
              background: '#0d1117',
              border: `1px solid ${n.online ? '#1d4ed8' : '#374151'}`,
              borderRadius: 8,
              padding: 12,
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
              <span style={{ fontWeight: 700, fontSize: 13 }}>{n.node_id}</span>
              <span style={{ fontSize: 11, color: n.online ? '#22c55e' : '#ef4444' }}>
                {n.online ? '● ONLINE' : '○ OFFLINE'}
              </span>
            </div>
            <div style={{ fontSize: 11, color: '#64748b', marginBottom: 6 }}>
              {n.location.lat.toFixed(4)}, {n.location.lon.toFixed(4)} · {n.location.alt_m}m
            </div>
            <div style={{ marginBottom: 8 }}>
              {(['rf', 'acoustic', 'radar', 'optical'] as SensorLayer[]).map((s) => (
                <Pill key={s} label={s} ok={n.sensors_active.includes(s)} />
              ))}
            </div>
            <div style={{ display: 'flex', gap: 8, marginBottom: 6 }}>
              <CpuBar pct={n.cpu_percent} label="CPU" />
              <CpuBar pct={n.mem_percent} label="MEM" />
            </div>
            <div style={{ fontSize: 10, color: stale ? '#ef4444' : '#475569' }}>
              ↻ {timeAgo(n.last_heartbeat)}
            </div>
          </div>
        );
      })}
    </div>
  );
}
