# ARTEMIS Architecture

## 1. System Overview

ARTEMIS is a distributed counter-UAV detection system comprising:

- **Hub** — central aggregation, fusion, cognition, and API server
- **Nodes** — edge sensor units (Raspberry Pi 5) deployed around the protected area
- **Dashboard** — real-time web UI (Next.js + Three.js) connected to the Hub API

```
┌──────────────────────────────────────────────────────────────┐
│                        ARTEMIS Hub                           │
│                                                              │
│  ┌────────────┐   ┌──────────────┐   ┌───────────────────┐  │
│  │  MQTT      │   │  Mesh        │   │  Track Manager    │  │
│  │  Broker    │──►│  Aggregator  │──►│  (EKF + DBSCAN)   │  │
│  │(Mosquitto) │   └──────────────┘   └────────┬──────────┘  │
│  └────────────┘                               │             │
│                                         ┌─────▼──────┐      │
│                                         │  Cognition │      │
│                                         │  Pipeline  │      │
│                                         │  (Scorer → │      │
│                                         │   Router)  │      │
│                                         └─────┬──────┘      │
│  ┌────────────┐   ┌──────────────┐      ┌─────▼──────┐      │
│  │  REST API  │   │  WebSocket   │      │  Effector  │      │
│  │  (FastAPI) │   │  Feed        │      │  Manager   │      │
│  └────────────┘   └──────────────┘      └────────────┘      │
└──────────────────────────────────────────────────────────────┘
         ▲  MQTT                                │  MQTT
         │  detections                          │  commands
┌────────┴───────────────────┐        ┌─────────▼──────────┐
│   ARTEMIS Node (RPi 5)     │        │  ARTEMIS Node      │
│                            │        │  (effector target) │
│  RF → RTLSDRListener       │        └────────────────────┘
│  Acoustic → AcousticClassifier
│  Radar → XM125Processor    │
│  Optical → OpticalDetector │
└────────────────────────────┘
```

---

## 2. Module Map

```
artemis/
├── action/
│   └── effectors/
│       ├── effector_manager.py   EffectorManager — registry + dispatch
│       ├── sim_relay.py          SimRelay — MQTT-based simulation relay
│       └── gpio_relay.py         GPIORelay — RPi GPIO hardware relay
├── api/
│   ├── rest.py                   FastAPI app factory, /api/* endpoints
│   ├── websocket.py              /ws endpoint, push ThreatMap at N Hz
│   ├── auth.py                   JWT bearer token validation
│   ├── metrics.py                Prometheus /metrics endpoint
│   └── rate_limit.py             slowapi rate limiter setup
├── cognition/
│   ├── pipeline.py               CognitionPipeline — orchestrates agents
│   └── agents/
│       ├── threat_scorer.py      Score tracks 0→1 using heuristics + model
│       ├── classifier_agent.py   TFLite acoustic/RF classification
│       ├── command_router.py     Map threat score → effector command
│       └── scheduler_agent.py    Deconflict simultaneous commands
├── core/
│   ├── config.py                 HubConfig + NodeConfig dataclass loaders
│   ├── config_validator.py       Env-var overrides + validation warnings
│   ├── logging.py                JSON structured logger
│   └── types.py                  Shared dataclasses (Detection, Track, …)
├── fusion/
│   ├── track_manager.py          EKF tracker + Hungarian assignment + DBSCAN
│   ├── threat_map.py             Thread-safe ThreatMap snapshot store
│   └── sensor_fusion.py          Per-track sensor-layer fusion helpers
├── mesh/
│   ├── aggregator.py             MeshAggregator — MQTT subscriber + fan-out
│   └── publisher.py              MQTTPublisher — typed publish helpers
└── perception/
    ├── base.py                   PerceptionDriver ABC, DriverStatus enum
    ├── acoustic/
    │   └── classifier.py         AcousticClassifier (sounddevice + TFLite)
    ├── optical/
    │   └── detector.py           OpticalDetector (picamera2/OpenCV + MOG2)
    ├── radar/
    │   └── xm125_processor.py    XM125Processor (Acconeer exptool)
    └── rf/
        └── rtlsdr_listener.py    RTLSDRListener (pyrtlsdr + FFT)
```

---

## 3. Data Flow

```
Sensor hardware
    │  raw samples (IQ / audio / range / frames)
    ▼
PerceptionDriver.stream()         [per sensor, async generator]
    │  Detection(node_id, layer, lat, lon, confidence, meta)
    ▼
MQTTPublisher.publish_<layer>()   [node → broker]
    │  JSON on artemis/nodes/<id>/detections/<layer>
    ▼
MeshAggregator._on_message()      [hub, MQTT callback]
    │  Detection deserialized
    ▼
TrackManager.update()             [EKF predict + update + assign]
    │  Track list (confirmed / coasting)
    ▼
ThreatMap.update_snapshot()       [atomic swap]
    │  ThreatMapSnapshot
    ▼
CognitionPipeline  [ThreatScorer → CommandRouter → SchedulerAgent]
    │  EngagementCommand
    ▼
EffectorManager.dispatch()        [SimRelay / GPIORelay]

                     ╔══════════════╗
ThreatMap ──────────►║  WebSocket   ║──► Dashboard (Three.js 3D map)
ThreatMap ──────────►║  REST API    ║──► External integrations
                     ╚══════════════╝
```

---

## 4. Key Design Decisions

| Decision | Rationale |
|---|---|
| Python async (asyncio) throughout | Avoids GIL contention; sensor I/O is mostly I/O-bound |
| MQTT QoS 1 for detections | Sufficient reliability; high-rate makes QoS 2 impractical |
| EKF per track, DBSCAN for swarms | EKF is lightweight enough for RPi; DBSCAN clusters efficiently |
| Dataclasses over Pydantic for config | Zero runtime deps on edge; Pydantic only in validator layer |
| picamera2 via apt, not pip | Only option on RPi OS Bookworm (PEP 668 restricts pip) |
| JWT auth on REST | Stateless, revocable via exp claim; no DB required |

---

## 5. Port Reference

| Service | Port | Protocol |
|---|---|---|
| MQTT broker | 1883 | TCP |
| MQTT broker (TLS, future) | 8883 | TCP/TLS |
| Hub REST API | 8080 | HTTP |
| Hub WebSocket | 8080 | WS (same server) |
| Dashboard dev server | 3000 | HTTP |
| Prometheus metrics | 8080/metrics | HTTP |
