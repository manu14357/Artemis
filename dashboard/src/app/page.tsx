'use client';
/**
 * app/page.tsx — ARTEMIS Dashboard root page.
 * 'use client' because this tree uses hooks, WebSocket, and Three.js.
 *
 * Layout:
 *   Top bar  (status / counters)
 *   Left col (Detection Feed + Node Status)
 *   Right col (3-D Threat Map)
 *   Bottom row (Effector Control)
 */
import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import dynamic from 'next/dynamic';
import AlertToast from '../components/AlertToast';
import DetectionFeed from '../components/DetectionFeed';
import EffectorPanel from '../components/EffectorPanel';
import EngagementHistory from '../components/EngagementHistory';
import NodeStatus from '../components/NodeStatus';
import { useArtemisWS } from '../hooks/useArtemisWS';

// MapLibre GL uses WebGL and browser-only APIs — must disable SSR
const ThreatMap = dynamic(() => import('../components/ThreatMap'), { ssr: false });

export default function DashboardPage() {
  const { threats, connected } = useArtemisWS();
  const [uptime, setUptime] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setUptime((s) => s + 1), 1000);
    return () => clearInterval(id);
  }, []);

  const critical = threats.filter((t) => t.tier >= 4).length;
  const avgConf = threats.length
    ? Math.round((threats.reduce((s, t) => s + (t.score ?? t.confidence), 0) / threats.length) * 100)
    : null;

  // Count how many active threats include each sensor layer
  const layerCounts: Record<string, number> = {};
  for (const t of threats) {
    for (const l of t.sensor_layers) {
      layerCounts[l] = (layerCounts[l] ?? 0) + 1;
    }
  }

  const h = String(Math.floor(uptime / 3600)).padStart(2, '0');
  const m = String(Math.floor((uptime % 3600) / 60)).padStart(2, '0');
  const s = String(uptime % 60).padStart(2, '0');
  const uptimeStr = `${h}:${m}:${s}`;

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        background: '#0a0f1a',
      }}
    >
      {/* ── Top bar ── */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '10px 20px',
          background: '#0d1117',
          borderBottom: '1px solid #1e3a5f',
          flexShrink: 0,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span
            style={{ fontWeight: 900, fontSize: 20, letterSpacing: 3, color: '#3b82f6' }}
          >
            ARTEMIS
          </span>
          <span style={{ fontSize: 11, color: '#64748b', letterSpacing: 1 }}>
            COUNTER-DRONE FUSION
          </span>
        </div>

        <div style={{ display: 'flex', gap: 20, fontSize: 12 }}>
          <span style={{ color: connected ? '#22c55e' : '#ef4444' }}>
            {connected ? '● LIVE' : '○ DISCONNECTED'}
          </span>
          <span style={{ color: '#94a3b8' }}>THREATS: {threats.length}</span>
          {critical > 0 && (
            <span style={{ color: '#ef4444', fontWeight: 700 }}>
              CRITICAL: {critical}
            </span>
          )}
          {avgConf !== null && (
            <span style={{ color: avgConf >= 75 ? '#22c55e' : avgConf >= 40 ? '#eab308' : '#ef4444' }}>
              CONF: {avgConf}%
            </span>
          )}
          {Object.entries(layerCounts).map(([layer, count]) => (
            <span key={layer} style={{ color: '#64748b', fontSize: 11 }}>
              {layer.toUpperCase()}: {count}
            </span>
          ))}
          <span style={{ color: '#64748b', fontFamily: 'monospace' }}>{uptimeStr}</span>
        </div>
      </div>

      {/* ── Main grid ── */}
      <div
        style={{
          flex: 1,
          display: 'grid',
          gridTemplateColumns: '340px 1fr',
          gridTemplateRows: '1fr auto',
          gap: 12,
          padding: 12,
          minHeight: 0,
        }}
      >
        {/* Left column */}
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 12,
            minHeight: 0,
            overflow: 'hidden',
          }}
        >
          <section>
            <SectionTitle>Detection Feed</SectionTitle>
            <DetectionFeed threats={threats} />
          </section>
          <section>
            <SectionTitle>Sensor Nodes</SectionTitle>
            <NodeStatus />
          </section>
          <section>
            <SectionTitle>Engagement History</SectionTitle>
            <EngagementHistory />
          </section>
        </div>

        {/* Right: 3-D threat map */}
        <div style={{ position: 'relative', minHeight: 400 }}>
          <SectionTitle>Threat Map (3D)</SectionTitle>
          <div style={{ height: 'calc(100% - 28px)' }}>
            <ThreatMap threats={threats} />
          </div>
        </div>

        {/* Bottom row spanning both columns */}
        <div style={{ gridColumn: '1 / -1' }}>
          <SectionTitle>Effector Control</SectionTitle>
          <EffectorPanel threats={threats} />
        </div>
      </div>

      {/* Alert toasts for Tier 4/5 threats */}
      <AlertToast threats={threats} />
    </div>
  );
}

function SectionTitle({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: 2,
        color: '#475569',
        textTransform: 'uppercase',
        marginBottom: 6,
        paddingLeft: 2,
      }}
    >
      {children}
    </div>
  );
}
