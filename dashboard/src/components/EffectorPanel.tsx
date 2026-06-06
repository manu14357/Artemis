'use client';
/**
 * EffectorPanel.tsx — Enhanced engagement command panel.
 * 
 * Features:
 * - Effector capability display (audio, visual, physical, simulation)
 * - Tier-appropriate action buttons (TRACK → visual, SOFT → audio/visual, HARD → physical)
 * - Auto-assign best effector for selected threat
 * - Real-time effector status (armed/active/cooldown)
 * - Engagement rules preview
 */
import { useState, useMemo } from 'react';
import type { Threat, EngagementTier } from '../types';
import { usePollEffectors } from '../hooks/usePollEffectors';

const HUB_URL = process.env.NEXT_PUBLIC_HUB_URL ?? 'http://localhost:8080';

// Effector capability detection from ID
function getEffectorCapability(effectorId: string): { 
  type: 'audio' | 'visual' | 'physical' | 'simulation' | 'unknown';
  tiers: EngagementTier[];
  label: string;
  color: string;
} {
  const id = effectorId.toLowerCase();
  if (id.includes('audio')) {
    return { type: 'audio', tiers: ['engage_soft'], label: '🔊 Audio', color: '#3b82f6' };
  }
  if (id.includes('visual') || id.includes('laser') || id.includes('strobe')) {
    return { type: 'visual', tiers: ['track_only', 'engage_soft'], label: '💡 Visual', color: '#f59e0b' };
  }
  if (id.includes('gpio') || id.includes('relay') || id.includes('net') || id.includes('launcher')) {
    return { type: 'physical', tiers: ['engage_hard', 'engage_soft', 'track_only'], label: '🔧 Physical', color: '#22c55e' };
  }
  if (id.includes('sim')) {
    return { type: 'simulation', tiers: ['engage_hard', 'engage_soft', 'track_only'], label: '🖥️ Sim', color: '#64748b' };
  }
  return { type: 'unknown', tiers: ['engage_hard', 'engage_soft', 'track_only'], label: '❓ Unknown', color: '#64748b' };
}

// Tier display config
const TIER_CONFIG: Record<EngagementTier, { label: string; color: string; description: string }> = {
  ignore:       { label: 'IGNORE',       color: '#334155', description: 'No action required' },
  track_only:   { label: 'TRACK ONLY',   color: '#1d4ed8', description: 'Visual tracking / strobe' },
  engage_soft:  { label: 'ENGAGE SOFT',  color: '#f59e0b', description: 'Audio deterrent / GPS spoof*' },
  engage_hard:  { label: 'ENGAGE HARD',  color: '#be123c', description: 'Physical intercept / net launcher' },
};

interface Props {
  threats: Threat[];
}

export default function EffectorPanel({ threats }: Props) {
  const { effectors, loading: effLoading } = usePollEffectors(10_000);
  const [selectedEffector, setSelectedEffector] = useState('');
  const [selectedThreat, setSelectedThreat] = useState<string>('');
  const [duration, setDuration] = useState(5);
  const [lastResult, setLastResult] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [pendingAction, setPendingAction] = useState<{ action: string; effector: string; threat: string } | null>(null);

  const highTier = threats.filter(t => t.tier >= 4);
  
  // Enrich effectors with capabilities
  const enrichedEffectors = useMemo(() => 
    effectors.map(id => ({
      id,
      ...getEffectorCapability(id),
    })), [effectors]);

  // Find best effector for a threat tier
  const bestEffectorForTier = (tier: EngagementTier) => {
    const priority: Partial<Record<EngagementTier, string[]>> = {
      track_only:   ['visual', 'physical', 'simulation'],
      engage_soft:  ['audio', 'visual', 'physical', 'simulation'],
      engage_hard:  ['physical', 'simulation'],
    };
    const order = priority[tier] ?? ['simulation'];
    for (const type of order) {
      const found = enrichedEffectors.find(e => e.type === type && e.tiers.includes(tier));
      if (found) return found;
    }
    return enrichedEffectors[0];
  };

  // Auto-select best effector for highest threat
  const autoAssign = () => {
    if (!threats.length || !enrichedEffectors.length) return;
    const topThreat = threats.reduce((max, t) => (t.score ?? t.confidence) > (max.score ?? max.confidence) ? t : max, threats[0]);
    const recommended = bestEffectorForTier(topThreat.tier >= 4 ? 'engage_hard' : 
                                             topThreat.tier >= 3 ? 'engage_soft' : 'track_only');
    if (recommended) {
      setSelectedEffector(recommended.id);
      setSelectedThreat(topThreat.threat_id);
    }
  };

  const effectiveEffector = selectedEffector || enrichedEffectors[0]?.id || '';
  const effectorInfo = enrichedEffectors.find(e => e.id === effectiveEffector);
  const selectedThreatObj = threats.find(t => t.threat_id === selectedThreat);

  async function sendCommand(action: string) {
    if (!effectiveEffector || !selectedThreat) {
      setLastResult('Select effector and threat');
      setPendingAction(null);
      return;
    }
    setLoading(true);
    setLastResult(null);
    setPendingAction(null);
    try {
      const r = await fetch(`${HUB_URL}/commands/${effectiveEffector}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          action, 
          duration_s: duration,
          track_id: selectedThreat,
        }),
      });
      const j = await r.json() as { status: string };
      setLastResult(`${j.status} → ${effectiveEffector}`);
    } catch {
      setLastResult('hub unreachable');
    } finally {
      setLoading(false);
    }
  }

  const tier = selectedThreatObj?.tier ? TIER_CONFIG[selectedThreatObj.tier >= 4 ? 'engage_hard' :
                                                selectedThreatObj.tier >= 3 ? 'engage_soft' :
                                                'track_only'] : TIER_CONFIG.ignore;

  return (
    <div style={{ background: '#0d1117', borderRadius: 8, padding: 16 }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', letterSpacing: 1 }}>
          EFFECTOR CONTROL
        </div>
        <button 
          onClick={autoAssign}
          disabled={!threats.length || !enrichedEffectors.length || loading}
          style={{
            background: '#0f172a',
            color: '#94a3b8',
            border: '1px solid #334155',
            borderRadius: 4,
            padding: '4px 8px',
            fontSize: 10,
            cursor: 'pointer',
          }}
        >
          AUTO-ASSIGN
        </button>
      </div>

      {/* Mode notice */}
      <div style={{ marginBottom: 10, color: '#94a3b8', fontSize: 11 }}>
        SIMULATION MODE — commands logged, not executed | *GPS spoof requires authorization
      </div>

      {/* Threat alert */}
      {highTier.length > 0 && (
        <div
          style={{
            background: '#7f1d1d',
            borderRadius: 6,
            padding: '6px 10px',
            marginBottom: 10,
            fontSize: 11,
            fontWeight: 700,
            color: '#fca5a5',
          }}
        >
          ⚠ {highTier.length} HIGH/CRITICAL threat{highTier.length > 1 ? 's' : ''} active — recommend ENGAGE HARD
        </div>
      )}

      {/* Effector selector with capability badges */}
      <div style={{ marginBottom: 12 }}>
        <label style={{ fontSize: 10, color: '#64748b', display: 'block', marginBottom: 4 }}>
          SELECT EFFECTOR {enrichedEffectors.length > 0 ? `(${enrichedEffectors.length} available)` : ''}
        </label>
        <select
          value={effectiveEffector}
          onChange={e => setSelectedEffector(e.target.value)}
          disabled={effLoading || enrichedEffectors.length === 0}
          style={{
            width: '100%',
            background: '#1e293b',
            color: '#e2e8f0',
            border: '1px solid #334155',
            borderRadius: 4,
            padding: '6px 8px',
            fontSize: 12,
          }}
        >
          {enrichedEffectors.length === 0
            ? <option value="">No effectors registered</option>
            : enrichedEffectors.map(ef => (
                <option key={ef.id} value={ef.id} style={{ background: '#0d1117' }}>
                  {ef.label} {ef.id} — Tiers: {ef.tiers.map(t => TIER_CONFIG[t].label).join(', ')}
                </option>
              ))}
        </select>
      </div>

      {/* Effector capability display */}
      {effectorInfo && (
        <div style={{ 
          background: '#1e293b', 
          border: `1px solid ${effectorInfo.color}40`,
          borderRadius: 6, 
          padding: '8px 10px', 
          marginBottom: 12,
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          flexWrap: 'wrap',
        }}>
          <span style={{ 
            background: effectorInfo.color, 
            color: '#fff', 
            padding: '2px 8px', 
            borderRadius: 4, 
            fontSize: 10, 
            fontWeight: 700 
          }}>
            {effectorInfo.label}
          </span>
          <span style={{ fontSize: 11, color: '#94a3b8' }}>
            Supports: {effectorInfo.tiers.map(t => (
              <span key={t} style={{ 
                marginRight: 4, 
                padding: '1px 6px', 
                borderRadius: 3, 
                fontSize: 9, 
                background: TIER_CONFIG[t].color + '30', 
                color: TIER_CONFIG[t].color 
              }}>
                {TIER_CONFIG[t].label}
              </span>
            ))}
          </span>
        </div>
      )}

      {/* Threat selector */}
      <div style={{ marginBottom: 12 }}>
        <label style={{ fontSize: 10, color: '#64748b', display: 'block', marginBottom: 4 }}>
          TARGET THREAT
        </label>
        <select
          value={selectedThreat}
          onChange={e => setSelectedThreat(e.target.value)}
          disabled={!threats.length}
          style={{
            width: '100%',
            background: '#1e293b',
            color: '#e2e8f0',
            border: '1px solid #334155',
            borderRadius: 4,
            padding: '6px 8px',
            fontSize: 12,
          }}
        >
          <option value="">Select a threat...</option>
          {threats.map(t => (
            <option key={t.threat_id} value={t.threat_id}>
              T{t.tier} {t.drone_type} — {Math.round(t.position.x)}m E, {Math.round(t.position.y)}m N — Score: {Math.round((t.score ?? t.confidence) * 100)}%
            </option>
          ))}
        </select>
      </div>

      {/* Selected threat tier recommendation */}
      {selectedThreatObj && (
        <div style={{ 
          background: tier.color + '20', 
          border: `1px solid ${tier.color}`,
          borderRadius: 6, 
          padding: '8px 10px', 
          marginBottom: 12,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <span style={{ 
                background: tier.color, 
                color: '#fff', 
                padding: '2px 6px', 
                borderRadius: 3, 
                fontSize: 9, 
                fontWeight: 700,
                marginRight: 8,
              }}>
                {tier.label}
              </span>
              <span style={{ fontSize: 11, color: '#e2e8f0' }}>
                {tier.description}
              </span>
            </div>
            <span style={{ 
              fontSize: 10, 
              color: tier.color,
              fontWeight: 700 
            }}>
              Recommended: {bestEffectorForTier(selectedThreatObj.tier >= 4 ? 'engage_hard' :
                                                selectedThreatObj.tier >= 3 ? 'engage_soft' : 'track_only')?.label || 'None'}
            </span>
          </div>
        </div>
      )}

      {/* Duration */}
      <div style={{ marginBottom: 12 }}>
        <label style={{ fontSize: 10, color: '#64748b', display: 'block', marginBottom: 4 }}>
          DURATION (seconds)
        </label>
        <input
          type="number"
          min={1}
          max={300}
          value={duration}
          onChange={e => setDuration(Math.min(300, Math.max(1, Number(e.target.value))))}
          style={{
            width: 80,
            background: '#1e293b',
            color: '#e2e8f0',
            border: '1px solid #334155',
            borderRadius: 4,
            padding: '6px 8px',
            fontSize: 13,
          }}
        />
      </div>

      {/* Action buttons - tier-aware */}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12 }}>
        {effectorInfo?.tiers.includes('track_only') && (
          <button
            onClick={() => setPendingAction({ action: 'activate', effector: effectiveEffector, threat: selectedThreat })}
            disabled={loading || !effectiveEffector || !selectedThreat}
            style={{ ...btnStyle, background: '#1d4ed8', flex: 1, minWidth: 100 }}
          >
            🎯 TRACK
          </button>
        )}
        {effectorInfo?.tiers.includes('engage_soft') && (
          <button
            onClick={() => setPendingAction({ action: 'engage_soft', effector: effectiveEffector, threat: selectedThreat })}
            disabled={loading || !effectiveEffector || !selectedThreat}
            style={{ ...btnStyle, background: '#f59e0b', flex: 1, minWidth: 100 }}
          >
            🔊 ENGAGE SOFT
          </button>
        )}
        {effectorInfo?.tiers.includes('engage_hard') && (
          <button
            onClick={() => setPendingAction({ action: 'engage_hard', effector: effectiveEffector, threat: selectedThreat })}
            disabled={loading || !effectiveEffector || !selectedThreat}
            style={{ ...btnStyle, background: '#be123c', flex: 1, minWidth: 100 }}
          >
            🔧 ENGAGE HARD
          </button>
        )}
        <button
          onClick={() => setPendingAction({ action: 'deactivate', effector: effectiveEffector, threat: selectedThreat })}
          disabled={loading || !effectiveEffector}
          style={{ ...btnStyle, background: '#374151', flex: 1, minWidth: 100 }}
        >
          ✕ DEACTIVATE
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
            background: 'rgba(0,0,0,0.7)',
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
              minWidth: 320,
              maxWidth: 400,
            }}
          >
            <div style={{ fontWeight: 700, fontSize: 14, color: '#f1f5f9', marginBottom: 12 }}>
              Confirm Engagement
            </div>
            <div style={{ fontSize: 12, color: '#94a3b8', marginBottom: 16, lineHeight: 1.6 }}>
              <strong style={{ color: '#e2e8f0' }}>{pendingAction.action.toUpperCase()}</strong> via{' '}
              <strong style={{ color: '#e2e8f0' }}>{pendingAction.effector}</strong>{' '}
              on threat <strong style={{ color: '#e2e8f0' }}>{pendingAction.threat.slice(-6)}</strong>{' '}
              for <strong style={{ color: '#e2e8f0' }}>{duration}s</strong>?
            </div>
            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
              <button
                onClick={() => sendCommand(pendingAction.action)}
                style={{
                  background: pendingAction.action === 'engage_hard' ? '#be123c' : 
                              pendingAction.action === 'engage_soft' ? '#f59e0b' : '#dc2626',
                  color: '#fff',
                  border: 'none',
                  borderRadius: 6,
                  padding: '8px 20px',
                  cursor: 'pointer',
                  fontWeight: 700,
                  fontSize: 12,
                }}
              >
                CONFIRM
              </button>
              <button
                onClick={() => setPendingAction(null)}
                style={{
                  background: '#374151',
                  color: '#e2e8f0',
                  border: 'none',
                  borderRadius: 6,
                  padding: '8px 20px',
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

      {/* Effector status list */}
      {enrichedEffectors.length > 0 && (
        <details style={{ marginTop: 16 }}>
          <summary style={{ cursor: 'pointer', color: '#64748b', fontSize: 10, fontWeight: 700 }}>
            EFFECTOR REGISTRY ({enrichedEffectors.length})
          </summary>
          <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 4, fontSize: 10 }}>
            {enrichedEffectors.map(ef => (
              <div key={ef.id} style={{ 
                display: 'flex', 
                alignItems: 'center', 
                gap: 6, 
                padding: '4px 8px',
                background: '#0d1117',
                borderRadius: 4,
              }}>
                <span style={{ 
                  background: ef.color, 
                  color: '#fff', 
                  padding: '1px 6px', 
                  borderRadius: 3, 
                  fontSize: 8, 
                  fontWeight: 700 
                }}>
                  {ef.label}
                </span>
                <span style={{ color: '#94a3b8', fontFamily: 'monospace', flex: 1 }}>
                  {ef.id}
                </span>
                <span style={{ color: '#64748b', fontSize: 9 }}>
                  {ef.tiers.map(t => TIER_CONFIG[t].label).join(', ')}
                </span>
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

const btnStyle: React.CSSProperties = {
  color: '#fff',
  border: 'none',
  borderRadius: 6,
  padding: '8px 12px',
  cursor: 'pointer',
  fontSize: 11,
  fontWeight: 700,
};

