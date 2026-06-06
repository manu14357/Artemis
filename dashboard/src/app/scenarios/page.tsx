'use client';
/**
 * app/scenarios/page.tsx — ARTEMIS Scenario Designer
 *
 * Features:
 * - Load and display built-in scenarios (10_drone_swarm, 1000_drone_swarm, etc.)
 * - Visual parameter editor (drone count, speed, formation, spread)
 * - Launch scenario command (shows CLI to run sim)
 * - What-if comparison table
 */
import { useState } from 'react';

interface ScenarioConfig {
  name: string;
  file: string;
  description: string;
  droneCount: number;
  formation: 'converging' | 'line' | 'grid' | 'random';
  speedMps: number;
  spreadM: number;
  durationS: number;
  tickHz: number;
}

const BUILT_IN_SCENARIOS: ScenarioConfig[] = [
  {
    name: 'Single Drone',
    file: 'sim/scenarios/single_drone.yaml',
    description: 'Single DJI Mini3 approaching from 500m. Tests single-target EKF tracking and classification.',
    droneCount: 1,
    formation: 'converging',
    speedMps: 8,
    spreadM: 500,
    durationS: 120,
    tickHz: 50,
  },
  {
    name: '10 Drone Swarm',
    file: 'sim/scenarios/10_drone_swarm.yaml',
    description: '10-drone coordinated swarm from multiple vectors. Tests DBSCAN swarm detection + multi-target EKF.',
    droneCount: 10,
    formation: 'converging',
    speedMps: 12,
    spreadM: 200,
    durationS: 300,
    tickHz: 50,
  },
  {
    name: 'Engagement Response',
    file: 'sim/scenarios/engagement_response.yaml',
    description: 'Swarm with simulated effector responses. Tests tiered engagement logic + scheduler.',
    droneCount: 5,
    formation: 'random',
    speedMps: 10,
    spreadM: 300,
    durationS: 180,
    tickHz: 50,
  },
  {
    name: '1000 Drone Swarm',
    file: 'sim/scenarios/1000_drone_swarm.yaml',
    description: 'Mass swarm stress test. Load-tests fusion pipeline, DBSCAN, and MQTT throughput.',
    droneCount: 1000,
    formation: 'random',
    speedMps: 15,
    spreadM: 2000,
    durationS: 60,
    tickHz: 10,
  },
];

const FORMATIONS = ['converging', 'line', 'grid', 'random'] as const;

function ParamRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', marginBottom: 12 }}>
      <label style={{ fontSize: 11, color: '#64748b', width: 140, flexShrink: 0 }}>{label}</label>
      {children}
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  background: '#1e293b',
  color: '#e2e8f0',
  border: '1px solid #334155',
  borderRadius: 4,
  padding: '5px 8px',
  fontSize: 12,
  width: 120,
};

export default function ScenariosPage() {
  const [selected, setSelected] = useState<ScenarioConfig>({ ...BUILT_IN_SCENARIOS[1] });
  const [customName, setCustomName] = useState('');
  const [launched, setLaunched] = useState(false);

  const cliCommand = `python sim/drone_swarm.py \\
  --scenario ${selected.file} \\
  --duration ${selected.durationS} \\
  --tick-hz ${selected.tickHz} \\
  --broker 127.0.0.1 --port 1883`;

  return (
    <div style={{ padding: 24, maxWidth: 1200, margin: '0 auto' }}>
      {/* Header */}
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ margin: 0, fontSize: 20, fontWeight: 900, letterSpacing: 2, color: '#3b82f6' }}>
          SCENARIOS
        </h1>
        <p style={{ margin: '4px 0 0', fontSize: 12, color: '#475569' }}>
          Design, launch, and compare simulation scenarios
        </p>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '280px 1fr', gap: 20 }}>
        {/* Scenario list */}
        <div>
          <div style={{ fontSize: 10, fontWeight: 700, color: '#475569', letterSpacing: 1, marginBottom: 8 }}>
            BUILT-IN SCENARIOS
          </div>
          {BUILT_IN_SCENARIOS.map((sc) => (
            <button
              key={sc.name}
              onClick={() => { setSelected({ ...sc }); setLaunched(false); }}
              style={{
                display: 'block',
                width: '100%',
                textAlign: 'left',
                background: selected.name === sc.name ? '#1e3a5f' : '#0d1117',
                border: selected.name === sc.name ? '1px solid #3b82f6' : '1px solid #1e293b',
                borderRadius: 6,
                padding: '10px 14px',
                marginBottom: 8,
                cursor: 'pointer',
                color: '#e2e8f0',
              }}
            >
              <div style={{ fontSize: 13, fontWeight: 700 }}>{sc.name}</div>
              <div style={{ fontSize: 10, color: '#64748b', marginTop: 3 }}>
                {sc.droneCount} drone{sc.droneCount !== 1 ? 's' : ''} · {sc.formation} · {sc.durationS}s
              </div>
            </button>
          ))}
        </div>

        {/* Editor + launch */}
        <div>
          {/* Description */}
          <div style={{ background: '#0d1117', borderRadius: 8, padding: 16, marginBottom: 16 }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: '#475569', letterSpacing: 1, marginBottom: 6 }}>
              DESCRIPTION
            </div>
            <p style={{ margin: 0, fontSize: 12, color: '#94a3b8', lineHeight: 1.6 }}>
              {selected.description}
            </p>
          </div>

          {/* Parameter editor */}
          <div style={{ background: '#0d1117', borderRadius: 8, padding: 16, marginBottom: 16 }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: '#475569', letterSpacing: 1, marginBottom: 14 }}>
              PARAMETERS
            </div>

            <ParamRow label="Drone count">
              <input
                type="number"
                value={selected.droneCount}
                min={1}
                max={1000}
                onChange={e => setSelected(s => ({ ...s, droneCount: Number(e.target.value) }))}
                style={inputStyle}
              />
            </ParamRow>

            <ParamRow label="Formation">
              <select
                value={selected.formation}
                onChange={e => setSelected(s => ({ ...s, formation: e.target.value as typeof FORMATIONS[number] }))}
                style={{ ...inputStyle, width: 140 }}
              >
                {FORMATIONS.map(f => <option key={f} value={f}>{f}</option>)}
              </select>
            </ParamRow>

            <ParamRow label="Speed (m/s)">
              <input
                type="number"
                value={selected.speedMps}
                min={1}
                max={50}
                onChange={e => setSelected(s => ({ ...s, speedMps: Number(e.target.value) }))}
                style={inputStyle}
              />
            </ParamRow>

            <ParamRow label="Spread radius (m)">
              <input
                type="number"
                value={selected.spreadM}
                min={50}
                max={5000}
                step={50}
                onChange={e => setSelected(s => ({ ...s, spreadM: Number(e.target.value) }))}
                style={inputStyle}
              />
            </ParamRow>

            <ParamRow label="Duration (s)">
              <input
                type="number"
                value={selected.durationS}
                min={10}
                max={3600}
                onChange={e => setSelected(s => ({ ...s, durationS: Number(e.target.value) }))}
                style={inputStyle}
              />
            </ParamRow>

            <ParamRow label="Tick rate (Hz)">
              <input
                type="number"
                value={selected.tickHz}
                min={1}
                max={100}
                onChange={e => setSelected(s => ({ ...s, tickHz: Number(e.target.value) }))}
                style={inputStyle}
              />
            </ParamRow>
          </div>

          {/* CLI launch command */}
          <div style={{ background: '#0d1117', borderRadius: 8, padding: 16, marginBottom: 16 }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: '#475569', letterSpacing: 1, marginBottom: 10 }}>
              LAUNCH COMMAND
            </div>
            <pre style={{
              background: '#060b14',
              borderRadius: 6,
              padding: 12,
              fontSize: 12,
              color: '#22c55e',
              margin: 0,
              overflowX: 'auto',
              border: '1px solid #1e293b',
            }}>
              {cliCommand}
            </pre>
            <button
              onClick={() => {
                navigator.clipboard?.writeText(cliCommand);
                setLaunched(true);
                setTimeout(() => setLaunched(false), 2000);
              }}
              style={{
                marginTop: 10,
                background: launched ? '#166534' : '#1e3a5f',
                color: launched ? '#86efac' : '#93c5fd',
                border: `1px solid ${launched ? '#166534' : '#1e3a5f'}`,
                borderRadius: 4,
                padding: '6px 14px',
                fontSize: 11,
                cursor: 'pointer',
                fontWeight: 700,
              }}
            >
              {launched ? '✓ COPIED TO CLIPBOARD' : 'COPY COMMAND'}
            </button>
          </div>

          {/* What-if comparison table */}
          <div style={{ background: '#0d1117', borderRadius: 8, padding: 16 }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: '#475569', letterSpacing: 1, marginBottom: 12 }}>
              WHAT-IF COMPARISON
            </div>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid #1e293b' }}>
                  {['Scenario', 'Drones', 'Formation', 'Speed', 'Duration'].map(h => (
                    <th key={h} style={{ textAlign: 'left', padding: '6px 10px', color: '#475569', fontWeight: 700, fontSize: 10, letterSpacing: 0.5 }}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {BUILT_IN_SCENARIOS.map((sc, i) => (
                  <tr
                    key={sc.name}
                    style={{
                      background: sc.name === selected.name ? '#0f172a' : 'transparent',
                      borderBottom: '1px solid #0f172a',
                    }}
                  >
                    <td style={{ padding: '7px 10px', color: sc.name === selected.name ? '#93c5fd' : '#94a3b8', fontWeight: sc.name === selected.name ? 700 : 400 }}>
                      {sc.name}
                    </td>
                    <td style={{ padding: '7px 10px', color: '#e2e8f0', fontFamily: 'monospace' }}>{sc.droneCount}</td>
                    <td style={{ padding: '7px 10px', color: '#e2e8f0' }}>{sc.formation}</td>
                    <td style={{ padding: '7px 10px', color: '#e2e8f0', fontFamily: 'monospace' }}>{sc.speedMps} m/s</td>
                    <td style={{ padding: '7px 10px', color: '#e2e8f0', fontFamily: 'monospace' }}>{sc.durationS}s</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
