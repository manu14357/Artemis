/**
 * App.tsx — ARTEMIS Dashboard root
 * Layout: left panel (threat feed + node status) | right (3D threat map) | bottom (effector)
 */
import { useEffect, useState } from 'react';
import DetectionFeed from './components/DetectionFeed';
import EffectorPanel from './components/EffectorPanel';
import NodeStatus from './components/NodeStatus';
import ThreatMap from './components/ThreatMap';
import { useArtemisWS } from './hooks/useArtemisWS';

const HUB_URL = import.meta.env.VITE_HUB_URL ?? 'http://localhost:8080';

export default function App() {
  const { threats, connected } = useArtemisWS();
  const [uptime, setUptime] = useState(0);

  // Uptime counter
  useEffect(() => {
    const id = setInterval(() => setUptime(s => s + 1), 1000);
    return () => clearInterval(id);
  }, []);

  const critical = threats.filter(t => t.tier >= 4).length;
  const uptimeStr = `${String(Math.floor(uptime / 3600)).padStart(2,'0')}:${String(Math.floor((uptime % 3600) / 60)).padStart(2,'0')}:${String(uptime % 60).padStart(2,'0')}`;

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', background: '#0a0f1a' }}>
      {/* Top bar */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '10px 20px',
          background: '#0d1117',
          borderBottom: '1px solid #1e3a5f',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ fontWeight: 900, fontSize: 20, letterSpacing: 3, color: '#3b82f6' }}>
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
            <span style={{ color: '#ef4444', fontWeight: 700 }}>CRITICAL: {critical}</span>
          )}
          <span style={{ color: '#64748b', fontFamily: 'monospace' }}>{uptimeStr}</span>
        </div>
      </div>

      {/* Main content */}
      <div
        style={{
          flex: 1,
          display: 'grid',
          gridTemplateColumns: '340px 1fr',
          gridTemplateRows: '1fr auto',
          gap: 12,
          padding: 12,
        }}
      >
        {/* Left column: feed + nodes */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, minHeight: 0 }}>
          <section>
            <SectionTitle>Detection Feed</SectionTitle>
            <DetectionFeed threats={threats} />
          </section>
          <section>
            <SectionTitle>Sensor Nodes</SectionTitle>
            <NodeStatus />
          </section>
        </div>

        {/* Right: 3D threat map */}
        <div style={{ position: 'relative', minHeight: 400 }}>
          <SectionTitle>Threat Map (3D)</SectionTitle>
          <div style={{ flex: 1, height: 'calc(100% - 28px)' }}>
            <ThreatMap threats={threats} />
          </div>
        </div>

        {/* Bottom row spanning both columns */}
        <div style={{ gridColumn: '1 / -1' }}>
          <SectionTitle>Effector Control</SectionTitle>
          <EffectorPanel threats={threats} />
        </div>
      </div>
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
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
