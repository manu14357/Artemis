# ARTEMIS Mesh Protocol

This document describes the MQTT topic schema, message formats, QoS/retain flags,
and connection patterns used for inter-node and hub communication.

---

## 1. Broker Configuration

All nodes and the hub connect to a single Mosquitto 2.x broker hosted on the hub.
Default connection parameters:

| Parameter | Default |
|---|---|
| Host | `127.0.0.1` (hub-local) / hub IP (nodes) |
| Port | `1883` (plain) / `8883` (TLS — future) |
| Keep-alive | 60 s |
| Clean session | `true` |
| QoS default | 1 (at-least-once) |

---

## 2. Topic Schema

```
artemis/
├── nodes/
│   ├── <node-id>/detections/<layer>     ← node → hub  (sensor detections)
│   └── <node-id>/status                 ← node → hub  (heartbeat)
├── threats/                             ← hub  → all  (fused threat map)
└── commands/<node-id>                   ← hub  → node (effector commands)
```

`<node-id>` is the value of `node.id` in `node_default.yaml` (e.g. `node-01`).  
`<layer>` is one of: `rf`, `acoustic`, `radar`, `optical`.

---

## 3. Message Formats

All payloads are UTF-8 JSON. Times use Unix epoch seconds (float).

### 3.1 Detection (node → hub)

Published to: `artemis/nodes/<node-id>/detections/<layer>`

```json
{
  "node_id": "node-01",
  "layer":   "rf",
  "ts":      1716460800.123,
  "lat":     28.6139,
  "lon":     77.2090,
  "alt_m":   216.0,
  "confidence": 0.87,
  "meta": {
    "frequency_hz": 2437000000,
    "power_db": -42.5,
    "bandwidth_hz": 20000000
  }
}
```

Layer-specific `meta` fields:

| Layer | Key meta fields |
|---|---|
| `rf` | `frequency_hz`, `power_db`, `bandwidth_hz` |
| `acoustic` | `class_label`, `mel_confidence`, `sample_rate` |
| `radar` | `range_m`, `velocity_ms`, `snr_db` |
| `optical` | `bbox_xywh`, `blob_area_px`, `frame_id` |

### 3.2 Node Status / Heartbeat (node → hub)

Published to: `artemis/nodes/<node-id>/status`  
QoS: 1, Retain: `true`

```json
{
  "node_id":     "node-01",
  "ts":          1716460800.0,
  "lat":         28.6139,
  "lon":         77.2090,
  "alt_m":       216.0,
  "cpu_pct":     12.4,
  "mem_pct":     38.1,
  "active_layers": ["rf", "acoustic", "radar", "optical"]
}
```

### 3.3 Threat Map Update (hub → all)

Published to: `artemis/threats`  
QoS: 1, Retain: `true`

```json
{
  "ts": 1716460800.5,
  "tracks": [
    {
      "track_id":   "trk-00042",
      "lat":        28.6145,
      "lon":        77.2098,
      "alt_m":      85.0,
      "vel_ms":     [2.1, -0.5, 0.0],
      "confidence": 0.94,
      "layers":     ["rf", "radar"],
      "swarm_id":   null,
      "threat_score": 0.82,
      "last_seen":  1716460800.4
    }
  ],
  "swarms": [
    {
      "swarm_id":  "swarm-001",
      "centroid":  {"lat": 28.615, "lon": 77.210, "alt_m": 80.0},
      "size":      7
    }
  ]
}
```

### 3.4 Effector Command (hub → node)

Published to: `artemis/commands/<node-id>`  
QoS: 2 (exactly-once)

```json
{
  "command_id": "cmd-00019",
  "ts":         1716460801.0,
  "action":     "jam_rf",
  "target": {
    "track_id": "trk-00042",
    "frequency_hz": 2437000000
  },
  "duration_s": 5.0,
  "authority":  "hub-01"
}
```

Known `action` values: `jam_rf`, `alert_visual`, `alert_audio`, `log_only`.

---

## 4. QoS and Retain Summary

| Topic pattern | QoS | Retain | Rationale |
|---|---|---|---|
| `artemis/nodes/+/detections/+` | 1 | false | High-rate; loss acceptable |
| `artemis/nodes/+/status` | 1 | **true** | Last status survives broker restart |
| `artemis/threats` | 1 | **true** | Dashboard reconnects see latest state |
| `artemis/commands/+` | **2** | false | Commands must not be duplicated |

---

## 5. Connection Lifecycle

```
Node boots
  │
  ├─► Connect to broker (clean_session=True, keepalive=60)
  │     LWT: topic=artemis/nodes/<id>/status  payload={"node_id":"…","ts":0}
  │
  ├─► Subscribe: artemis/commands/<node-id>  (QoS 2)
  │
  ├─► sd_notify READY=1
  │
  ├─►  [every 5 s]  Publish status heartbeat
  │
  └─►  [per detection]  Publish detection
```

The hub's `MeshAggregator` subscribes to `artemis/nodes/+/detections/#` and
`artemis/nodes/+/status`.

---

## 6. Authentication (Production)

For production deployments, enable MQTT password authentication on Mosquitto:

```bash
# Create password file
sudo mosquitto_passwd -c /etc/mosquitto/passwd artemis

# Enable in /etc/mosquitto/conf.d/artemis.conf
allow_anonymous false
password_file /etc/mosquitto/passwd

sudo systemctl restart mosquitto
```

Set credentials via env vars:
```bash
export ARTEMIS_MQTT_USERNAME=artemis
export ARTEMIS_MQTT_PASSWORD=<strong-password>
```
