'use client';
/**
 * EffectorPanel.tsx
 * Engagement command panel (simulation mode only by default).
 * Posts to POST /commands/{effector_id} on the hub API.
 *
 * Bug fix: effector list is now dynamically fetched from GET /effectors
 * instead of being hardcoded.  A confirmation modal is shown before dispatch.
 */
import { useState } from 'react';
import type { Threat } from '../types';
import { usePollEffectors } from '../hooks/usePollEffectors';

// NEXT_PUBLIC_* vars are inlined at build time; fallback covers local dev.
const HUB_URL =
  process.env.NEXT_PUBLIC_HUB_URL ?? 'http://localhost:8080';

interface Props {
  threats: Threat[];
}

export default function EffectorPanel({ threats }: Props) {
  const { effectors, loading: effLoading } = usePollEffectors(10_000);
  const [selectedEffector, setSelectedEffector] = useState('');
  const [duration, setDuration] = useState(5);
  const [lastResult, setLastResult] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  // Confirmation modal state
  const [pendingAction, setPendingAction] = useState<string | null>(null);

  const highTier = threats.filter(t => t.tier >= 4);
  const effectiveEffector = selectedEffector || effectors[0] || '';

  async function sendCommand(action: string) {
    setLoading(true);
    setLastResult(null);
    setPendingAction(null);
    try {
      const r = await fetch(`${HUB_URL}/commands/${effectiveEffector}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, duration_s: duration }),
      });
      const j = await r.json() as { status: string };
      setLastResult(`${j.status}`);
    } catch {
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
            value={effectiveEffector}
            onChange={e => setSelectedEffector(e.target.value)}
            disabled={effLoading || effectors.length === 0}
            style={{
              background: '#1e293b',
              color: '#e2e8f0',
              border: '1px solid #334155',
              borderRadius: 4,
              padding: '4px 8px',
              fontSize: 13,
            }}
          >
            {effectors.length === 0
              ? <option value="">Loading...</option>
              : effectors.map(ef => (
                  <option key={ef} value={ef}>{ef}</option>
                ))
            }
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
          onClick={() => setPendingAction('activate')}
          disabled={loading || effectors.length === 0}
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
          onClick={() => setPendingAction('deactivate')}
          disabled={loading || effectors.length === 0}
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

      {/* Confirmation modal */}
      {pendingAction && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.6)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 10000,
          }}
        >
          <div
            style={{
              background: '#1e293b',
              border: '1px solid #334155',
              borderRadius: 8,
              padding: 24,
              minWidth: 300,
              textAlign: 'center',
            }}
          >
            <div style={{ fontWeight: 700, fontSize: 14, color: '#f1f5f9', marginBottom: 8 }}>
              Confirm Command
            </div>
            <div style={{ fontSize: 12, color: '#94a3b8', marginBottom: 16 }}>
              Send <strong style={{ color: '#e2e8f0' }}>{pendingAction.toUpperCase()}</strong> to{' '}
              <strong style={{ color: '#e2e8f0' }}>{effectiveEffector}</strong> for{' '}
              <strong style={{ color: '#e2e8f0' }}>{duration}s</strong>?
            </div>
            <div style={{ display: 'flex', gap: 10, justifyContent: 'center' }}>
              <button
                onClick={() => sendCommand(pendingAction)}
                style={{
                  background: '#dc2626',
                  color: '#fff',
                  border: 'none',
                  borderRadius: 6,
                  padding: '6px 18px',
                  cursor: 'pointer',
                  fontWeight: 700,
                  fontSize: 12,
                }}
              >
                Confirm
              </button>
              <button
                onClick={() => setPendingAction(null)}
                style={{
                  background: '#374151',
                  color: '#e2e8f0',
                  border: 'none',
                  borderRadius: 6,
                  padding: '6px 18px',
                  cursor: 'pointer',
                  fontSize: 12,
                }}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

