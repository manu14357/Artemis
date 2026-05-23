'use client';
/**
 * ThreatMap.tsx
 * Three.js scene rendered on a <canvas> showing live drone positions
 * as coloured spheres in a local-Cartesian coordinate frame.
 *
 * Controls: left-drag to orbit, right-drag to pan, scroll to zoom.
 * Click a sphere to show a detail popover for that threat.
 *
 * Must be 'use client' — Three.js uses browser-only globals (window, document,
 * ResizeObserver, WebGLRenderingContext).
 *
 * Tier colour scale: 1=green, 2=yellow, 3=orange, 4=red, 5=crimson
 */
import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import type { Threat } from '../types';

const TIER_COLOURS: Record<number, number> = {
  1: 0x22c55e,   // green-500
  2: 0xeab308,   // yellow-500
  3: 0xf97316,   // orange-500
  4: 0xef4444,   // red-500
  5: 0xbe123c,   // rose-700
};

const GRID_SIZE   = 500;   // metres each side
const GRID_DIV    = 10;
const TRAIL_LEN   = 10;    // positions to retain per track

interface Props {
  threats: Threat[];
}

/** Compute speed in m/s from velocity state if available */
function computeSpeed(threat: Threat): string {
  const vel = threat.velocity;
  if (vel && typeof vel.vx === 'number') {
    const speed = Math.sqrt(vel.vx ** 2 + vel.vy ** 2 + (vel.vz ?? 0) ** 2);
    return speed.toFixed(1);
  }
  return '?';
}

/** Small detail card shown when the user clicks a threat sphere */
function ThreatPopover({
  threat,
  onClose,
}: {
  threat: Threat;
  onClose: () => void;
}) {
  const dist = Math.round(
    Math.sqrt(threat.position.x ** 2 + threat.position.y ** 2 + threat.position.z ** 2)
  );
  const tierLabels: Record<number, string> = {
    1: 'TRACK ONLY', 2: 'LOW', 3: 'MODERATE', 4: 'HIGH', 5: 'CRITICAL',
  };
  return (
    <div
      style={{
        position: 'absolute',
        top: 12,
        left: 12,
        background: '#0f172a',
        border: '1px solid #1e3a5f',
        borderRadius: 8,
        padding: '10px 14px',
        minWidth: 200,
        zIndex: 10,
        boxShadow: '0 4px 24px #00000080',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <span style={{ fontSize: 10, fontWeight: 700, color: '#94a3b8', letterSpacing: 1 }}>
          THREAT DETAIL
        </span>
        <button
          onClick={onClose}
          style={{
            background: 'none', border: 'none', color: '#475569',
            cursor: 'pointer', fontSize: 14, padding: 0, lineHeight: 1,
          }}
          aria-label="Close"
        >
          ✕
        </button>
      </div>
      <table style={{ fontSize: 11, borderCollapse: 'collapse', width: '100%' }}>
        <tbody>
          {[
            ['ID', threat.threat_id],
            ['Type', threat.drone_type],
            ['Tier', `${threat.tier} — ${tierLabels[threat.tier] ?? ''}`],
            ['Speed', `${computeSpeed(threat)} m/s`],
            ['Range', `${dist} m`],
            ['Alt', `${Math.round(threat.position.z)} m`],
          ].map(([k, v]) => (
            <tr key={k}>
              <td style={{ color: '#475569', paddingRight: 8, paddingBottom: 4 }}>{k}</td>
              <td style={{ color: '#e2e8f0', fontFamily: 'monospace' }}>{v}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function ThreatMap({ threats }: Props) {
  const mountRef     = useRef<HTMLDivElement>(null);
  const rendererRef  = useRef<THREE.WebGLRenderer | null>(null);
  const sceneRef     = useRef<THREE.Scene | null>(null);
  const cameraRef    = useRef<THREE.PerspectiveCamera | null>(null);
  const controlsRef  = useRef<OrbitControls | null>(null);
  const spheresRef   = useRef<Map<string, THREE.Mesh>>(new Map());
  // Trails: one Points object per track, history of last TRAIL_LEN positions
  const trailsRef       = useRef<Map<string, THREE.Points>>(new Map());
  const trailHistoryRef = useRef<Map<string, THREE.Vector3[]>>(new Map());
  const frameRef     = useRef<number>(0);
  const threatsRef   = useRef<Threat[]>([]);
  const [selectedThreat, setSelectedThreat] = useState<Threat | null>(null);

  // Keep threatsRef in sync for the click handler (avoids stale closure)
  useEffect(() => {
    threatsRef.current = threats;
  }, [threats]);

  // One-time scene setup
  useEffect(() => {
    if (!mountRef.current) return;
    const el = mountRef.current;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0d1117);
    sceneRef.current = scene;

    const camera = new THREE.PerspectiveCamera(60, el.clientWidth / el.clientHeight, 1, 5000);
    camera.position.set(0, -600, 400);
    camera.lookAt(0, 0, 0);
    cameraRef.current = camera;

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.setSize(el.clientWidth, el.clientHeight);
    el.appendChild(renderer.domElement);
    rendererRef.current = renderer;

    // OrbitControls — mouse/touch camera navigation
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.minDistance = 50;
    controls.maxDistance = 3000;
    controls.maxPolarAngle = Math.PI / 1.8;   // prevent flip under ground
    controlsRef.current = controls;

    // Grid (X-Y ground plane)
    const grid = new THREE.GridHelper(GRID_SIZE, GRID_DIV, 0x1e40af, 0x1e3a5f);
    grid.rotation.x = Math.PI / 2;
    scene.add(grid);

    // Origin marker (hub position)
    const originGeo = new THREE.SphereGeometry(6, 8, 8);
    const originMat = new THREE.MeshBasicMaterial({ color: 0xffffff });
    scene.add(new THREE.Mesh(originGeo, originMat));

    // Lighting
    scene.add(new THREE.AmbientLight(0xffffff, 0.4));
    const dir = new THREE.DirectionalLight(0xffffff, 0.8);
    dir.position.set(200, 200, 400);
    scene.add(dir);

    // ── Click-to-select handler ──────────────────────────────────────
    const raycaster = new THREE.Raycaster();
    const onCanvasClick = (e: MouseEvent) => {
      const rect = el.getBoundingClientRect();
      const mouse = new THREE.Vector2(
        ((e.clientX - rect.left) / el.clientWidth)  *  2 - 1,
        -((e.clientY - rect.top)  / el.clientHeight) *  2 + 1,
      );
      raycaster.setFromCamera(mouse, camera);
      const meshes = [...spheresRef.current.values()];
      const hits = raycaster.intersectObjects(meshes);
      if (hits.length === 0) {
        setSelectedThreat(null);
        return;
      }
      const hitMesh = hits[0].object;
      // Find the threat whose sphere was hit
      for (const [id, mesh] of spheresRef.current.entries()) {
        if (mesh === hitMesh) {
          const found = threatsRef.current.find((t) => t.threat_id === id) ?? null;
          setSelectedThreat(found);
          return;
        }
      }
    };
    renderer.domElement.addEventListener('click', onCanvasClick);

    // Resize observer
    const ro = new ResizeObserver(() => {
      if (!el || !cameraRef.current || !rendererRef.current) return;
      cameraRef.current.aspect = el.clientWidth / el.clientHeight;
      cameraRef.current.updateProjectionMatrix();
      rendererRef.current.setSize(el.clientWidth, el.clientHeight);
    });
    ro.observe(el);

    function animate() {
      frameRef.current = requestAnimationFrame(animate);
      controls.update();   // needed for damping
      renderer.render(scene, camera);
    }
    animate();

    return () => {
      cancelAnimationFrame(frameRef.current);
      ro.disconnect();
      controls.dispose();
      renderer.domElement.removeEventListener('click', onCanvasClick);
      renderer.dispose();
      if (el.contains(renderer.domElement)) el.removeChild(renderer.domElement);
    };
  }, []);

  // Update spheres + trails whenever threats change
  useEffect(() => {
    const scene = sceneRef.current;
    if (!scene) return;

    const seen = new Set<string>();

    for (const t of threats) {
      seen.add(t.threat_id);
      const colour = TIER_COLOURS[t.tier] ?? 0xffffff;
      let mesh = spheresRef.current.get(t.threat_id);

      if (!mesh) {
        // Scale sphere radius by tier (T5 is larger — more visible)
        const radius = 3 + t.tier;
        const geo = new THREE.SphereGeometry(radius, 12, 12);
        const mat = new THREE.MeshLambertMaterial({ color: colour });
        mesh = new THREE.Mesh(geo, mat);
        scene.add(mesh);
        spheresRef.current.set(t.threat_id, mesh);
      }

      // Coordinate mapping: x=East, y=Up (alt), z=-North (Three.js y-up world)
      const pos3 = new THREE.Vector3(t.position.x, t.position.z, -t.position.y);
      mesh.position.copy(pos3);
      (mesh.material as THREE.MeshLambertMaterial).color.setHex(colour);

      // ── Trail history ────────────────────────────────────────────────
      const history = trailHistoryRef.current.get(t.threat_id) ?? [];
      history.push(pos3.clone());
      if (history.length > TRAIL_LEN) history.shift();
      trailHistoryRef.current.set(t.threat_id, history);

      // Build or replace trail Points geometry
      const oldTrail = trailsRef.current.get(t.threat_id);
      if (oldTrail) {
        scene.remove(oldTrail);
        oldTrail.geometry.dispose();
        (oldTrail.material as THREE.Material).dispose();
      }
      if (history.length > 1) {
        const positions = new Float32Array(history.length * 3);
        history.forEach((v, i) => {
          positions[i * 3]     = v.x;
          positions[i * 3 + 1] = v.y;
          positions[i * 3 + 2] = v.z;
        });
        const trailGeo = new THREE.BufferGeometry();
        trailGeo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
        const trailMat = new THREE.PointsMaterial({
          color: colour,
          size: 1.5,
          transparent: true,
          opacity: 0.4,
        });
        const trail = new THREE.Points(trailGeo, trailMat);
        scene.add(trail);
        trailsRef.current.set(t.threat_id, trail);
      }
    }

    // Remove stale spheres + trails (including selected one if it disappeared)
    for (const [id, mesh] of spheresRef.current.entries()) {
      if (!seen.has(id)) {
        scene.remove(mesh);
        (mesh.material as THREE.Material).dispose();
        (mesh.geometry as THREE.BufferGeometry).dispose();
        spheresRef.current.delete(id);
        // Clean up trail
        const trail = trailsRef.current.get(id);
        if (trail) {
          scene.remove(trail);
          trail.geometry.dispose();
          (trail.material as THREE.Material).dispose();
          trailsRef.current.delete(id);
        }
        trailHistoryRef.current.delete(id);
      }
    }

    // Clear popover if selected threat is gone
    setSelectedThreat((prev) => {
      if (!prev) return null;
      return threats.find((t) => t.threat_id === prev.threat_id) ?? null;
    });
  }, [threats]);

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%', minHeight: 400 }}>
      <div
        ref={mountRef}
        style={{ width: '100%', height: '100%', borderRadius: 8 }}
      />

      {/* Threat detail popover */}
      {selectedThreat && (
        <ThreatPopover
          threat={selectedThreat}
          onClose={() => setSelectedThreat(null)}
        />
      )}

      <div
        style={{
          position: 'absolute',
          bottom: 8,
          right: 10,
          fontSize: 9,
          color: '#475569',
          pointerEvents: 'none',
          letterSpacing: 0.5,
        }}
      >
        DRAG TO ORBIT · SCROLL TO ZOOM · CLICK TO INSPECT
      </div>
    </div>
  );
}
