'use client';
/**
 * app/settings/page.tsx — ARTEMIS Hub Settings
 *
 * Features:
 * - Live hub status (GET /status + GET /health)
 * - Key hub config display (MQTT, API, fusion params)
 * - Trigger config hot-reload (POST /config/reload)
 * - Alert notification config (stored in localStorage, UI only)
 */
import { useCallback, useEffect, useState } from 'react';

const HUB_URL = process.env.NEXT_PUBLIC_HUB_URL ?? 'http://localhost:8080';

interface HubStatus {
  hub_id: string;
  uptime_s: number;
  active_tracks: number;
  node_count: number;
  engagement_count: number;
}

interface AlertConfig {
  webhookUrl: string;
  webhookEnabled: boolean;
  minTier: string;
  cooldownS: number;
}

const DEFAULT_ALERTS: AlertConfig = {
  webhookUrl: '',
  webhookEnabled: false,
  minTier: 'engage_soft',
  cooldownS: 30,
};

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ background: '#0d1117', borderRadius: 8, padding: 20, marginBottom: 16 }}>
      <div style={{ fontSize: 10, fontWeight: 700, color: '#475569', letterSpacing: 1, marginBottom: 14 }}>
        {title}
      </div>
      {children}
    </div>
  );
}

function KVRow({ k, v, mono }: { k: string; v: string | number | boolean | null | undefined; mono?: boolean }) {
  const display = v == null ? <span style={{ color: '#475569' }}>—</span> : String(v);
  return (
    <div style={{ display: 'flex', padding: '6px 0', borderBottom: '1px solid #1a2130', fontSize: 12 }}>
      <span style={{ color: '#64748b', width: 200, flexShrink: 0 }}>{k}</span>
      <span style={{ color: '#e2e8f0', fontFamily: mono ? 'monospace' : undefined }}>{display}</span>
    </div>
  );
}

function Badge({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span style={{
      display: 'inline-block',
      padding: '2px 8px',
      borderRadius: 4,
      background: ok ? '#14532d' : '#7f1d1d',
      color: ok ? '#86efac' : '#fca5a5',
      fontSize: 10,
      fontWeight: 700,
    }}>
      {label}
    </span>
  );
}

export default function SettingsPage() {
  const [status, setStatus] = useState<HubStatus | null>(null);
  const [healthy, setHealthy] = useState<boolean | null>(null);
  const [reloading, setReloading] = useState(false);
  const [reloadMsg, setReloadMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Alert config persisted to localStorage
  const [alerts, setAlerts] = useState<AlertConfig>(() => {
    if (typeof window === 'undefined') return DEFAULT_ALERTS;
    try {
      const raw = localStorage.getItem('artemis_alerts');
      return raw ? { ...DEFAULT_ALERTS, ...JSON.parse(raw) } : DEFAULT_ALERTS;
    } catch {
      return DEFAULT_ALERTS;
    }
  });
  const [alertSaved, setAlertSaved] = useState(false);

  const fetchStatus = useCallback(async () => {
    try {
      const [sRes, hRes] = await Promise.all([
        fetch(`${HUB_URL}/status`),
        fetch(`${HUB_URL}/health`),
      ]);
      if (sRes.ok) setStatus(await sRes.json());
      setHealthy(hRes.ok);
      setError(null);
    } catch {
      setError('Hub unreachable — start hub/main.py first');
      setHealthy(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    const id = setInterval(fetchStatus, 10000);
    return () => clearInterval(id);
  }, [fetchStatus]);

  async function triggerReload() {
    setReloading(true);
    setReloadMsg(null);
    try {
      const res = await fetch(`${HUB_URL}/config/reload`, { method: 'POST' });
      const data = await res.json() as { status?: string };
      setReloadMsg(data.status ?? (res.ok ? 'Reload triggered' : 'Reload failed'));
    } catch {
      setReloadMsg('Failed to reach hub');
    } finally {
      setReloading(false);
    }
  }

  function saveAlerts() {
    localStorage.setItem('artemis_alerts', JSON.stringify(alerts));
    setAlertSaved(true);
    setTimeout(() => setAlertSaved(false), 2000);
  }

  return (
    <div style={{ padding: 24, maxWidth: 900, margin: '0 auto' }}>
      {/* Header */}
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ margin: 0, fontSize: 20, fontWeight: 900, letterSpacing: 2, color: '#3b82f6' }}>
          SETTINGS
        </h1>
        <p style={{ margin: '4px 0 0', fontSize: 12, color: '#475569' }}>
          Hub configuration · System status · Alert notification
        </p>
      </div>

      {error && (
        <div style={{ background: '#7f1d1d', borderRadius: 8, padding: 12, marginBottom: 16, color: '#fca5a5', fontSize: 12 }}>
          {error}
        </div>
      )}

      {/* System status */}
      <Section title="SYSTEM STATUS">
        <div style={{ display: 'flex', gap: 12, marginBottom: 12, flexWrap: 'wrap' }}>
          <Badge ok={healthy === true} label={healthy === true ? 'HUB ONLINE' : 'HUB OFFLINE'} />
          {status && <Badge ok={true} label={`ID: ${status.hub_id}`} />}
        </div>
        {status && <>
          <KVRow k="Hub ID"            v={status.hub_id} />
          <KVRow k="Uptime"            v={`${Math.floor(status.uptime_s / 60)}m ${Math.floor(status.uptime_s % 60)}s`} />
          <KVRow k="Active tracks"     v={status.active_tracks} mono />
          <KVRow k="Sensor nodes"      v={status.node_count} mono />
          <KVRow k="Total engagements" v={status.engagement_count} mono />
        </>}
      </Section>

      {/* Hub config (read-only from hub_default.yaml defaults) */}
      <Section title="HUB CONFIGURATION">
        <KVRow k="API endpoint"        v={HUB_URL} mono />
        <KVRow k="MQTT broker"         v="127.0.0.1:1883" mono />
        <KVRow k="Node topic prefix"   v="artemis/nodes/{id}" mono />
        <KVRow k="Threats topic"       v="artemis/threats" mono />
        <KVRow k="EKF process noise Q" v="0.1" mono />
        <KVRow k="EKF meas. noise R"   v="0.5" mono />
        <KVRow k="Max coast frames"    v="30  (~3 s)" mono />
        <KVRow k="Assignment max dist" v="100 m" mono />
        <KVRow k="DBSCAN eps"          v="100 m" mono />
        <KVRow k="DBSCAN min samples"  v="3" mono />
        <KVRow k="Confirm min layers"  v="1" mono />
      </Section>

      {/* Config hot-reload */}
      <Section title="CONFIG HOT-RELOAD">
        <p style={{ fontSize: 12, color: '#94a3b8', margin: '0 0 12px' }}>
          Trigger a live reload of the hub YAML config. Fusion parameters (coast frames, assignment distance, min layers) are updated without restarting the hub.
        </p>
        <button
          onClick={triggerReload}
          disabled={reloading || healthy !== true}
          style={{
            background: reloading ? '#334155' : '#1e3a5f',
            color: reloading ? '#64748b' : '#93c5fd',
            border: '1px solid #1e3a5f',
            borderRadius: 6,
            padding: '8px 18px',
            fontSize: 12,
            fontWeight: 700,
            cursor: healthy === true && !reloading ? 'pointer' : 'not-allowed',
          }}
        >
          {reloading ? 'RELOADING…' : 'RELOAD CONFIG'}
        </button>
        {reloadMsg && (
          <div style={{ marginTop: 10, fontSize: 12, color: '#86efac' }}>
            {reloadMsg}
          </div>
        )}
      </Section>

      {/* Alert notifications */}
      <Section title="ALERT NOTIFICATIONS">
        <p style={{ fontSize: 12, color: '#94a3b8', margin: '0 0 16px' }}>
          Alert config is stored locally in your browser. The hub does not send outbound notifications — configure an external webhook to receive engagement events.
        </p>

        <div style={{ marginBottom: 12 }}>
          <label style={{ fontSize: 11, color: '#64748b', display: 'block', marginBottom: 4 }}>
            Webhook URL (POST JSON payload)
          </label>
          <input
            type="url"
            value={alerts.webhookUrl}
            onChange={e => setAlerts(a => ({ ...a, webhookUrl: e.target.value }))}
            placeholder="https://hooks.slack.com/…"
            style={{
              background: '#1e293b',
              border: '1px solid #334155',
              borderRadius: 4,
              color: '#e2e8f0',
              fontSize: 12,
              padding: '7px 10px',
              width: '100%',
              maxWidth: 480,
              boxSizing: 'border-box',
            }}
          />
        </div>

        <div style={{ marginBottom: 12, display: 'flex', alignItems: 'center', gap: 10 }}>
          <label style={{ fontSize: 11, color: '#64748b' }}>Enable webhook</label>
          <input
            type="checkbox"
            checked={alerts.webhookEnabled}
            onChange={e => setAlerts(a => ({ ...a, webhookEnabled: e.target.checked }))}
          />
        </div>

        <div style={{ marginBottom: 12 }}>
          <label style={{ fontSize: 11, color: '#64748b', display: 'block', marginBottom: 4 }}>
            Minimum tier to alert
          </label>
          <select
            value={alerts.minTier}
            onChange={e => setAlerts(a => ({ ...a, minTier: e.target.value }))}
            style={{
              background: '#1e293b',
              border: '1px solid #334155',
              borderRadius: 4,
              color: '#e2e8f0',
              fontSize: 12,
              padding: '6px 10px',
            }}
          >
            <option value="ignore">IGNORE (all)</option>
            <option value="track_only">TRACK ONLY</option>
            <option value="engage_soft">ENGAGE SOFT</option>
            <option value="engage_hard">ENGAGE HARD (critical only)</option>
          </select>
        </div>

        <div style={{ marginBottom: 16 }}>
          <label style={{ fontSize: 11, color: '#64748b', display: 'block', marginBottom: 4 }}>
            Cooldown between alerts (seconds)
          </label>
          <input
            type="number"
            value={alerts.cooldownS}
            min={5}
            max={3600}
            onChange={e => setAlerts(a => ({ ...a, cooldownS: Number(e.target.value) }))}
            style={{
              background: '#1e293b',
              border: '1px solid #334155',
              borderRadius: 4,
              color: '#e2e8f0',
              fontSize: 12,
              padding: '6px 10px',
              width: 100,
            }}
          />
        </div>

        <button
          onClick={saveAlerts}
          style={{
            background: alertSaved ? '#166534' : '#1e293b',
            color: alertSaved ? '#86efac' : '#93c5fd',
            border: `1px solid ${alertSaved ? '#166534' : '#334155'}`,
            borderRadius: 6,
            padding: '7px 16px',
            fontSize: 12,
            fontWeight: 700,
            cursor: 'pointer',
          }}
        >
          {alertSaved ? '✓ SAVED' : 'SAVE ALERT CONFIG'}
        </button>
      </Section>

      {/* About */}
      <Section title="ABOUT">
        <KVRow k="System"      v="ARTEMIS Counter-Drone Fusion" />
        <KVRow k="Dashboard"   v="Next.js 14 · App Router" />
        <KVRow k="Hub backend" v="FastAPI · Python 3.11" />
        <KVRow k="Fusion"      v="EKF + Hungarian + DBSCAN" />
        <KVRow k="Sensors"     v="RF · Acoustic · Radar · Optical" />
      </Section>
    </div>
  );
}
