'use client';
/**
 * DetectionFeed.tsx
 * Scrollable live feed of the latest threat entries, newest first.
 * Shows tier badge, drone type, sensor layer pills, confidence bar, and
 * position / time metadata.
 *
 * Historical replay: pass `threatHistory` ref from useArtemisWS to enable
 * a time-slider that scrubs through the last ~1 h of snapshots.
 */
import { useState, type MutableRefObject } from 'react';
import type { ThreatSnapshot } from '../hooks/useArtemisWS';
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
  /** Ring-buffer ref from useArtemisWS — enables replay time-slider. */
  threatHistory?: MutableRefObject<ThreatSnapshot[]>;
}

export default function DetectionFeed({ threats, threatHistory }: Props) {
  const [replayMode, setReplayMode] = useState(false);
  const [replayPct, setReplayPct]   = useState(100); // 0 = oldest, 100 = newest

  // Determine which threats to show
  let displayThreats = threats;
  let replayTime: number | null = null;
  if (replayMode && threatHistory) {
    const hist = threatHistory.current;
    if (hist.length > 0) {
      const idx = Math.min(
        Math.floor((replayPct / 100) * (hist.length - 1)),
        hist.length - 1,
      );
      displayThreats = hist[idx].threats;
      replayTime = hist[idx].ts;
    }
  }

  const sorted = [...displayThreats].sort((a, b) => b.timestamp - a.timestamp);

  const hasHistory = threatHistory && threatHistory.current.length > 1;

  return (
    <div style={{ background: '#0d1117', borderRadius: 8, overflow: 'hidden' }}>
      {/* ── Replay toolbar ── */}
      {hasHistory && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '6px 10px',
            borderBottom: '1px solid #1e293b',
            background: replayMode ? '#0f172a' : 'transparent',
          }}
        >
          <button
            onClick={() => { setReplayMode(false); setReplayPct(100); }}
            style={{
              fontSize: 9,
              fontWeight: 700,
              padding: '2px 7px',
              borderRadius: 4,
              border: `1px solid ${!replayMode ? '#22c55e' : '#334155'}`,
              background: !replayMode ? '#14532d' : 'transparent',
              color: !replayMode ? '#86efac' : '#64748b',
              cursor: 'pointer',
            }}
          >
            ● LIVE
          </button>
          <button
            onClick={() => setReplayMode(true)}
            style={{
              fontSize: 9,
              fontWeight: 700,
              padding: '2px 7px',
              borderRadius: 4,
              border: `1px solid ${replayMode ? '#f59e0b' : '#334155'}`,
              background: replayMode ? '#713f12' : 'transparent',
              color: replayMode ? '#fcd34d' : '#64748b',
              cursor: 'pointer',
            }}
          >
            ◀ REPLAY
          </button>
          {replayMode && (
            <>
              <input
                type="range"
                min={0}
                max={100}
                value={replayPct}
                onChange={e => setReplayPct(Number(e.target.value))}
                style={{ flex: 1, accentColor: '#f59e0b', height: 4 }}
              />
              <span style={{ fontSize: 9, color: '#f59e0b', fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
                {replayTime
                  ? new Date(replayTime * 1000).toLocaleTimeString([], { hour12: false })
                  : '--:--:--'}
              </span>
            </>
          )}
        </div>
      )}

      {/* ── Feed items ── */}
    <div
      style={{
        overflowY: 'auto',
        maxHeight: 400,
        padding: 8,
      }}
    >
      {sorted.length === 0 && (
        <p style={{ color: '#64748b', textAlign: 'center', padding: 24 }}>
          {replayMode ? 'No threats in selected snapshot' : 'No active threats'}
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
    </div>
  );
}
