'use client';
/**
 * components/NodeConfig.tsx — Per-node sensor configuration display
 *
 * Fetches GET /nodes from the hub and renders a card per node
 * showing location, active sensors, health metrics, and sensor
 * thresholds sourced from the node's last heartbeat payload.
 *
 * Write-back is not implemented (would require a hub API extension);
 * all values shown are read-only from the hub's node registry.
 */
import { useCallback, useEffect, useState } from 'react';
import type { NodeStatus, SensorLayer } from '../types';

const HUB_URL = process.env.NEXT_PUBLIC_HUB_URL ?? 'http://localhost:8080';

const LAYER_COLOR: Record<SensorLayer, string> = {
  rf:       '#3b82f6',
  acoustic: '#10b981',
  radar:    '#f59e0b',
  optical:  '#a855f7',
};

function SensorPill({ layer, active }: { layer: SensorLayer; active: boolean }) {
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '2px 8px',
        borderRadius: 10,
        fontSize: 9,
        fontWeight: 700,
        background: active ? LAYER_COLOR[layer] + '22' : '#1e293b',
        color: active ? LAYER_COLOR[layer] : '#475569',
        border: `1px solid ${active ? LAYER_COLOR[layer] + '66' : '#334155'}`,
        marginRight: 4,
        letterSpacing: 0.5,
      }}
    >
      {layer.toUpperCase()}
    </span>
  );
}

function MeterBar({ value, color = '#3b82f6', label }: { value: number; color?: string; label: string }) {
  const clamp = Math.min(Math.max(value, 0), 100);
  const warn = clamp > 80;
  const barColor = warn ? '#ef4444' : color;
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: '#64748b', marginBottom: 3 }}>
        <span>{label}</span>
        <span style={{ fontFamily: 'monospace', color: warn ? '#fca5a5' : '#94a3b8' }}>{clamp.toFixed(1)}%</span>
      </div>
      <div style={{ height: 4, background: '#1e293b', borderRadius: 2 }}>
        <div style={{ width: `${clamp}%`, height: '100%', background: barColor, borderRadius: 2, transition: 'width 0.4s' }} />
      </div>
    </div>
  );
}

function NodeCard({ node }: { node: NodeStatus }) {
  const age = Date.now() / 1000 - node.last_heartbeat;
  const stale = age > 10;

  return (
    <div
      style={{
        background: '#0d1117',
        borderRadius: 8,
        padding: 16,
        border: `1px solid ${node.online ? '#1e3a5f' : '#3b1111'}`,
        position: 'relative',
      }}
    >
      {/* Title row */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <span style={{ fontSize: 13, fontWeight: 800, color: '#e2e8f0', fontFamily: 'monospace' }}>
          {node.node_id}
        </span>
        <span
          style={{
            fontSize: 9,
            fontWeight: 700,
            padding: '2px 8px',
            borderRadius: 4,
            background: node.online ? '#14532d' : '#7f1d1d',
            color: node.online ? '#86efac' : '#fca5a5',
          }}
        >
          {node.online ? 'ONLINE' : 'OFFLINE'}
        </span>
      </div>

      {/* Location */}
      <div style={{ fontSize: 11, color: '#64748b', marginBottom: 10, fontFamily: 'monospace' }}>
        {node.location.lat.toFixed(5)}° N &nbsp;
        {node.location.lon.toFixed(5)}° E &nbsp;
        {node.location.alt_m.toFixed(0)}m ASL
      </div>

      {/* Sensor pills */}
      <div style={{ marginBottom: 14 }}>
        {(['rf', 'acoustic', 'radar', 'optical'] as SensorLayer[]).map(l => (
          <SensorPill key={l} layer={l} active={node.sensors_active.includes(l)} />
        ))}
      </div>

      {/* CPU + memory bars */}
      <MeterBar value={node.cpu_percent} label="CPU" color="#3b82f6" />
      <MeterBar value={node.mem_percent} label="Memory" color="#a855f7" />

      {/* Heartbeat age */}
      <div style={{ fontSize: 10, color: stale ? '#fca5a5' : '#475569', marginTop: 8 }}>
        Heartbeat {stale ? `STALE (${age.toFixed(0)}s ago)` : `${age.toFixed(1)}s ago`}
      </div>
    </div>
  );
}

interface NodeConfigProps {
  /** If provided, only show this node */
  filterNodeId?: string;
  /** Show compact single-row layout */
  compact?: boolean;
}

export function NodeConfig({ filterNodeId, compact = false }: NodeConfigProps) {
  const [nodes, setNodes] = useState<NodeStatus[]>([]);
  const [error, setError] = useState<string | null>(null);

  const fetchNodes = useCallback(async () => {
    try {
      const res = await fetch(`${HUB_URL}/nodes`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json() as { nodes: NodeStatus[] };
      setNodes(data.nodes ?? []);
      setError(null);
    } catch (e) {
      setError(`Hub unreachable: ${(e as Error).message}`);
    }
  }, []);

  useEffect(() => {
    fetchNodes();
    const id = setInterval(fetchNodes, 5000);
    return () => clearInterval(id);
  }, [fetchNodes]);

  const displayed = filterNodeId
    ? nodes.filter(n => n.node_id === filterNodeId)
    : nodes;

  if (error) {
    return (
      <div style={{ color: '#fca5a5', fontSize: 12, padding: 8 }}>
        {error}
      </div>
    );
  }

  if (nodes.length === 0) {
    return (
      <div style={{ color: '#475569', fontSize: 12, padding: 8 }}>
        No sensor nodes connected
      </div>
    );
  }

  return (
    <div
      style={{
        display: 'grid',
        gap: 12,
        gridTemplateColumns: compact
          ? '1fr'
          : 'repeat(auto-fill, minmax(280px, 1fr))',
      }}
    >
      {displayed.map(node => (
        <NodeCard key={node.node_id} node={node} />
      ))}
    </div>
  );
}
