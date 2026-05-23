'use client';
/**
 * ThreatMap.tsx — ARTEMIS real-world threat map using MapLibre GL JS.
 *
 * Base tiles: OpenFreeMap "dark" style — completely free, no API key, OSM data.
 *
 * Coordinate system: threats arrive in local Cartesian metres from hub:
 *   x → East,  y → Altitude,  z → South  (−z = North)
 * Converted to WGS-84 [lon, lat] for MapLibre rendering.
 *
 * Controls: drag to pan, scroll to zoom, right-drag / Ctrl+drag to tilt/rotate.
 * Click a threat circle to inspect details.
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
import type { FeatureCollection, Feature, LineString, Point } from 'geojson';
import type { Threat } from '../types';

// ── Config ────────────────────────────────────────────────────────────────────
const MAP_STYLE   = 'https://tiles.openfreemap.org/styles/dark';
const TRAIL_LEN   = 8;

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

/** Detection-layer range rings — matches README sensor specs. */
const RINGS = [
  { r: 300,  label: '300 m · Acoustic/Optical', color: '#10b981' },
  { r: 1000, label: '1 km · RF close',          color: '#3b82f6' },
  { r: 3000, label: '3 km · RF typical',        color: '#6366f1' },
  { r: 5000, label: '5 km · RF max',            color: '#8b5cf6' },
] as const;

// ── Geo helpers ───────────────────────────────────────────────────────────────

/** Convert local Cartesian metres (x=East, z=South) to [lon, lat]. */
function toCoord(x: number, z: number, cLat: number, cLon: number): [number, number] {
  const lat = cLat + (-z) / 111_319.9;
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

// ── Props ─────────────────────────────────────────────────────────────────────
interface Props {
  threats:    Threat[];
  centerLat?: number;
  centerLon?: number;
}

// ── Component ─────────────────────────────────────────────────────────────────
export default function ThreatMap({
  threats,
  centerLat = DEFAULT_LAT,
  centerLon = DEFAULT_LON,
}: Props) {
  const mapRef    = useRef<MapRef>(null);
  const trailsRef = useRef<globalThis.Map<string, [number, number][]>>(
    new globalThis.Map(),
  );
  const [selected, setSelected] = useState<Threat | null>(null);

  // ── Real GPS: use browser geolocation, fall back to props/default ─────────
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
      () => { /* permission denied or unavailable — keep default */ },
      { enableHighAccuracy: true, timeout: 10_000 },
    );
  }, []);

  // ── Update trail history (synchronous derivation) ─────────────────────────
  useMemo(() => {
    const trails = trailsRef.current;
    const alive  = new Set(threats.map((t) => t.threat_id));
    for (const id of trails.keys()) if (!alive.has(id)) trails.delete(id);
    for (const t of threats) {
      const coord = toCoord(t.position.x, t.position.z, cLat, cLon);
      const pts   = trails.get(t.threat_id) ?? [];
      pts.push(coord);
      if (pts.length > TRAIL_LEN) pts.splice(0, pts.length - TRAIL_LEN);
      trails.set(t.threat_id, pts);
    }
  }, [threats, cLat, cLon]);

  // ── GeoJSON: threat circles ───────────────────────────────────────────────
  const threatGeoJSON = useMemo((): FeatureCollection<Point> => ({
    type: 'FeatureCollection',
    features: threats.map((t): Feature<Point> => {
      const [lon, lat] = toCoord(t.position.x, t.position.z, cLat, cLon);
      return {
        type: 'Feature',
        id: t.threat_id,
        properties: {
          id:    t.threat_id,
          color: TIER_COLOUR[t.tier] ?? '#ffffff',
          label: `T${t.tier}`,
          alt:   Math.round(t.position.y),
        },
        geometry: { type: 'Point', coordinates: [lon, lat] },
      };
    }),
  }), [threats, cLat, cLon]);

  // ── GeoJSON: trails ───────────────────────────────────────────────────────
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

  // ── GeoJSON: range rings ──────────────────────────────────────────────────
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

  // ── Click handler ─────────────────────────────────────────────────────────
  const handleClick = useCallback(
    (e: { features?: Array<{ properties?: Record<string, unknown> | null }> }) => {
      const id = e.features?.[0]?.properties?.['id'] as string | undefined;
      if (!id) { setSelected(null); return; }
      setSelected(threats.find((t) => t.threat_id === id) ?? null);
    },
    [threats],
  );

  const popupCoords = selected
    ? toCoord(selected.position.x, selected.position.z, cLat, cLon)
    : null;

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div style={{ position: 'relative', width: '100%', height: '100%', minHeight: 440 }}>
      <MapGL
        ref={mapRef}
        mapStyle={MAP_STYLE}
        initialViewState={{
          longitude: cLon,
          latitude:  cLat,
          zoom:      11.5,
          pitch:     25,
          bearing:   0,
        }}
        style={{ width: '100%', height: '100%' }}
        interactiveLayerIds={['threat-circles']}
        onClick={handleClick as Parameters<typeof MapGL>[0]['onClick']}
        attributionControl={false}
      >
        <NavigationControl position="top-right" />

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

        {/* ── Threat trails ─────────────────────────────────────────── */}
        <Source id="trails" type="geojson" data={trailGeoJSON}>
          <Layer
            id="trail-lines"
            type="line"
            paint={{
              'line-color': ['get', 'color'],
              'line-width': 1.5,
              'line-opacity': 0.45,
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
                12, 7,
                16, 16,
              ],
              'circle-color': ['get', 'color'],
              'circle-opacity': 0.85,
              'circle-stroke-width': 1.5,
              'circle-stroke-color': '#ffffff',
            }}
          />
          <Layer
            id="threat-labels"
            type="symbol"
            layout={{
              'text-field': ['get', 'label'],
              'text-size': 10,
              'text-offset': [0, 1.6],
              'text-anchor': 'top',
            }}
            paint={{
              'text-color': '#e2e8f0',
              'text-halo-color': '#080d14',
              'text-halo-width': 1.5,
            }}
          />
        </Source>

        {/* ── Hub marker ────────────────────────────────────────────── */}
        <Marker longitude={cLon} latitude={cLat}>
          <div
            title="Hub"
            style={{
              width: 16,
              height: 16,
              borderRadius: '50%',
              background: '#3b82f6',
              border: '2px solid #93c5fd',
              boxShadow: '0 0 10px #3b82f6',
              cursor: 'default',
            }}
          />
        </Marker>

        {/* ── Threat detail popup ───────────────────────────────────── */}
        {selected && popupCoords && (
          <Popup
            longitude={popupCoords[0]}
            latitude={popupCoords[1]}
            closeButton
            onClose={() => setSelected(null)}
            anchor="bottom"
            style={{ color: '#0f172a', fontSize: 12 }}
          >
            <div style={{ minWidth: 170 }}>
              <strong style={{ display: 'block', marginBottom: 4 }}>
                Track {selected.track_id.slice(-6)}
              </strong>
              <div>Tier {selected.tier} — {selected.drone_type}</div>
              <div>Altitude: {Math.round(selected.position.y)} m</div>
              <div>
                Confidence:{' '}
                {Math.round((selected.score ?? selected.confidence) * 100)}%
              </div>
              <div>Sensors: {selected.sensor_layers.join(', ')}</div>
            </div>
          </Popup>
        )}
      </MapGL>

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
