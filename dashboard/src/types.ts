/**
 * Types matching the hub REST/WebSocket API responses exactly.
 *
 * Python Threat.to_dict() returns:
 *   position: {x, y, z}  (local Cartesian metres from hub reference)
 *   velocity: {vx, vy, vz}
 *   timestamp: float (Unix epoch seconds)
 *   confidence: float 0–1 (sensor layer ratio)
 *   tier: int 1–5
 *   sensor_layers: string[] e.g. ["rf", "acoustic"]
 */

export interface ThreatPosition {
  x: number;
  y: number;
  z: number;
}

export interface ThreatVelocity {
  vx: number;
  vy: number;
  vz: number;
}

export interface ThreatImpact {
  x: number;
  y: number;
}

/** Engagement tier strings emitted by CommandRouter (Phase 2) */
export type EngagementTier = 'ignore' | 'track_only' | 'engage_soft' | 'engage_hard';

/** Engagement command sent from CommandRouter via MQTT / API */
export interface Command {
  track_id:  string;
  tier:      EngagementTier;
  /** Threat scorer multi-factor score 0–1 */
  score:     number;
  position:  ThreatPosition;
  timestamp: number;
}

export type SensorLayer = 'rf' | 'acoustic' | 'radar' | 'optical';

export interface Threat {
  threat_id:     string;
  track_id:      string;
  /** 1 (low concern) – 5 (immediate lethal threat) */
  tier:          number;
  drone_type:    string;
  position:      ThreatPosition;
  velocity:      ThreatVelocity;
  /** null when no trajectory extrapolation available */
  impact:        ThreatImpact | null;
  swarm_id:      number | null;
  swarm_size:    number;
  /** e.g. ["rf", "acoustic"] */
  sensor_layers: SensorLayer[];
  /** Unix epoch seconds */
  timestamp:     number;
  /** 0–1 overall track quality score (sensor layer ratio) */
  confidence:    number;
  /** Phase 2: optional multi-factor threat score from ThreatScorer */
  score?:        number;
}

export interface NodeStatusLocation {
  lat:   number;
  lon:   number;
  alt_m: number;
}

export interface NodeStatus {
  node_id:        string;
  location:       NodeStatusLocation;
  sensors_active: SensorLayer[];
  last_heartbeat: number;
  online:         boolean;
  cpu_percent:    number;
  mem_percent:    number;
}

export interface HubStatus {
  status:       string;
  threat_count: number;
  node_count:   number;
}

/** One dispatched engagement record from GET /engagements */
export interface Engagement {
  track_id:    string;
  effector_id: string;
  tier:        EngagementTier;
  score:       number;
  position:    ThreatPosition;
  timestamp:   number;
}
