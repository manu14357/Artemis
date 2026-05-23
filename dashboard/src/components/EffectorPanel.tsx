'use client';
/**
 * EffectorPanel.tsx
 * Engagement command panel (simulation mode only by default).
 * Posts to POST /commands/{effector_id} on the hub API.
 */
import { useState } from 'react';
import type { Threat } from '../types';

// NEXT_PUBLIC_* vars are inlined at build time; fallback covers local dev.
const HUB_URL =
  process.env.NEXT_PUBLIC_HUB_URL ?? 'http://localhost:8080';

const EFFECTORS = ['jammer-01', 'jammer-02', 'spoofer-01', 'relay-01'];

interface Props {
  threats: Threat[];
}

export default function EffectorPanel({ threats }: Props) {
  const [selectedEffector, setSelectedEffector] = useState(EFFECTORS[0]);
  const [duration, setDuration] = useState(5);
  const [lastResult, setLastResult] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const highTier = threats.filter(t => t.tier >= 4);

  async function sendCommand(action: string) {
    setLoading(true);
    setLastResult(null);
    try {
      const r = await fetch(`${HUB_URL}/commands/${selectedEffector}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, duration_s: duration }),
      });
      const j = await r.json() as { status: string };
      setLastResult(`${j.status}`);
    } catch (e) {
      setLastResult('hub unreachable');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ background: '#0d1117', borderRadius: 8, padding: 16 }}>
      <div style={{ marginBottom: 10, color: '#94a3b8', fontSize: 12 }}>
        SIMULATION MODE — commands are echoed, not executed
      </div>

      {highTier.length > 0 && (
        <div
          style={{
            background: '#7f1d1d',
            borderRadius: 6,
            padding: '6px 10px',
            marginBottom: 10,
            fontSize: 12,
            fontWeight: 700,
            color: '#fca5a5',
          }}
        >
          ⚠ {highTier.length} HIGH/CRITICAL threat{highTier.length > 1 ? 's' : ''} active
        </div>
      )}

      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 10 }}>
        <div>
          <label style={{ fontSize: 11, color: '#64748b', display: 'block', marginBottom: 4 }}>
            EFFECTOR
          </label>
          <select
            aria-label="Select effector"
            value={selectedEffector}
            onChange={e => setSelectedEffector(e.target.value)}
            style={{
              background: '#1e293b',
              color: '#e2e8f0',
              border: '1px solid #334155',
              borderRadius: 4,
              padding: '4px 8px',
              fontSize: 13,
            }}
          >
            {EFFECTORS.map(ef => (
              <option key={ef} value={ef}>{ef}</option>
            ))}
          </select>
        </div>

        <div>
          <label style={{ fontSize: 11, color: '#64748b', display: 'block', marginBottom: 4 }}>
            DURATION (s)
          </label>
          <input
            type="number"
            min={1}
            max={60}
            value={duration}
            title="Engagement duration in seconds"
            placeholder="5"
            onChange={e => setDuration(Number(e.target.value))}
            style={{
              width: 70,
              background: '#1e293b',
              color: '#e2e8f0',
              border: '1px solid #334155',
              borderRadius: 4,
              padding: '4px 8px',
              fontSize: 13,
            }}
          />
        </div>
      </div>

      <div style={{ display: 'flex', gap: 8 }}>
        <button
          onClick={() => sendCommand('activate')}
          disabled={loading}
          style={{
            background: '#1d4ed8',
            color: '#fff',
            border: 'none',
            borderRadius: 6,
            padding: '6px 14px',
            cursor: loading ? 'wait' : 'pointer',
            fontSize: 12,
            fontWeight: 700,
          }}
        >
          ACTIVATE
        </button>
        <button
          onClick={() => sendCommand('deactivate')}
          disabled={loading}
          style={{
            background: '#374151',
            color: '#e2e8f0',
            border: 'none',
            borderRadius: 6,
            padding: '6px 14px',
            cursor: loading ? 'wait' : 'pointer',
            fontSize: 12,
          }}
        >
          DEACTIVATE
        </button>
      </div>

      {lastResult && (
        <div style={{ marginTop: 8, fontSize: 11, color: '#22c55e' }}>
          ✓ {lastResult}
        </div>
      )}
    </div>
  );
}
