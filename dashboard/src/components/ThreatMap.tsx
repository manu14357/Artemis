'use client';
/**
 * ThreatMap.tsx
 * Three.js scene rendered on a <canvas> showing live drone positions
 * as coloured spheres in a local-Cartesian coordinate frame.
 *
 * Must be 'use client' — Three.js uses browser-only globals (window, document,
 * ResizeObserver, WebGLRenderingContext).
 *
 * Tier colour scale: 1=green, 2=yellow, 3=orange, 4=red, 5=crimson
 */
import { useEffect, useRef } from 'react';
import * as THREE from 'three';
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

interface Props {
  threats: Threat[];
}

export default function ThreatMap({ threats }: Props) {
  const mountRef = useRef<HTMLDivElement>(null);
  const rendererRef  = useRef<THREE.WebGLRenderer | null>(null);
  const sceneRef     = useRef<THREE.Scene | null>(null);
  const cameraRef    = useRef<THREE.PerspectiveCamera | null>(null);
  const spheresRef   = useRef<Map<string, THREE.Mesh>>(new Map());
  const frameRef     = useRef<number>(0);

  // One-time scene setup
  useEffect(() => {
    if (!mountRef.current) return;
    const el = mountRef.current;

    const scene    = new THREE.Scene();
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

    // Grid
    const grid = new THREE.GridHelper(GRID_SIZE, GRID_DIV, 0x1e40af, 0x1e3a5f);
    grid.rotation.x = Math.PI / 2;
    scene.add(grid);

    // Ambient + directional light
    scene.add(new THREE.AmbientLight(0xffffff, 0.4));
    const dir = new THREE.DirectionalLight(0xffffff, 0.8);
    dir.position.set(200, 200, 400);
    scene.add(dir);

    // Resize observer
    const ro = new ResizeObserver(() => {
      if (!el || !camera || !renderer) return;
      camera.aspect = el.clientWidth / el.clientHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(el.clientWidth, el.clientHeight);
    });
    ro.observe(el);

    function animate() {
      frameRef.current = requestAnimationFrame(animate);
      renderer.render(scene, camera);
    }
    animate();

    return () => {
      cancelAnimationFrame(frameRef.current);
      ro.disconnect();
      renderer.dispose();
      el.removeChild(renderer.domElement);
    };
  }, []);

  // Update spheres whenever threats change
  useEffect(() => {
    const scene = sceneRef.current;
    if (!scene) return;

    const seen = new Set<string>();

    for (const t of threats) {
      seen.add(t.threat_id);
      const colour = TIER_COLOURS[t.tier] ?? 0xffffff;
      let mesh = spheresRef.current.get(t.threat_id);

      if (!mesh) {
        const geo = new THREE.SphereGeometry(4, 12, 12);
        const mat = new THREE.MeshLambertMaterial({ color: colour });
        mesh = new THREE.Mesh(geo, mat);
        scene.add(mesh);
        spheresRef.current.set(t.threat_id, mesh);
      }

      // Coordinate mapping: x=East, y=Up (alt), z=-North (Three.js y-up world)
      mesh.position.set(t.position.x, t.position.z, -t.position.y);
      (mesh.material as THREE.MeshLambertMaterial).color.setHex(colour);
    }

    // Remove stale spheres
    for (const [id, mesh] of spheresRef.current.entries()) {
      if (!seen.has(id)) {
        scene.remove(mesh);
        (mesh.material as THREE.Material).dispose();
        (mesh.geometry as THREE.BufferGeometry).dispose();
        spheresRef.current.delete(id);
      }
    }
  }, [threats]);

  return (
    <div
      ref={mountRef}
      style={{ width: '100%', height: '100%', minHeight: 400, borderRadius: 8 }}
    />
  );
}
