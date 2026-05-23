'use client';
/**
 * SwarmMap.tsx
 * Renders swarm groupings as convex-hull polygons in the Three.js scene.
 *
 * Each swarm gets:
 *  - A translucent filled polygon (convex hull of member positions, XY plane)
 *  - A floating text label showing swarm_id and member count
 *
 * This component is overlay-only — it reuses the scene from ThreatMap by
 * accepting an external sceneRef.  If you embed ThreatMap + SwarmMap in the
 * same page, pass the scene ref down.
 *
 * Alternatively (standalone use), this component mounts its own canvas.
 */
import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import type { Threat } from '../types';

interface Props {
  threats: Threat[];
  /** Optional: inject an existing Three.js scene (shared with ThreatMap) */
  scene?: THREE.Scene | null;
}

// ── Geometry helpers ──────────────────────────────────────────────────────────

/** Graham scan convex hull on 2-D points (returns indices in CCW order) */
function convexHull2D(pts: { x: number; z: number }[]): { x: number; z: number }[] {
  if (pts.length < 3) return pts;

  // Sort by x, then z
  const sorted = [...pts].sort((a, b) => a.x - b.x || a.z - b.z);

  function cross(o: { x: number; z: number }, a: { x: number; z: number }, b: { x: number; z: number }) {
    return (a.x - o.x) * (b.z - o.z) - (a.z - o.z) * (b.x - o.x);
  }

  const lower: { x: number; z: number }[] = [];
  for (const p of sorted) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) {
      lower.pop();
    }
    lower.push(p);
  }

  const upper: { x: number; z: number }[] = [];
  for (let i = sorted.length - 1; i >= 0; i--) {
    const p = sorted[i];
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) {
      upper.pop();
    }
    upper.push(p);
  }

  lower.pop();
  upper.pop();
  return [...lower, ...upper];
}

/** Build a flat (XZ plane) filled polygon mesh from hull points */
function buildHullMesh(hull: { x: number; z: number }[], colour: number, y: number): THREE.Mesh {
  const shape = new THREE.Shape();
  shape.moveTo(hull[0].x, hull[0].z);
  for (let i = 1; i < hull.length; i++) shape.lineTo(hull[i].x, hull[i].z);
  shape.closePath();

  const geo = new THREE.ShapeGeometry(shape);
  // Rotate flat shape to XZ plane (Three.js shapes are in XY)
  geo.rotateX(-Math.PI / 2);
  // Shift to correct Y (altitude)
  geo.translate(0, y, 0);

  const mat = new THREE.MeshBasicMaterial({
    color: colour,
    transparent: true,
    opacity: 0.15,
    side: THREE.DoubleSide,
    depthWrite: false,
  });
  return new THREE.Mesh(geo, mat);
}

/** Build wireframe outline of the hull */
function buildHullOutline(hull: { x: number; z: number }[], colour: number, y: number): THREE.LineLoop {
  const pts = hull.map(p => new THREE.Vector3(p.x, y, p.z));
  pts.push(pts[0].clone());  // close the loop
  const geo = new THREE.BufferGeometry().setFromPoints(pts);
  const mat = new THREE.LineBasicMaterial({ color: colour, linewidth: 1.5, transparent: true, opacity: 0.6 });
  return new THREE.LineLoop(geo, mat);
}

/** Build a canvas sprite label */
function buildLabel(text: string, colour: string): THREE.Sprite {
  const canvas = document.createElement('canvas');
  canvas.width = 256;
  canvas.height = 64;
  const ctx = canvas.getContext('2d')!;
  ctx.clearRect(0, 0, 256, 64);
  ctx.font = 'bold 22px monospace';
  ctx.fillStyle = colour;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(text, 128, 32);
  const tex = new THREE.CanvasTexture(canvas);
  const mat = new THREE.SpriteMaterial({ map: tex, transparent: true });
  const sprite = new THREE.Sprite(mat);
  sprite.scale.set(80, 20, 1);
  return sprite;
}

// Swarm colour palette (cycles via swarm_id mod length)
const SWARM_PALETTE = [0x818cf8, 0xfb7185, 0x34d399, 0xfbbf24, 0xa78bfa, 0x38bdf8];
const SWARM_PALETTE_CSS = ['#818cf8', '#fb7185', '#34d399', '#fbbf24', '#a78bfa', '#38bdf8'];

// ── Component ─────────────────────────────────────────────────────────────────

interface SwarmObjects {
  hull: THREE.Mesh;
  outline: THREE.LineLoop;
  label: THREE.Sprite;
}

export default function SwarmMap({ threats, scene }: Props) {
  const localSceneRef  = useRef<THREE.Scene | null>(null);
  const swarmObjectsRef = useRef<Map<number, SwarmObjects>>(new Map());

  // Resolve which scene to use (injected or local)
  const resolvedScene = scene ?? localSceneRef.current;

  useEffect(() => {
    if (!resolvedScene) return;

    // Group threats by swarm_id (null → no swarm)
    const swarmGroups = new Map<number, Threat[]>();
    for (const t of threats) {
      if (t.swarm_id == null) continue;
      const group = swarmGroups.get(t.swarm_id) ?? [];
      group.push(t);
      swarmGroups.set(t.swarm_id, group);
    }

    const seenSwarms = new Set<number>();

    for (const [swarmId, members] of swarmGroups.entries()) {
      seenSwarms.add(swarmId);
      const colIdx = swarmId % SWARM_PALETTE.length;
      const colour    = SWARM_PALETTE[colIdx];
      const colourCSS = SWARM_PALETTE_CSS[colIdx];

      // Compute centroid (XZ plane; use mean altitude for label)
      const cx = members.reduce((s, m) => s + m.position.x, 0) / members.length;
      const cy = members.reduce((s, m) => s + m.position.z, 0) / members.length;  // altitude
      const cz = members.reduce((s, m) => s + m.position.y, 0) / members.length;  // Three.js z

      const pts2d = members.map(m => ({ x: m.position.x, z: -m.position.y }));
      const hull  = convexHull2D(pts2d);

      // Remove old objects for this swarm
      const old = swarmObjectsRef.current.get(swarmId);
      if (old) {
        resolvedScene.remove(old.hull, old.outline, old.label);
        old.hull.geometry.dispose();
        (old.hull.material as THREE.Material).dispose();
        old.outline.geometry.dispose();
        (old.outline.material as THREE.Material).dispose();
        (old.label.material as THREE.SpriteMaterial).map?.dispose();
        (old.label.material as THREE.Material).dispose();
      }

      const y = cy;  // altitude of hull layer
      const hullMesh    = buildHullMesh(hull.length >= 3 ? hull : pts2d, colour, y);
      const hullOutline = buildHullOutline(hull.length >= 3 ? hull : pts2d, colour, y);
      const label       = buildLabel(
        `SW-${swarmId} ×${members.length}`,
        colourCSS,
      );
      label.position.set(cx, y + 20, -cz);

      resolvedScene.add(hullMesh, hullOutline, label);
      swarmObjectsRef.current.set(swarmId, { hull: hullMesh, outline: hullOutline, label });
    }

    // Remove stale swarms
    for (const [id, objs] of swarmObjectsRef.current.entries()) {
      if (!seenSwarms.has(id)) {
        resolvedScene.remove(objs.hull, objs.outline, objs.label);
        objs.hull.geometry.dispose();
        (objs.hull.material as THREE.Material).dispose();
        objs.outline.geometry.dispose();
        (objs.outline.material as THREE.Material).dispose();
        (objs.label.material as THREE.SpriteMaterial).map?.dispose();
        (objs.label.material as THREE.Material).dispose();
        swarmObjectsRef.current.delete(id);
      }
    }
  }, [threats, resolvedScene]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      const sc = resolvedScene;
      if (!sc) return;
      for (const objs of swarmObjectsRef.current.values()) {
        sc.remove(objs.hull, objs.outline, objs.label);
        objs.hull.geometry.dispose();
        (objs.hull.material as THREE.Material).dispose();
        objs.outline.geometry.dispose();
        (objs.outline.material as THREE.Material).dispose();
        (objs.label.material as THREE.SpriteMaterial).map?.dispose();
        (objs.label.material as THREE.Material).dispose();
      }
      swarmObjectsRef.current.clear();
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // This component renders no DOM of its own — it only mutates the Three.js scene
  return null;
}
