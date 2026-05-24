'use client';
/**
 * EngagementHistory.tsx
 * Scrollable list of recent engagement commands dispatched by the hub,
 * polled from GET /engagements every 5 s.
 *
 * Mirrors the usePollNodes pattern from NodeStatus.tsx.
 */
import { useEffect, useRef, useState } from 'react';
import type { Engagement, EngagementTier } from '../types';

const HUB_URL = process.env.NEXT_PUBLIC_HUB_URL ?? 'http://localhost:8080';

// ── Tier colour palette ────────────────────────────────────────────────────
const TIER_COLOUR: Record<EngagementTier, { bg: string; label: string }> = {
  ignore:       { bg: '#334155', label: 'IGNORE' },
  track_only:   { bg: '#1d4ed8', label: 'TRACK' },
  engage_soft:  { bg: '#b45309', label: 'SOFT' },
  engage_hard:  { bg: '#be123c', label: 'HARD' },
};

function timeAgo(epochSeconds: number): string {
  const diff = Math.floor(Date.now() / 1000 - epochSeconds);
  if (diff < 0)    return 'just now';
  if (diff < 60)   return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return `${Math.floor(diff / 3600)}h ago`;
}

// ── Poll hook ─────────────────────────────────────────────────────────────
function usePollEngagements(intervalMs = 5000): Engagement[] {
  const [engagements, setEngagements] = useState<Engagement[]>([]);
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    async function fetchEngagements() {
      controllerRef.current?.abort();
      controllerRef.current = new AbortController();
      try {
        const r = await fetch(`${HUB_URL}/engagements?limit=200`, {
          signal: controllerRef.current.signal,
        });
        if (r.ok) {
          const json = await r.json();
          setEngagements(json.engagements ?? []);
        }
      } catch (err) {
        if (err instanceof Error && err.name !== 'AbortError') {
          // Hub offline — keep stale list
        }
      }
    }

    fetchEngagements();
    const id = setInterval(fetchEngagements, intervalMs);
    return () => {
      clearInterval(id);
      controllerRef.current?.abort();
    };
  }, [intervalMs]);

  return engagements;
}

// ── Row component ─────────────────────────────────────────────────────────
function EngagementRow({ eng }: { eng: Engagement }) {
  const tierStyle = TIER_COLOUR[eng.tier] ?? { bg: '#334155', label: eng.tier.toUpperCase() };
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '5px 8px',
        borderBottom: '1px solid #1e293b',
        fontSize: 11,
      }}
    >
      {/* Tier badge */}
      <span
        style={{
          padding: '2px 6px',
          borderRadius: 4,
          fontSize: 9,
          fontWeight: 700,
          letterSpacing: 0.5,
          background: tierStyle.bg,
          color: '#fff',
          flexShrink: 0,
          minWidth: 42,
          textAlign: 'center',
        }}
      >
        {tierStyle.label}
      </span>

      {/* Track + effector */}
      <span style={{ color: '#94a3b8', fontFamily: 'monospace', flexShrink: 0 }}>
        {eng.track_id}
      </span>
      <span style={{ color: '#475569', fontSize: 10 }}>→</span>
      <span style={{ color: '#64748b', fontFamily: 'monospace', flexShrink: 0 }}>
        {eng.effector_id}
      </span>

      {/* Score */}
      <span
        style={{
          marginLeft: 'auto',
          color: eng.score >= 0.8 ? '#ef4444' : eng.score >= 0.6 ? '#eab308' : '#64748b',
          fontWeight: 600,
          flexShrink: 0,
        }}
      >
        {Math.round(eng.score * 100)}%
      </span>

      {/* Time ago */}
      <span style={{ color: '#334155', fontSize: 10, flexShrink: 0, width: 48, textAlign: 'right' }}>
        {timeAgo(eng.timestamp)}
      </span>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────
export default function EngagementHistory() {
  const engagements = usePollEngagements();
  // Re-render every 10 s to update time-ago strings
  const [, tick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => tick((t) => t + 1), 10_000);
    return () => clearInterval(id);
  }, []);

  return (
    <div
      style={{
        background: '#0d1117',
        border: '1px solid #1e3a5f',
        borderRadius: 8,
        overflow: 'hidden',
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: '6px 10px',
          borderBottom: '1px solid #1e3a5f',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}
      >
        <span style={{ fontSize: 10, fontWeight: 700, color: '#475569', letterSpacing: 1 }}>
          ENGAGEMENTS
        </span>
        <span style={{ fontSize: 9, color: '#334155' }}>
          {engagements.length} record{engagements.length !== 1 ? 's' : ''}
        </span>
      </div>

      {/* Rows */}
      <div style={{ maxHeight: 500, overflowY: 'auto' }}>
        {engagements.length === 0 ? (
          <div
            style={{
              padding: '20px 10px',
              textAlign: 'center',
              color: '#334155',
              fontSize: 11,
            }}
          >
            No engagements yet
          </div>
        ) : (
          engagements.map((eng, i) => (
            <EngagementRow key={`${eng.track_id}-${eng.timestamp}-${i}`} eng={eng} />
          ))
        )}
      </div>
    </div>
  );
}
