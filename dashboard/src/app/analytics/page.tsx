'use client';
/**
 * app/analytics/page.tsx — ARTEMIS Analytics Dashboard
 *
 * Polls GET /analytics and GET /engagements to show:
 *  - Live counters: uptime, tracks, nodes, total engagements
 *  - Engagement breakdown by tier (bar chart via CSS)
 *  - Recent engagement timeline (last 20 events)
 *  - Sensor layer activity heat indicator
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import type { Engagement } from '../../types';

const HUB_URL = process.env.NEXT_PUBLIC_HUB_URL ?? 'http://localhost:8080';

interface Analytics {
  uptime_s: number;
  active_tracks: number;
  node_count: number;
  engagement_summary: {
    total: number;
    by_tier: Record<string, number>;
  };
  last_fusion_age_s: number | null;
}

const TIER_COLOR: Record<string, string> = {
  ignore:       '#334155',
  track_only:   '#1d4ed8',
  engage_soft:  '#f59e0b',
  engage_hard:  '#be123c',
};

const TIER_LABEL: Record<string, string> = {
  ignore:       'IGNORE',
  track_only:   'TRACK ONLY',
  engage_soft:  'ENGAGE SOFT',
  engage_hard:  'ENGAGE HARD',
};

function fmtUptime(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
}

function StatCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div style={{
      background: '#0d1117',
      borderRadius: 8,
      padding: '16px 20px',
      minWidth: 140,
      flex: 1,
    }}>
      <div style={{ fontSize: 10, color: '#64748b', letterSpacing: 1, fontWeight: 700, marginBottom: 8 }}>
        {label}
      </div>
      <div style={{ fontSize: 28, fontWeight: 900, color: '#e2e8f0', fontFamily: 'monospace' }}>
        {value}
      </div>
      {sub && <div style={{ fontSize: 11, color: '#475569', marginTop: 4 }}>{sub}</div>}
    </div>
  );
}

export default function AnalyticsPage() {
  const [analytics, setAnalytics] = useState<Analytics | null>(null);
  const [engagements, setEngagements] = useState<Engagement[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const fetch_data = useCallback(async () => {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setRefreshing(true);

    try {
      const [aRes, eRes] = await Promise.all([
        fetch(`${HUB_URL}/analytics`, { signal: ctrl.signal }),
        fetch(`${HUB_URL}/engagements?limit=20`, { signal: ctrl.signal }),
      ]);
      if (!aRes.ok || !eRes.ok) throw new Error(`Hub error: ${aRes.status} / ${eRes.status}`);
      const [a, e] = await Promise.all([aRes.json(), eRes.json()]) as [Analytics, { engagements: Engagement[] }];
      setAnalytics(a);
      setEngagements(e.engagements ?? []);
      setError(null);
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        setError('Hub unreachable — start hub/main.py first');
      }
    } finally {
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    fetch_data();
    const id = setInterval(fetch_data, 5000);
    return () => {
      clearInterval(id);
      abortRef.current?.abort();
    };
  }, [fetch_data]);

  const tierEntries = Object.entries(analytics?.engagement_summary.by_tier ?? {}).sort(
    (a, b) => b[1] - a[1]
  );
  const maxTierCount = Math.max(...tierEntries.map(([, v]) => v), 1);

  return (
    <div style={{ padding: 24, maxWidth: 1200, margin: '0 auto' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 20, fontWeight: 900, letterSpacing: 2, color: '#3b82f6' }}>
            ANALYTICS
          </h1>
          <p style={{ margin: '4px 0 0', fontSize: 12, color: '#475569' }}>
            Engagement statistics · Detection throughput · System health
          </p>
        </div>
        <button
          onClick={fetch_data}
          disabled={refreshing}
          style={{
            background: '#1e293b',
            color: '#94a3b8',
            border: '1px solid #334155',
            borderRadius: 6,
            padding: '6px 14px',
            fontSize: 11,
            cursor: 'pointer',
          }}
        >
          {refreshing ? 'REFRESHING…' : 'REFRESH'}
        </button>
      </div>

      {error && (
        <div style={{ background: '#7f1d1d', borderRadius: 8, padding: 12, marginBottom: 20, color: '#fca5a5', fontSize: 12 }}>
          {error}
        </div>
      )}

      {/* Summary cards */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 24, flexWrap: 'wrap' }}>
        <StatCard label="UPTIME" value={analytics ? fmtUptime(analytics.uptime_s) : '--:--:--'} />
        <StatCard label="ACTIVE TRACKS" value={analytics?.active_tracks ?? '—'} />
        <StatCard label="SENSOR NODES" value={analytics?.node_count ?? '—'} />
        <StatCard
          label="TOTAL ENGAGEMENTS"
          value={analytics?.engagement_summary.total ?? '—'}
          sub="since hub start"
        />
        <StatCard
          label="FUSION AGE"
          value={analytics?.last_fusion_age_s != null ? `${analytics.last_fusion_age_s.toFixed(2)}s` : '—'}
          sub="last fusion cycle"
        />
      </div>

      {/* Two-column: tier bars + timeline */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
        {/* Engagement tier breakdown */}
        <div style={{ background: '#0d1117', borderRadius: 8, padding: 20 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: '#64748b', letterSpacing: 1, marginBottom: 16 }}>
            ENGAGEMENT BREAKDOWN
          </div>
          {tierEntries.length === 0 && (
            <p style={{ color: '#475569', fontSize: 12 }}>No engagements yet</p>
          )}
          {tierEntries.map(([tier, count]) => (
            <div key={tier} style={{ marginBottom: 14 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 4 }}>
                <span style={{ color: TIER_COLOR[tier] ?? '#94a3b8', fontWeight: 700 }}>
                  {TIER_LABEL[tier] ?? tier.toUpperCase()}
                </span>
                <span style={{ color: '#94a3b8', fontFamily: 'monospace' }}>{count}</span>
              </div>
              <div style={{ height: 6, background: '#1e293b', borderRadius: 3, overflow: 'hidden' }}>
                <div
                  style={{
                    width: `${(count / maxTierCount) * 100}%`,
                    height: '100%',
                    background: TIER_COLOR[tier] ?? '#64748b',
                    borderRadius: 3,
                    transition: 'width 0.3s',
                  }}
                />
              </div>
            </div>
          ))}
        </div>

        {/* Recent engagement timeline */}
        <div style={{ background: '#0d1117', borderRadius: 8, padding: 20, overflow: 'hidden' }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: '#64748b', letterSpacing: 1, marginBottom: 16 }}>
            RECENT ENGAGEMENTS (last 20)
          </div>
          <div style={{ overflowY: 'auto', maxHeight: 280 }}>
            {engagements.length === 0 && (
              <p style={{ color: '#475569', fontSize: 12 }}>No engagements recorded</p>
            )}
            {engagements.map((eng, i) => (
              <div
                key={i}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  padding: '6px 0',
                  borderBottom: '1px solid #1e293b',
                  fontSize: 11,
                }}
              >
                <div>
                  <span
                    style={{
                      display: 'inline-block',
                      padding: '2px 6px',
                      borderRadius: 4,
                      background: TIER_COLOR[eng.tier] ?? '#334155',
                      color: '#fff',
                      fontSize: 9,
                      fontWeight: 700,
                      marginRight: 8,
                    }}
                  >
                    {TIER_LABEL[eng.tier] ?? eng.tier.toUpperCase()}
                  </span>
                  <span style={{ color: '#94a3b8' }}>{eng.effector_id}</span>
                </div>
                <div style={{ color: '#475569', fontSize: 10, fontFamily: 'monospace' }}>
                  {new Date(eng.timestamp * 1000).toLocaleTimeString([], { hour12: false })}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Sensor layer activity */}
      <div style={{ background: '#0d1117', borderRadius: 8, padding: 20, marginTop: 20 }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: '#64748b', letterSpacing: 1, marginBottom: 16 }}>
          SENSOR LAYER ACTIVITY
        </div>
        <div style={{ display: 'flex', gap: 12 }}>
          {([
            { layer: 'RF',       color: '#3b82f6', desc: 'RTL-SDR · 200m–5km' },
            { layer: 'ACOUSTIC', color: '#10b981', desc: '4-Mic Array · 50–300m' },
            { layer: 'RADAR',    color: '#f59e0b', desc: 'XM125 · 0.5–20m' },
            { layer: 'OPTICAL',  color: '#a855f7', desc: 'Camera · 0–200m' },
          ] as const).map(({ layer, color, desc }) => (
            <div
              key={layer}
              style={{
                flex: 1,
                background: '#1e293b',
                borderRadius: 6,
                padding: '12px 16px',
                borderLeft: `3px solid ${color}`,
              }}
            >
              <div style={{ fontSize: 12, fontWeight: 700, color }}>{layer}</div>
              <div style={{ fontSize: 10, color: '#475569', marginTop: 4 }}>{desc}</div>
              <div
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: '50%',
                  background: color,
                  marginTop: 8,
                  boxShadow: `0 0 6px ${color}`,
                  animation: 'pulse 2s infinite',
                }}
              />
            </div>
          ))}
        </div>
      </div>

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
      `}</style>
    </div>
  );
}
