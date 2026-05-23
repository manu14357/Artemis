'use client';
/**
 * DetectionFeed.tsx
 * Scrollable live feed of the latest threat entries, newest first.
 */
import type { Threat } from '../types';

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

function fmt(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString([], { hour12: false });
}

interface Props {
  threats: Threat[];
}

export default function DetectionFeed({ threats }: Props) {
  // Sort by timestamp descending (newest first)
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
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            fontSize: 13,
          }}
        >
          <div>
            <span
              style={{
                fontWeight: 700,
                marginRight: 8,
                fontSize: 11,
                letterSpacing: 1,
              }}
            >
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
      ))}
    </div>
  );
}
