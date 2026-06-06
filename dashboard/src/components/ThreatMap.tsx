'use client';
/**
 * ThreatMap.tsx — ARTEMIS tactical threat map using MapLibre GL JS.
 *
 * Enhanced with:
 * - Sensor coverage volumes (RF dome, acoustic cone, radar frustum, optical FOV)
 * - Predicted trajectories with uncertainty ellipses
 * - Swarm convex hulls and centroids
 * - Engagement zones (track/soft/hard rings)
 * - 3D threat cones with altitude
 *
 * Base tiles: OpenFreeMap "dark" style — completely free, no API key, OSM data.
 */
import { useEffect, useRef, useState, useMemo, useCallback } from 'react';
import MapGL, {
  Source,
  Layer,
  Marker,
  Popup,
  NavigationControl,
  type MapRef,
} from 'react-map-gl/maplibre';
import 'maplibre-gl/dist/maplibre-gl.css';
import type { FeatureCollection, Feature, LineString, Point, Polygon } from 'geojson';
import type { Threat, NodeStatus, SensorLayer } from '../types';

// ── Config ────────────────────────────────────────────────────────────────────
const MAP_STYLE   = 'https://tiles.openfreemap.org/styles/dark';
const TRAIL_LEN   = 15;
const PREDICTION_HORIZON_S = 30;

/** Hub default (London). Replace with hub GPS API feed if available. */
const DEFAULT_LAT = 51.5074;
const DEFAULT_LON = -0.1278;

const TIER_COLOUR: Record<number, string> = {
  1: '#22c55e',
  2: '#eab308',
  3: '#f97316',
  4: '#ef4444',
  5: '#be123c',
};

const LAYER_COLOUR: Record<SensorLayer, string> = {
  rf:       '#3b82f6',    // Blue
  acoustic: '#10b981',    // Green
  radar:    '#f59e0b',    // Amber
  optical:  '#a855f7',    // Violet
};

/** Detection-layer range rings — matches README sensor specs. */
const RINGS = [
  { r: 300,  label: '300 m · Acoustic/Optical', color: '#10b981' },
  { r: 1000, label: '1 km · RF close',          color: '#3b82f6' },
  { r: 3000, label: '3 km · RF typical',        color: '#6366f1' },
  { r: 5000, label: '5 km · RF max',            color: '#8b5cf6' },
] as const;

/** Engagement zone rings around protected asset */
const ENGAGEMENT_ZONES = [
  { r: 100,  tier: 5, label: 'ENGAGE HARD (100m)',  color: '#be123c' },
  { r: 500,  tier: 4, label: 'ENGAGE SOFT (500m)',  color: '#ef4444' },
  { r: 1000, tier: 3, label: 'TRACK ONLY (1km)',    color: '#f97316' },
] as const;

// ── Geo helpers ───────────────────────────────────────────────────────────────

/** Convert local Cartesian metres (x=East, y=North) to [lon, lat]. */
function toCoord(x: number, y: number, cLat: number, cLon: number): [number, number] {
  const lat = cLat + y / 111_319.9;
  const lon = cLon + x / (111_319.9 * Math.cos((cLat * Math.PI) / 180));
  return [lon, lat];
}

/** Build a closed GeoJSON LineString ring at given radius in metres. */
function buildRing(
  cLat: number, cLon: number, radiusM: number, color: string,
): Feature<LineString> {
  const coords: [number, number][] = [];
  const N = 96;
  for (let i = 0; i <= N; i++) {
    const a = (i / N) * 2 * Math.PI;
    const dLat = (radiusM * Math.cos(a)) / 111_319.9;
    const dLon = (radiusM * Math.sin(a)) / (111_319.9 * Math.cos((cLat * Math.PI) / 180));
    coords.push([cLon + dLon, cLat + dLat]);
  }
  return {
    type: 'Feature',
    properties: { r: radiusM, color },
    geometry: { type: 'LineString', coordinates: coords },
  };
}

/** Build uncertainty ellipse for predicted position */
function buildUncertaintyEllipse(
  cLat: number, cLon: number,
  centerX: number, centerY: number,
  sigmaX: number, sigmaY: number,
  rotation: number,
  color: string,
): Feature<Polygon> {
  const coords: [number, number][] = [];
  const N = 64;
  for (let i = 0; i <= N; i++) {
    const a = (i / N) * 2 * Math.PI;
    // Ellipse param eq: x = a*cos(t), y = b*sin(t), then rotate
    const ex = sigmaX * Math.cos(a);
    const ey = sigmaY * Math.sin(a);
    const rx = ex * Math.cos(rotation) - ey * Math.sin(rotation);
    const ry = ex * Math.sin(rotation) + ey * Math.cos(rotation);
    const dLat = (centerY + ry) / 111_319.9;
    const dLon = (centerX + rx) / (111_319.9 * Math.cos((cLat * Math.PI) / 180));
    coords.push([cLon + dLon, cLat + dLat]);
  }
  return {
    type: 'Feature',
    properties: { color },
    geometry: { type: 'Polygon', coordinates: [coords] },
  };
}

/** Build sensor coverage polygon (simplified 2D footprint) */
function buildSensorCoverage(
  cLat: number, cLon: number,
  nodeLat: number, nodeLon: number,
  layer: SensorLayer,
  maxRange: number,
  color: string,
): Feature<Polygon> | null {
  const [centerLon, centerLat] = toCoord(0, 0, cLat, cLon);
  const [nodeX, nodeY] = toCoord(
    (nodeLon - centerLon) * 111_319.9 * Math.cos((cLat * Math.PI) / 180),
    (nodeLat - centerLat) * 111_319.9,
    cLat, cLon
  );

  // Simplified coverage shapes
  let coords: [number, number][] = [];
  const N = 48;

  if (layer === 'rf') {
    // RF: Omnidirectional circle
    for (let i = 0; i <= N; i++) {
      const a = (i / N) * 2 * Math.PI;
      coords.push([
        nodeX + maxRange * Math.sin(a),
        nodeY + maxRange * Math.cos(a),
      ]);
    }
  } else if (layer === 'acoustic') {
    // Acoustic: 120-degree cone forward
    const bearing = 0; // Assume forward-facing
    for (let i = 0; i <= N; i++) {
      const a = bearing - Math.PI/3 + (i / N) * (2*Math.PI/3);
      const r = maxRange * (0.5 + 0.5 * Math.cos(a - bearing));
      coords.push([nodeX + r * Math.sin(a), nodeY + r * Math.cos(a)]);
    }
    coords.push([nodeX, nodeY]); // Close at origin
  } else if (layer === 'radar') {
    // Radar: 90-degree frustum
    const bearing = 0;
    for (let i = 0; i <= N; i++) {
      const a = bearing - Math.PI/4 + (i / N) * (Math.PI/2);
      coords.push([nodeX + maxRange * Math.sin(a), nodeY + maxRange * Math.cos(a)]);
    }
    coords.push([nodeX, nodeY]);
  } else if (layer === 'optical') {
    // Optical: 60-degree FOV cone
    const bearing = 0;
    for (let i = 0; i <= N; i++) {
      const a = bearing - Math.PI/6 + (i / N) * (Math.PI/3);
      coords.push([nodeX + maxRange * Math.sin(a), nodeY + maxRange * Math.cos(a)]);
    }
    coords.push([nodeX, nodeY]);
  } else {
    return null;
  }

  // Convert to lat/lon
  const llCoords = coords.map(([x, y]) => [
    cLon + x / (111_319.9 * Math.cos((cLat * Math.PI) / 180)),
    cLat + y / 111_319.9,
  ]);
  llCoords.push(llCoords[0]); // Close polygon

  return {
    type: 'Feature',
    properties: { layer, color, opacity: 0.15 },
    geometry: { type: 'Polygon', coordinates: [llCoords] },
  };
}

/** Compute convex hull of points (Graham scan) */
function convexHull(points: [number, number][]): [number, number][] {
  if (points.length < 3) return points;
  
  // Find bottom-most point
  let pivot = points.reduce((min, p) => p[1] < min[1] ? p : min, points[0]);
  
  // Sort by polar angle
  const sorted = [...points].sort((a, b) => {
    const angleA = Math.atan2(a[1] - pivot[1], a[0] - pivot[0]);
    const angleB = Math.atan2(b[1] - pivot[1], b[0] - pivot[0]);
    return angleA - angleB;
  });
  
  // Graham scan
  const hull: [number, number][] = [];
  for (const p of sorted) {
    while (hull.length >= 2) {
      const b = hull[hull.length - 1];
      const a = hull[hull.length - 2];
      const cross = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]);
      if (cross <= 0) hull.pop();
      else break;
    }
    hull.push(p);
  }
  return hull;
}

// ── Props ─────────────────────────────────────────────────────────────────────
interface Props {
  threats:      Threat[];
  nodes?:       NodeStatus[];
  centerLat?:   number;
  centerLon?:   number;
  showCoverage?: boolean;
  showPredictions?: boolean;
  showSwarmHulls?: boolean;
  showEngagementZones?: boolean;
}

// ── Component ─────────────────────────────────────────────────────────────────
export default function ThreatMap({
  threats,
  nodes = [],
  centerLat = DEFAULT_LAT,
  centerLon = DEFAULT_LON,
  showCoverage = true,
  showPredictions = true,
  showSwarmHulls = true,
  showEngagementZones = true,
}: Props) {
  const mapRef    = useRef<MapRef>(null);
  const trailsRef = useRef<globalThis.Map<string, [number, number][]>>(
    new globalThis.Map(),
  );
  const [selected, setSelected] = useState<Threat | null>(null);
  const [cLat, setCLat] = useState(centerLat);
  const [cLon, setCLon] = useState(centerLon);

  useEffect(() => {
    if (!navigator?.geolocation) return;
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => {
        setCLat(coords.latitude);
        setCLon(coords.longitude);
        mapRef.current?.flyTo({
          center: [coords.longitude, coords.latitude],
          zoom: 11.5,
          duration: 1200,
        });
      },
      () => { /* permission denied */ },
      { enableHighAccuracy: true, timeout: 10_000 },
    );
  }, []);

  // ── Update trail history ────────────────────────────────────────────────
  useMemo(() => {
    const trails = trailsRef.current;
    const alive  = new Set(threats.map((t) => t.threat_id));
    for (const id of trails.keys()) if (!alive.has(id)) trails.delete(id);
    for (const t of threats) {
      const coord = toCoord(t.position.x, t.position.y, cLat, cLon);
      const pts   = trails.get(t.threat_id) ?? [];
      pts.push(coord);
      if (pts.length > TRAIL_LEN) pts.splice(0, pts.length - TRAIL_LEN);
      trails.set(t.threat_id, pts);
    }
  }, [threats, cLat, cLon]);

  // ── GeoJSON: threat circles ────────────────────────────────────────────
  const threatGeoJSON = useMemo((): FeatureCollection<Point> => ({
    type: 'FeatureCollection',
    features: threats.map((t): Feature<Point> => {
      const [lon, lat] = toCoord(t.position.x, t.position.y, cLat, cLon);
      return {
        type: 'Feature',
        id: t.threat_id,
        properties: {
          id:    t.threat_id,
          color: TIER_COLOUR[t.tier] ?? '#ffffff',
          label: `T${t.tier}`,
          alt:   Math.round(t.position.z),
        },
        geometry: { type: 'Point', coordinates: [lon, lat] },
      };
    }),
  }), [threats, cLat, cLon]);

  // ── GeoJSON: trails ────────────────────────────────────────────────────
  const trailGeoJSON = useMemo((): FeatureCollection<LineString> => ({
    type: 'FeatureCollection',
    features: [...trailsRef.current.entries()]
      .filter(([, pts]) => pts.length >= 2)
      .map(([id, pts]): Feature<LineString> => {
        const t = threats.find((x) => x.threat_id === id);
        return {
          type: 'Feature',
          properties: { color: TIER_COLOUR[t?.tier ?? 1] ?? '#fff' },
          geometry: { type: 'LineString', coordinates: pts },
        };
      }),
  }), [threats]);

  // ── GeoJSON: predicted trajectories with uncertainty ────────────────────
  const predictionGeoJSON = useMemo((): FeatureCollection<LineString | Polygon> => {
    if (!showPredictions) return { type: 'FeatureCollection', features: [] };
    
    const features: (Feature<LineString> | Feature<Polygon>)[] = [];
    
    for (const t of threats) {
      const vx = t.velocity.vx;
      const vy = t.velocity.vy;
      const speed = Math.sqrt(vx*vx + vy*vy);
      if (speed < 0.5) continue; // Skip stationary
      
      // Predict positions at 5, 10, 20, 30 seconds
      const waypoints: [number, number][] = [];
      for (const dt of [5, 10, 20, 30]) {
        const px = t.position.x + vx * dt;
        const py = t.position.y + vy * dt;
        waypoints.push(toCoord(px, py, cLat, cLon));
      }
      
      // Trajectory line
      features.push({
        type: 'Feature',
        properties: { color: TIER_COLOUR[t.tier] ?? '#fff', track_id: t.track_id },
        geometry: { type: 'LineString', coordinates: waypoints },
      });
      
      // Uncertainty ellipse at 30s (grows with time)
      const finalPx = t.position.x + vx * PREDICTION_HORIZON_S;
      const finalPy = t.position.y + vy * PREDICTION_HORIZON_S;
      const uncertainty = Math.min(50 + speed * PREDICTION_HORIZON_S * 0.5, 300);
      const rotation = Math.atan2(vy, vx);
      
      features.push(buildUncertaintyEllipse(
        cLat, cLon,
        finalPx, finalPy,
        uncertainty, uncertainty * 0.5,
        rotation,
        TIER_COLOUR[t.tier] ?? '#fff',
      ));
    }
    
    return { type: 'FeatureCollection', features };
  }, [threats, cLat, cLon, showPredictions]);

  // ── GeoJSON: swarm convex hulls ────────────────────────────────────────
  const swarmGeoJSON = useMemo((): FeatureCollection<Polygon> => {
    if (!showSwarmHulls) return { type: 'FeatureCollection', features: [] };
    
    // Group threats by swarm_id
    const swarms: Record<number, Threat[]> = {};
    for (const t of threats) {
      if (t.swarm_id !== null && t.swarm_id >= 0) {
        if (!swarms[t.swarm_id]) swarms[t.swarm_id] = [];
        swarms[t.swarm_id].push(t);
      }
    }
    
    const features: Feature<Polygon>[] = [];
    for (const [swarmId, members] of Object.entries(swarms)) {
      if (members.length < 3) continue;
      
      const points = members.map(t => [t.position.x, t.position.y] as [number, number]);
      const hull = convexHull(points);
      if (hull.length < 3) continue;
      
      const hullCoords = hull.map(([x, y]) => toCoord(x, y, cLat, cLon));
      hullCoords.push(hullCoords[0]); // Close
      
      // Find highest tier in swarm for color
      const maxTier = Math.max(...members.map(m => m.tier));
      features.push({
        type: 'Feature',
        properties: { 
          swarm_id: parseInt(swarmId), 
          color: TIER_COLOUR[maxTier] ?? '#fff',
          count: members.length,
        },
        geometry: { type: 'Polygon', coordinates: [hullCoords] },
      });
    }
    
    return { type: 'FeatureCollection', features };
  }, [threats, cLat, cLon, showSwarmHulls]);

  // ── GeoJSON: sensor coverage ────────────────────────────────────────────
  const coverageGeoJSON = useMemo((): FeatureCollection<Polygon> => {
    if (!showCoverage || !nodes.length) return { type: 'FeatureCollection', features: [] };
    
    const features: Feature<Polygon>[] = [];
    const maxRanges: Record<SensorLayer, number> = {
      rf: 5000,
      acoustic: 500,
      radar: 2000,
      optical: 200,
    };
    
    for (const node of nodes) {
      if (!node.online) continue;
      for (const layer of node.sensors_active) {
        const coverage = buildSensorCoverage(
          cLat, cLon,
          node.location.lat, node.location.lon,
          layer as SensorLayer,
          maxRanges[layer as SensorLayer] || 1000,
          LAYER_COLOUR[layer as SensorLayer],
        );
        if (coverage) features.push(coverage);
      }
    }
    
    return { type: 'FeatureCollection', features };
  }, [nodes, cLat, cLon, showCoverage]);

  // ── GeoJSON: engagement zones ──────────────────────────────────────────
  const engagementGeoJSON = useMemo((): FeatureCollection<LineString> => {
    if (!showEngagementZones) return { type: 'FeatureCollection', features: [] };

    return {
      type: 'FeatureCollection',
      features: ENGAGEMENT_ZONES.map((zone) => buildRing(cLat, cLon, zone.r, zone.color)),
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cLat, cLon, showEngagementZones]);

  // ── GeoJSON: range rings ───────────────────────────────────────────────
  const ringGeoJSON = useMemo((): FeatureCollection<LineString> => ({
    type: 'FeatureCollection',
    features: RINGS.map((ring) => buildRing(cLat, cLon, ring.r, ring.color)),
  }), [cLat, cLon]);

  const ringLabelGeoJSON = useMemo((): FeatureCollection<Point> => ({
    type: 'FeatureCollection',
    features: RINGS.map((ring): Feature<Point> => ({
      type: 'Feature',
      properties: { label: ring.label, color: ring.color },
      geometry: {
        type: 'Point',
        coordinates: [
          cLon + ring.r / (111_319.9 * Math.cos((cLat * Math.PI) / 180)) + 0.00008,
          cLat,
        ],
      },
    })),
  }), [cLat, cLon]);

  // ── Click handler ──────────────────────────────────────────────────────
  const handleClick = useCallback(
    (e: { features?: Array<{ properties?: Record<string, unknown> | null }> }) => {
      const id = e.features?.[0]?.properties?.['id'] as string | undefined;
      if (!id) { setSelected(null); return; }
      setSelected(threats.find((t) => t.threat_id === id) ?? null);
    },
    [threats],
  );

  const popupCoords = selected
    ? toCoord(selected.position.x, selected.position.y, cLat, cLon)
    : null;

  // ── Render ──────────────────────────────────────────────────────────────
  return (
    <div style={{ position: 'relative', width: '100%', height: '100%', minHeight: 440 }}>
      <MapGL
        ref={mapRef}
        mapStyle={MAP_STYLE}
        initialViewState={{
          longitude: cLon,
          latitude:  cLat,
          zoom:      11.5,
          pitch:     35,
          bearing:   0,
        }}
        style={{ width: '100%', height: '100%' }}
        interactiveLayerIds={['threat-circles', 'swarm-hulls']}
        onClick={handleClick as Parameters<typeof MapGL>[0]['onClick']}
        attributionControl={false}
      >
        <NavigationControl position="top-right" />

        {/* ── Sensor coverage volumes ──────────────────────────────── */}
        {showCoverage && coverageGeoJSON.features.length > 0 && (
          <Source id="coverage" type="geojson" data={coverageGeoJSON}>
            <Layer
              id="sensor-coverage"
              type="fill"
              paint={{
                'fill-color': ['get', 'color'],
                'fill-opacity': ['get', 'opacity'],
              }}
            />
            <Layer
              id="sensor-coverage-outline"
              type="line"
              paint={{
                'line-color': ['get', 'color'],
                'line-width': 1,
                'line-opacity': 0.4,
                'line-dasharray': [4, 4],
              }}
            />
          </Source>
        )}

        {/* ── Engagement zones ─────────────────────────────────────── */}
        {showEngagementZones && (
          <Source id="engagement" type="geojson" data={engagementGeoJSON}>
            <Layer
              id="engagement-zones"
              type="line"
              paint={{
                'line-color': ['get', 'color'],
                'line-width': 2,
                'line-opacity': 0.7,
                'line-dasharray': [8, 4],
              }}
            />
          </Source>
        )}

        {/* ── Range rings ──────────────────────────────────────────── */}
        <Source id="rings" type="geojson" data={ringGeoJSON}>
          <Layer
            id="range-rings"
            type="line"
            paint={{
              'line-color': ['get', 'color'],
              'line-width': 1,
              'line-opacity': 0.55,
              'line-dasharray': [4, 4],
            }}
          />
        </Source>

        {/* ── Ring labels ───────────────────────────────────────────── */}
        <Source id="ring-labels" type="geojson" data={ringLabelGeoJSON}>
          <Layer
            id="ring-label-text"
            type="symbol"
            layout={{
              'text-field': ['get', 'label'],
              'text-size': 10,
              'text-anchor': 'left',
            }}
            paint={{
              'text-color': ['get', 'color'],
              'text-halo-color': '#080d14',
              'text-halo-width': 1.5,
            }}
          />
        </Source>

        {/* ── Swarm convex hulls ───────────────────────────────────── */}
        {showSwarmHulls && swarmGeoJSON.features.length > 0 && (
          <Source id="swarms" type="geojson" data={swarmGeoJSON}>
            <Layer
              id="swarm-hulls"
              type="fill"
              paint={{
                'fill-color': ['get', 'color'],
                'fill-opacity': 0.2,
              }}
            />
            <Layer
              id="swarm-hulls-outline"
              type="line"
              paint={{
                'line-color': ['get', 'color'],
                'line-width': 2,
                'line-opacity': 0.8,
              }}
            />
          </Source>
        )}

        {/* ── Predicted trajectories ───────────────────────────────── */}
        {showPredictions && predictionGeoJSON.features.length > 0 && (
          <>
            <Source id="predictions" type="geojson" data={predictionGeoJSON}>
              <Layer
                id="prediction-lines"
                type="line"
                filter={['==', '$type', 'LineString']}
                paint={{
                  'line-color': ['get', 'color'],
                  'line-width': 1.5,
                  'line-opacity': 0.6,
                  'line-dasharray': [6, 6],
                }}
              />
              <Layer
                id="prediction-ellipses"
                type="fill"
                filter={['==', '$type', 'Polygon']}
                paint={{
                  'fill-color': ['get', 'color'],
                  'fill-opacity': 0.1,
                }}
              />
              <Layer
                id="prediction-ellipses-outline"
                type="line"
                filter={['==', '$type', 'Polygon']}
                paint={{
                  'line-color': ['get', 'color'],
                  'line-width': 1,
                  'line-opacity': 0.4,
                  'line-dasharray': [4, 4],
                }}
              />
            </Source>
          </>
        )}

        {/* ── Threat trails ─────────────────────────────────────────── */}
        <Source id="trails" type="geojson" data={trailGeoJSON}>
          <Layer
            id="trail-lines"
            type="line"
            paint={{
              'line-color': ['get', 'color'],
              'line-width': 1.5,
              'line-opacity': 0.5,
            }}
          />
        </Source>

        {/* ── Threat circles + labels ───────────────────────────────── */}
        <Source id="threats" type="geojson" data={threatGeoJSON}>
          <Layer
            id="threat-circles"
            type="circle"
            paint={{
              'circle-radius': [
                'interpolate', ['linear'], ['zoom'],
                12, 8,
                16, 18,
              ],
              'circle-color': ['get', 'color'],
              'circle-opacity': 0.9,
              'circle-stroke-width': 2,
              'circle-stroke-color': '#ffffff',
            }}
          />
          <Layer
            id="threat-labels"
            type="symbol"
            layout={{
              'text-field': ['get', 'label'],
              'text-size': 11,
              'text-offset': [0, 1.8],
              'text-anchor': 'top',
            }}
            paint={{
              'text-color': '#e2e8f0',
              'text-halo-color': '#080d14',
              'text-halo-width': 1.5,
            }}
          />
        </Source>

        {/* ── Node markers ───────────────────────────────────────────── */}
        {nodes.map((node) => (
          <Marker key={node.node_id} longitude={node.location.lon} latitude={node.location.lat}>
            <div
              title={`${node.node_id} — ${node.online ? 'ONLINE' : 'OFFLINE'}`}
              style={{
                width: 20,
                height: 20,
                borderRadius: '50%',
                background: node.online ? '#22c55e' : '#ef4444',
                border: '2px solid #fff',
                boxShadow: '0 0 8px ' + (node.online ? '#22c55e' : '#ef4444'),
                cursor: 'pointer',
              }}
            />
          </Marker>
        ))}

        {/* ── Hub marker ────────────────────────────────────────────── */}
        <Marker longitude={cLon} latitude={cLat}>
          <div
            title="Hub (Protected Asset)"
            style={{
              width: 24,
              height: 24,
              borderRadius: '50%',
              background: '#3b82f6',
              border: '3px solid #93c5fd',
              boxShadow: '0 0 15px #3b82f6',
              cursor: 'default',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <span style={{ color: '#fff', fontSize: 10, fontWeight: 'bold' }}>★</span>
          </div>
        </Marker>

        {/* ── Threat detail popup ───────────────────────────────────── */}
        {selected && popupCoords && (
          <Popup
            longitude={popupCoords[0]}
            latitude={popupCoords[1]}
            closeButton
            onClose={() => setSelected(null)}
            anchor="bottom"
            style={{ color: '#0f172a', fontSize: 12, minWidth: 200 }}
          >
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
                <strong style={{ fontSize: 13 }}>Track {selected.track_id.slice(-6)}</strong>
                <span
                  style={{
                    padding: '2px 6px',
                    borderRadius: 4,
                    fontSize: 9,
                    fontWeight: 700,
                    background: TIER_COLOUR[selected.tier] ?? '#334155',
                    color: '#fff',
                  }}
                >
                  TIER {selected.tier}
                </span>
              </div>
              <div style={{ marginBottom: 2 }}><strong>Type:</strong> {selected.drone_type}</div>
              <div style={{ marginBottom: 2 }}><strong>Position:</strong> ({Math.round(selected.position.x)}m E, {Math.round(selected.position.y)}m N, {Math.round(selected.position.z)}m Alt)</div>
              <div style={{ marginBottom: 2 }}><strong>Velocity:</strong> ({selected.velocity.vx.toFixed(1)}, {selected.velocity.vy.toFixed(1)}, {selected.velocity.vz.toFixed(1)}) m/s</div>
              <div style={{ marginBottom: 2 }}><strong>Speed:</strong> {Math.sqrt(selected.velocity.vx**2 + selected.velocity.vy**2).toFixed(1)} m/s</div>
              <div style={{ marginBottom: 2 }}><strong>Confidence:</strong> {Math.round((selected.score ?? selected.confidence) * 100)}%</div>
              <div style={{ marginBottom: 2 }}><strong>Sensors:</strong> {selected.sensor_layers.map(l => (
                <span key={l} style={{ 
                  marginRight: 4, 
                  padding: '1px 6px', 
                  borderRadius: 4, 
                  fontSize: 9, 
                  background: LAYER_COLOUR[l as SensorLayer], 
                  color: '#fff' 
                }}>{l.toUpperCase()}</span>
              ))}</div>
              {selected.swarm_id !== null && (
                <div style={{ marginBottom: 2, color: '#fbbf24' }}>
                  <strong>Swarm #{selected.swarm_id}</strong> — {selected.swarm_size} members
                </div>
              )}
              <div style={{ marginBottom: 2 }}><strong>Impact Prob:</strong> {Math.round((selected.impact ? 80 : 20))}%</div>
            </div>
          </Popup>
        )}
      </MapGL>

      {/* Layer toggles */}
      <div style={{ position: 'absolute', top: 50, left: 12, zIndex: 100, display: 'flex', flexDirection: 'column', gap: 4 }}>
        <button onClick={() => mapRef.current?.flyTo({ center: [cLon, cLat], zoom: 11.5, duration: 500 })} style={btnStyle}>Reset View</button>
      </div>

      {/* Attribution */}
      <div
        style={{
          position: 'absolute',
          bottom: 4,
          right: 4,
          fontSize: 9,
          color: '#475569',
          pointerEvents: 'none',
        }}
      >
        © OpenFreeMap · © OpenStreetMap contributors
      </div>
    </div>
  );
}

const btnStyle: React.CSSProperties = {
  background: '#1e293b',
  color: '#e2e8f0',
  border: '1px solid #334155',
  borderRadius: 4,
  padding: '4px 10px',
  fontSize: 11,
  cursor: 'pointer',
};
