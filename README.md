# ARTEMIS v1

**Agentic Response & Tactical Engagement with Multi-agent Intelligence System**

[![GitHub](https://img.shields.io/badge/GitHub-manu14357%2FArtemis-blue?logo=github)](https://github.com/manu14357/Artemis)
[![Sponsor](https://img.shields.io/badge/Sponsor-%E2%9D%A4-pink?logo=github-sponsors)](https://github.com/sponsors/manu14357)

> Open-source, multi-sensor counter-drone platform running on commodity Raspberry Pi 5 hardware.  
> Status: **Pre-Alpha / Research Framework** | Version: 1.0.0 | May 2026

---

## What Is ARTEMIS?

ARTEMIS v1 is **not** a single device — it is a distributed sensor mesh where each node contributes perception data, and a central hub fuses all signals into a unified threat picture. Every node is a Raspberry Pi 5 with four commodity sensors (~$285/node), running a 4-layer detection pipeline entirely on CPU.

### Three Core Bets

| Bet | Claim | Technical Basis |
|-----|-------|----------------|
| **Bet 1** | Detect at 1–5 km via RF before the drone is visible | RTL-SDR passive listening on 2.4 / 5.8 GHz / 900 MHz |
| **Bet 2** | No YOLO, no GPU — background subtraction is better | OpenCV MOG2 + Lucas-Kanade optical flow on RPi 5 CPU |
| **Bet 3** | $280/node vs $3M Patriot — software is the moat | Raspberry Pi 5 + 4 commodity sensors per node |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        ARTEMIS NODE (RPi 5)                     │
│                                                                 │
│  Layer 1 ── RF (RTL-SDR)        1–5 km  ──► FFT peak detect    │
│  Layer 2 ── Acoustic (4-mic)  100–500 m ──► MobileNetV2 CNN    │
│  Layer 3 ── Radar (XM125)      0–20 m   ──► micro-Doppler      │
│  Layer 4 ── Optical (Camera)   0–200 m  ──► MOG2 + opt-flow    │
│                         │                                       │
│                    ┌────▼────┐                                  │
│                    │ FUSION  │  EKF track manager               │
│                    │ ENGINE  │  Hungarian assignment            │
│                    │         │  DBSCAN swarm detection          │
│                    └────┬────┘                                  │
│                         │                                       │
│                ┌────────▼────────┐                              │
│                │  COGNITION /    │  Classifier Agent            │
│                │  AI AGENTS      │  Predictor Agent             │
│                │                 │  Scheduler Agent             │
│                │                 │  Spoof Agent (sim only)      │
│                └────────┬────────┘                              │
└─────────────────────────┼───────────────────────────────────────┘
                          │ MQTT
        ┌─────────────────▼─────────────────┐
        │           HUB (Aggregator)        │
        │   Multi-node fusion · FastAPI     │
        │   WebSocket feed · Threat map     │
        └─────────────────┬─────────────────┘
                          │
                ┌─────────▼─────────┐
                │    DASHBOARD      │
                │  Next.js + Three.js│
                │  3D threat map    │
                └───────────────────┘
```

### Detection Layers at a Glance

| Layer | Sensor | Range | Method | Latency |
|-------|--------|-------|--------|---------|
| RF | RTL-SDR Blog V4 | 200 m – 3 km | FFT energy peak on 2.4/5.8 GHz/900 MHz | < 100 ms |
| Acoustic | ReSpeaker 4-Mic Array | 50 – 300 m | STFT mel spectrogram → MobileNetV2 TFLite | < 300 ms |
| Radar | Acconeer XM125 | 0.5 – 20 m | Micro-Doppler IQ processing | < 50 ms |
| Optical | Pi Camera Module 3 NoIR | 0 – 200 m | MOG2 background subtraction + Lucas-Kanade | < 33 ms |

> **Radar range note:** The XM125 is a short-range sensor (max ~20 m). For 300 m+ radar detection, upgrade to the TI IWR6843 (~$80–120). See [docs/SENSOR_GUIDE.md](docs/SENSOR_GUIDE.md).

---

## Hardware Bill of Materials (per node)

| Component | Model | Purpose | Approx. Cost |
|-----------|-------|---------|-------------|
| SBC | Raspberry Pi 5 (8 GB) | Main compute | $80 |
| RF dongle | RTL-SDR Blog V4 | 2.4/5.8 GHz/900 MHz passive RX | $35 |
| Microphone array | ReSpeaker 4-Mic v2 (USB) | Acoustic detection + TDOA bearing | $40 |
| Radar | Acconeer XM125 | Micro-Doppler short-range confirmation | $30 |
| Camera | Pi Camera Module 3 NoIR | Optical detection (no-IR filter for night) | $35 |
| Power | PoE HAT+ | Power + Ethernet via a single cable | $30 |
| Storage | 64 GB microSD (A2 rated) | OS + models + logs | $15 |
| Enclosure + misc | Weatherproof case, cables | Field deployment | ~$20 |
| **Total per node** | | | **~$285** |

### Multi-Node Coverage Estimates

| # Nodes | Area Coverage | Hardware Cost | Setup Time |
|---------|--------------|--------------|-----------|
| 1 | ~0.3 km² (directional) | $285 | 2–3 days |
| 3 | ~1 km² (triangle) | $855 | 1 week |
| 6 | ~2 km² (hexagonal) | $1,710 | 2 weeks |
| 12 | ~5 km² (full perimeter) | $3,420 | 1 month |

---

## Quickstart — Simulation Mode (No Hardware Required)

Run the entire ARTEMIS stack on any laptop. No physical sensors needed.

### Prerequisites

- Python 3.11+
- Node.js 18+
- [Mosquitto MQTT broker](https://mosquitto.org/download/)

### Steps

```bash
# 1. Clone the repository
git clone https://github.com/your-org/artemis.git
cd artemis

# 2. Python environment
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Terminal A — MQTT broker
mosquitto -c /etc/mosquitto/mosquitto.conf

# 4. Terminal B — Drone swarm simulator
python sim/drone_swarm.py --scenario sim/scenarios/10_drone_swarm.yaml

# 5. Terminal C — Hub fusion engine
python hub/main.py --config hub/config/hub_default.yaml

# 6. Terminal D — Dashboard
cd dashboard
npm install
cp .env.local.example .env.local   # defaults point to localhost:8080
npm run dev
# Open http://localhost:3000
```

---

## Hardware Setup

### Phase 1 — Single Node (Raspberry Pi 5)

**Step 1: Flash Raspberry Pi OS**

Use [Raspberry Pi Imager](https://www.raspberrypi.com/software/):
- OS: **Raspberry Pi OS (64-bit) Bookworm**
- Enable SSH; set hostname: `artemis-node-01`
- Recommend PoE HAT+ for power + Ethernet via single cable

```bash
# After first boot
sudo apt update && sudo apt upgrade -y
```

**Step 2: One-command node setup**

```bash
curl -sSL https://raw.githubusercontent.com/your-org/artemis/main/scripts/setup_node.sh | bash
```

This installs: Python 3.11, RTL-SDR drivers, GNU Radio, libcamera2, ALSA/PortAudio, Mosquitto, Acconeer exploration tool, ARTEMIS Python package, and registers the `artemis-node` systemd service.

**Step 3: Sensor wiring**

| Sensor | Interface | RPi Connection | Notes |
|--------|-----------|---------------|-------|
| RTL-SDR Blog V4 | USB | Any USB 3.0 port | Use USB extension for antenna positioning |
| ReSpeaker 4-Mic v2 | USB | Any USB port | USB version recommended over I2S |
| Acconeer XM125 | UART via USB-UART adapter | Any USB port | **Flash exploration firmware first** — see [docs/SENSOR_GUIDE.md](docs/SENSOR_GUIDE.md) |
| Pi Camera Module 3 NoIR | CSI-2 | Camera ribbon connector | Enable via `raspi-config` |
| GPIO Relay Board | GPIO | Pins 11,13,15,16 (GPIO 17,27,22,23) | Check 3.3 V compatibility |

**Step 4: Configure the node**

Edit `node/config/node_default.yaml` — set your GPS coordinates and MQTT broker IP (your hub's IP):

```yaml
node:
  id: 'node-01'
  location:
    lat: 17.3850
    lon: 78.4867
    alt_m: 540
mqtt:
  broker: 192.168.1.100   # Hub IP address
```

**Step 5: Test sensors individually**

```bash
python scripts/test_rf.py        # RTL-SDR OK, detected X signals
python scripts/test_acoustic.py  # Mic array OK, 4 channels active
python scripts/test_radar.py     # Acconeer XM125 OK, IQ frames streaming
python scripts/test_optical.py   # Camera OK, background model training...

# Integrated self-test
python node/main.py --test-mode --config node/config/node_default.yaml
```

**Step 6: Start the node daemon**

```bash
sudo systemctl enable artemis-node
sudo systemctl start artemis-node
sudo journalctl -u artemis-node -f   # follow logs
```

---

### Phase 2 — Multi-Node Mesh

Deploy nodes at corners/edges of the perimeter. Each node needs Ethernet (PoE recommended) or WiFi to reach the hub.

```bash
# On the hub machine
python hub/main.py --config hub/config/hub_default.yaml
# Hub subscribes to artemis/nodes/+/# and aggregates all sensor streams
```

MQTT topic schema:

| Topic | Publisher | Subscriber | Rate |
|-------|-----------|-----------|------|
| `artemis/nodes/{id}/rf` | Node | Hub | On detection |
| `artemis/nodes/{id}/acoustic` | Node | Hub | Every 500 ms |
| `artemis/nodes/{id}/radar` | Node | Hub | Every 50 ms |
| `artemis/nodes/{id}/optical` | Node | Hub | Every 33 ms |
| `artemis/threats` | Hub | All nodes + Dashboard | On threat update |
| `artemis/commands/{id}` | Hub | Specific effector | On engagement decision |
| `artemis/nodes/{id}/status` | Node | Hub + Dashboard | Every 1 s |

---

### Phase 3 — Dashboard

The dashboard is built with **Next.js 14** (App Router) + **Three.js**.

```bash
cd dashboard
npm install

# Copy and fill in environment variables
cp .env.local.example .env.local
# Edit .env.local:
# NEXT_PUBLIC_HUB_URL=http://192.168.1.100:8080
# NEXT_PUBLIC_HUB_WS_URL=ws://192.168.1.100:8080/ws

npm run dev     # Development — http://localhost:3000  (Turbopack)
npm run build   # Production build → .next/
npm run start   # Serve production build on :3000
```

---

## Acoustic Model Training

The acoustic CNN (`models/acoustic_drone_cnn.tflite`) **is not pre-supplied** — you must train it with your own data collected using your exact hardware setup.

### Dataset Requirements

| Class | Minimum Samples | Collection Method |
|-------|----------------|-----------------|
| `drone_present` | 5,000+ × 500 ms clips | Record real drones at various ranges and approach angles |
| `drone_absent` | 5,000+ × 500 ms clips | Ambient noise: wind, traffic, birds, rain, silence |

### Public Datasets to Bootstrap Training

- [DroneAudioDataset](https://github.com/gumberss/DroneAudioDataset) — 4 drone types + ambient
- [ESC-50](https://github.com/karolpiczak/ESC-50) — Environmental Sound Classification (ambient augmentation)
- DCASE 2023 — Drone detection challenge dataset

### Training

```bash
python scripts/train_acoustic_model.py \
    --drone-clips data/drone/ \
    --ambient-clips data/ambient/ \
    --epochs 50 \
    --output models/acoustic_drone_cnn.tflite

# Expected accuracy (well-collected dataset): 90–96%
# Inference time on RPi 5: 180–280 ms
# Inference time with Hailo-8L accelerator: 20–40 ms
```

---

## Directory Structure

```
artemis/
├── README.md
├── LICENSE
├── CONTRIBUTING.md
├── SECURITY.md
├── package.json                      # Doc generator (artemis_docs.js)
├── requirements.txt                  # Python dependencies
├── .gitignore
│
├── artemis/                          # Core Python package
│   ├── core/                         # Config loader, event bus, shared types
│   ├── perception/
│   │   ├── rf/                       # RTL-SDR listener + fingerprinter
│   │   ├── acoustic/                 # Mic reader, STFT, CNN classifier
│   │   ├── radar/                    # Acconeer XM125 reader + Doppler processor
│   │   └── optical/                  # Camera reader, MOG2, optical flow
│   ├── fusion/                       # EKF, track manager, Hungarian, DBSCAN
│   ├── cognition/agents/             # Classifier, Predictor, Scheduler, Spoof agents
│   ├── action/effectors/             # GPIO relay, RF jammer (sim only)
│   ├── mesh/                         # MQTT publisher, subscriber, aggregator
│   └── api/                          # FastAPI REST + WebSocket
│
├── node/
│   ├── main.py
│   ├── config/node_default.yaml
│   └── systemd/artemis-node.service
│
├── hub/
│   ├── main.py
│   └── config/hub_default.yaml
│
├── dashboard/                        # Next.js 14 + Three.js (App Router)
│   └── src/
│       ├── app/                      # Next.js app directory
│       │   ├── layout.tsx            # Root layout (Server Component)
│       │   ├── page.tsx              # Dashboard page ('use client')
│       │   └── globals.css
│       ├── components/
│       │   ├── ThreatMap.tsx
│       │   ├── NodeStatus.tsx
│       │   ├── DetectionFeed.tsx
│       │   └── EffectorPanel.tsx
│       ├── hooks/useArtemisWS.ts
│       └── types.ts
│
├── sim/
│   ├── drone_swarm.py
│   ├── rf_emulator.py
│   ├── acoustic_emulator.py
│   └── scenarios/
│       ├── single_drone.yaml
│       ├── 10_drone_swarm.yaml
│       └── 1000_drone_swarm.yaml
│
├── models/                           # Place trained .tflite / .onnx files here
├── scripts/                          # setup_node.sh, test_*.py, train_acoustic_model.py
├── tests/unit/ tests/integration/ tests/load/
├── infra/docker-compose.yml infra/k8s/
└── docs/
    ├── ARCHITECTURE.md
    ├── NODE_SETUP.md
    ├── SENSOR_GUIDE.md
    ├── DETECTION_LOGIC.md
    ├── MESH_PROTOCOL.md
    └── LEGAL.md
```

---

## Performance Targets

| Stage | Target | Realistic Expectation | Notes |
|-------|--------|----------------------|-------|
| RF detection | < 100 ms | 50–150 ms | Achievable with tuned FFT |
| Acoustic classification | < 300 ms | 200–400 ms | Depends on TFLite model size |
| Radar detection | < 50 ms | 50–100 ms | After correct UART setup |
| Optical detection | < 33 ms | 33–66 ms | Depends on resolution |
| Fusion (track confirmed) | < 200 ms total | 150–400 ms | Very achievable |
| End-to-end: detect → command | < 500 ms | 300 ms–1.5 s | Pipeline latency varies |
| RF detection range | 1–5 km | 200 m–2 km realistic | Depends on antenna + RF noise floor |
| Radar range (XM125) | — | 0.5–20 m (actual) | Upgrade to IWR6843 for 300 m |
| Acoustic range | 100–500 m | 50–300 m typical | Environment-dependent |

### CPU Load on RPi 5 (per node, all layers active)

| Process | CPU | RAM |
|---------|-----|-----|
| RF FFT scanning | 8–15 % | 50 MB |
| Acoustic STFT + TFLite | 25–40 % | 150 MB |
| Radar data processing | 5–10 % | 30 MB |
| Optical flow (640×480 @ 30 fps) | 20–35 % | 80 MB |
| Fusion + Kalman | 5–10 % | 40 MB |
| MQTT + FastAPI | 3–5 % | 30 MB |
| **Total (all layers)** | **65–115 % (1 core)** | **380 MB** |

*RPi 5 has 4 × ARM Cortex-A76 cores. asyncio distributes load across cores; typical wall-clock stays below 80 % total.*

---

## Development Roadmap

| Phase | Duration | Deliverables | Prerequisites |
|-------|----------|-------------|--------------|
| **Phase 0** — Simulation | Month 1 | Full sim stack + dashboard on any laptop | Python 3.11, Node.js 18 |
| **Phase 1** — Single Node | Months 2–3 | RF + Acoustic + Optical on live RPi | Hardware ($285) + trained acoustic model |
| **Phase 2** — Radar + Mesh | Months 4–6 | Radar integration + 2-node MQTT mesh + triangulation | XM125 + corrected firmware; 2 nodes |
| **Phase 3** — Decision + Effectors | Months 7–9 | AI agent network + GPIO relay (sim effectors) | Phase 1+2 complete |
| **Phase 4** — Area Shield | Months 10–12 | 6-node production perimeter deployment | Test range + institutional support |

---

## Legal Notice

> **Read before deploying.**

| Component | India | USA | EU |
|-----------|-------|-----|----|
| RF listening (passive receive) | Legal | Legal | Legal |
| Acoustic monitoring (outdoor) | Legal | Legal | Legal (privacy laws apply) |
| Camera monitoring (public airspace) | Legal | Legal | Legal (GDPR may apply) |
| Radar detection (passive) | Legal | Legal | Legal |
| **RF jamming** | **ILLEGAL** | **ILLEGAL (FCC)** | **ILLEGAL** |
| **GPS spoofing** | **ILLEGAL** | **ILLEGAL (18 U.S.C. § 32)** | **ILLEGAL** |
| Counter-drone interception | Requires MHA auth | Requires FAA/DoD auth | Requires national authority auth |

**All effector modules** (`rf_jammer.py`, `gps_spoofer.py`) are **simulation-only by default** and require an explicit `--enable-effectors` flag. Do not activate them without written authorization from the relevant authority.

For India-specific guidance, see [docs/LEGAL.md](docs/LEGAL.md).

---

## Contributing

1. Fork the repository and create a feature branch.
2. Run the test suite: `pytest tests/unit/`
3. For sensor driver changes, include output from the relevant `scripts/test_*.py` script.
4. Submit a pull request with a clear description of the change and any hardware tested.

Please read `CONTRIBUTING.md` and `SECURITY.md` before submitting.

---

## License

MIT License — see [LICENSE](LICENSE).

---

---

## Contributors

| Contributor | Role | GitHub |
|-------------|------|--------|
| **Manu** | Creator & Lead Developer | [@manu14357](https://github.com/manu14357) |

Want to contribute? Open a pull request on [GitHub](https://github.com/manu14357/Artemis) or raise an issue.

## Sponsor

If ARTEMIS is useful to your research or organization, consider supporting development:

[![Sponsor manu14357](https://img.shields.io/badge/Sponsor-%E2%9D%A4-pink?logo=github-sponsors&style=for-the-badge)](https://github.com/sponsors/manu14357)

---

*ARTEMIS v1 — Full Technical Documentation available in [docs/FULL_DOCUMENTATION.md](docs/artemis.md).*
*Hardware wiring, sensor setup & commissioning guide: [docs/HARDWARE_SETUP.md](docs/HARDWARE_SETUP.md).*
