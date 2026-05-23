/**
 * Types matching the hub REST/WebSocket API responses exactly.
 *
 * Python Threat.to_dict() returns:
 *   position: {x, y, z}  (local Cartesian metres from hub reference)
 *   velocity: {vx, vy, vz}
 *   timestamp: float (Unix epoch seconds)
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
  sensor_layers: string[];
  /** Unix epoch seconds */
  timestamp:     number;
  /** 0–1 overall track quality score */
  confidence:    number;
}

export interface NodeStatusLocation {
  lat:   number;
  lon:   number;
  alt_m: number;
}

export interface NodeStatus {
  node_id:        string;
  location:       NodeStatusLocation;
  sensors_active: string[];
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
