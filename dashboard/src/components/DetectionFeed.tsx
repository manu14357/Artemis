'use client';
/**
 * DetectionFeed.tsx
 * Scrollable live feed of the latest threat entries, newest first.
 * Shows tier badge, drone type, sensor layer pills, confidence bar, and
 * position / time metadata.
 */
import type { SensorLayer, Threat } from '../types';

const TIER_BG: Record<number, string> = {
  1: '#14532d',
  2: '#713f12',
  3: '#7c2d12',
  4: '#7f1d1d',
  5: '#4c0519',
};

const TIER_LABEL: Record<number, string> = {
  1: 'MINIMAL',
  2: 'LOW',
  3: 'ELEVATED',
  4: 'HIGH',
  5: 'CRITICAL',
};

const LAYER_COLOUR: Record<SensorLayer, string> = {
  rf:       '#1d4ed8',   // blue
  acoustic: '#15803d',   // green
  radar:    '#b45309',   // amber
  optical:  '#7c3aed',   // violet
};

function LayerPill({ layer, active }: { layer: SensorLayer; active: boolean }) {
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '1px 6px',
        borderRadius: 10,
        fontSize: 9,
        fontWeight: 700,
        marginRight: 3,
        letterSpacing: 0.5,
        background: active ? LAYER_COLOUR[layer] : '#1e293b',
        color: active ? '#fff' : '#475569',
        opacity: active ? 1 : 0.5,
      }}
    >
      {layer.toUpperCase()}
    </span>
  );
}

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const colour = pct >= 75 ? '#22c55e' : pct >= 40 ? '#eab308' : '#ef4444';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 4 }}>
      <div
        style={{
          flex: 1,
          height: 3,
          background: '#1e293b',
          borderRadius: 2,
          overflow: 'hidden',
        }}
      >
        <div
          style={{ width: `${pct}%`, height: '100%', background: colour, borderRadius: 2 }}
        />
      </div>
      <span style={{ fontSize: 9, color: colour, minWidth: 28 }}>{pct}%</span>
    </div>
  );
}

function fmt(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString([], { hour12: false });
}

const ALL_LAYERS: SensorLayer[] = ['rf', 'acoustic', 'radar', 'optical'];

interface Props {
  threats: Threat[];
}

export default function DetectionFeed({ threats }: Props) {
  const sorted = [...threats].sort((a, b) => b.timestamp - a.timestamp);

  return (
    <div
      style={{
        overflowY: 'auto',
        maxHeight: 400,
        background: '#0d1117',
        borderRadius: 8,
        padding: 8,
      }}
    >
      {sorted.length === 0 && (
        <p style={{ color: '#64748b', textAlign: 'center', padding: 24 }}>
          No active threats
        </p>
      )}
      {sorted.map((t) => (
        <div
          key={t.threat_id}
          style={{
            background: TIER_BG[t.tier] ?? '#1e293b',
            borderRadius: 6,
            padding: '8px 12px',
            marginBottom: 6,
            fontSize: 13,
          }}
        >
          {/* Row 1: tier badge + drone type + swarm + time */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <span style={{ fontWeight: 700, marginRight: 8, fontSize: 11, letterSpacing: 1 }}>
                T{t.tier} {TIER_LABEL[t.tier] ?? 'UNKNOWN'}
              </span>
              <span style={{ color: '#94a3b8' }}>{t.drone_type}</span>
              {t.swarm_id !== null && (
                <span style={{ marginLeft: 8, color: '#fbbf24', fontSize: 11 }}>
                  SWARM ×{t.swarm_size}
                </span>
              )}
            </div>
            <div style={{ textAlign: 'right', color: '#64748b', fontSize: 11 }}>
              <div>
                ({Math.round(t.position.x)}m, {Math.round(t.position.y)}m,{' '}
                {Math.round(t.position.z)}m)
              </div>
              <div>{fmt(t.timestamp)}</div>
            </div>
          </div>

          {/* Row 2: sensor layer pills */}
          <div style={{ marginTop: 5 }}>
            {ALL_LAYERS.map((l) => (
              <LayerPill key={l} layer={l} active={t.sensor_layers.includes(l)} />
            ))}
          </div>

          {/* Row 3: confidence bar */}
          <ConfidenceBar value={t.score ?? t.confidence} />
        </div>
      ))}
    </div>
  );
}
