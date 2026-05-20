# ARTEMIS v1 — Full Technical Documentation

**Agentic Response & Tactical Engagement with Multi-agent Intelligence System**

> Version 1.0.0 | May 2026 | Status: Pre-Alpha Research Framework  
> Deep Research · Feasibility Assessment · Architecture · Corrections · Step-by-Step Implementation

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [System Architecture Deep Dive](#2-system-architecture-deep-dive)
3. [Corrections & Improvements to the Original README](#3-corrections--improvements-to-the-original-readme)
4. [Full Technology Stack Analysis](#4-full-technology-stack-analysis)
5. [Step-by-Step Build Guide](#5-step-by-step-build-guide)
6. [Acoustic Model Training Guide](#6-acoustic-model-training-guide)
7. [Performance Targets & Real-World Expectations](#7-performance-targets--real-world-expectations)
8. [Legal Framework](#8-legal-framework)
9. [Complete Repository Structure](#9-complete-repository-structure)
10. [Corrected Development Roadmap](#10-corrected-development-roadmap)

---

## 1. Executive Summary

ARTEMIS v1 (Agentic Response & Tactical Engagement with Multi-agent Intelligence System) is an open-source, multi-sensor counter-drone platform designed to run on commodity Raspberry Pi 5 hardware at a fraction of the cost of military-grade systems. It is **NOT** a single device — it is a distributed sensor mesh where each node contributes perception data, and a central hub fuses all signals into a unified threat picture.

### 1.1 Core Design Philosophy

Three fundamental bets set ARTEMIS apart from all competing counter-drone products:

| Bet | Claim | Technical Basis |
|-----|-------|----------------|
| **Bet 1** | Detect at 1–5 km via RF before the drone is visible | RTL-SDR passive listening on 2.4/5.8 GHz / 900 MHz |
| **Bet 2** | No YOLO, no GPU — background subtraction is better | OpenCV MOG2 + Lucas-Kanade optical flow on RPi 5 CPU |
| **Bet 3** | $280/node vs $3M Patriot — software is the moat | Raspberry Pi 5 + 4 commodity sensors per node |

### 1.2 Is Building This Application Possible?

> **✅ YES — This is Fully Buildable**
>
> ARTEMIS is not science fiction. Every individual component (RTL-SDR RF sensing, acoustic ML, radar, OpenCV optical flow, Kalman tracking, MQTT mesh, React dashboard) exists as proven open-source technology. The challenge is integration, tuning, and field calibration — not any single technical breakthrough. A simulation-mode version with a full dashboard can be running in days. A real 4-sensor node is achievable in 2–3 months.

**Feasibility breakdown by layer:**

| Layer | Component | Feasibility | Difficulty | Timeline |
|-------|-----------|-------------|-----------|---------|
| Layer 1 | RF Fingerprinting (RTL-SDR) | ✅ Fully Feasible | Medium | 2–4 weeks |
| Layer 2 | Acoustic Detection (MobileNetV2) | ✅ Fully Feasible | Medium-Hard | 4–6 weeks |
| Layer 3 | Micro-Doppler Radar (Acconeer) | ✅ Feasible with caveats | Hard | 4–8 weeks |
| Layer 4 | Optical (MOG2 + Optical Flow) | ✅ Fully Feasible | Easy-Medium | 1–2 weeks |
| Fusion | EKF + DBSCAN Track Manager | ✅ Fully Feasible | Hard | 4–6 weeks |
| Mesh | MQTT Multi-Node Network | ✅ Fully Feasible | Medium | 2–3 weeks |
| Cognition | AI Agent Decision Layer | ✅ Feasible | Hard | 6–10 weeks |
| Dashboard | React 3D Map (Three.js) | ✅ Fully Feasible | Medium | 3–4 weeks |
| Effectors | GPIO Relay + RF Jammer | ⚠️ Legal restrictions apply | Medium | 2 weeks (sim only) |
| Simulation | Full software sim mode | ✅ Trivial | Easy | 3–5 days |

---

## 2. System Architecture Deep Dive

### 2.1 Detection Stack — Four Layers

The detection pipeline is layered: each layer operates independently and in parallel. Signals from all layers are fed to the fusion engine, which maintains tracks (persistent objects in airspace) using an Extended Kalman Filter.

#### Layer 1 — RF Fingerprinting (1–5 km range)

This is the long-range early warning system. Commercial drones transmit on 2.4 GHz (most DJI/consumer), 5.8 GHz (video downlink), and 900 MHz (long-range FPV). The RTL-SDR Blog V4 dongle passively intercepts these transmissions.

| Parameter | Value | Notes |
|-----------|-------|-------|
| Detection Range | 500 m–3 km realistic, up to 5 km ideal | Depends on antenna gain and environment |
| Frequencies Monitored | 2.4 GHz, 5.8 GHz, 900 MHz | Covers 99% of commercial drones |
| Detection Method | FFT energy peak above threshold | Power Spectral Entropy also effective |
| Fingerprinting Method | RF burst timing pattern matching | DJI vs Autel vs FPV have distinct patterns |
| Latency | <100 ms from signal | Async FFT on USB stream |
| False Positive Risk | Medium (WiFi also on 2.4 GHz) | Fingerprinting helps differentiate |

#### Layer 2 — Acoustic Detection (100–500 m range)

Drone rotors create characteristic acoustic signatures at 50–400 Hz (fundamental) with strong harmonic overtones. A 4-microphone array captures this, a Short-Time Fourier Transform converts audio to mel spectrogram, and a MobileNetV2 CNN classifies it as drone/non-drone.

| Parameter | Value | Notes |
|-----------|-------|-------|
| Detection Range | 100–500 m in low ambient noise | Reduces significantly in urban noise |
| Audio Window | 500 ms STFT window | Good balance of accuracy vs latency |
| Model | MobileNetV2 on mel spectrogram | ARM-optimized TFLite, runs on RPi CPU |
| Inference Time | <300 ms on RPi 5 CPU | ~80 ms with Hailo-8L accelerator |
| Bearing Accuracy | ±10–20° with 4-mic TDOA | Time-difference-of-arrival method |
| Training Data Needed | Yes — drone audio dataset required | Biggest challenge: data collection |

#### Layer 3 — Micro-Doppler Radar (50–500 m range)

The Acconeer XM125 is a 60 GHz pulsed coherent radar module. When a drone's rotors spin, they create a micro-Doppler signature — spreading the Doppler peak into a characteristic frequency fan. This works through walls, in rain, at night.

> **⚠️ Critical Correction to Original README**
>
> The README's Acconeer code uses: `Client.open(serial_port="/dev/spidev0.0")` — This is **WRONG**. The XM125 connects via UART serial (e.g. `/dev/ttyUSB0` or `/dev/ttyAMA0`), not SPI device files. The correct call is: `et.a121.Client.open(serial_port="/dev/ttyUSB0")`. Additionally, the XM125 requires the Exploration Server firmware (`acc_exploration_server_a121.bin`) to be flashed before Python SDK use.

> **⚠️ Range Correction — XM125 is Short-Range**
>
> The XM125 module has a maximum range of approximately 20 meters for human presence detection. The README's claim of 50–500 m detection range for drones is significantly overstated for the XM125. For 500 m drone detection, you would need a proper FMCW radar module (e.g., TI IWR6843, Infineon BGT60TR13C at $80–150) or a custom radar array. The micro-Doppler approach is still correct — only the sensor choice needs upgrading for longer range.

#### Layer 4 — Optical Confirmation (0–200 m)

OpenCV's MOG2 (Mixture of Gaussians v2) background subtractor learns the 'normal' sky, then highlights any moving foreground blob. Lucas-Kanade sparse optical flow then estimates the velocity vector of each blob. This is the final confirmation layer, not the primary detector.

| YOLO | ARTEMIS MOG2 + Optical Flow |
|------|-----------------------------|
| Requires GPU (not available on RPi) | Runs at 30 fps on RPi 5 CPU — no GPU |
| Needs training data for new drone types | Detects anything that moves, any drone type |
| Fails in rain, fog, darkness | Motion detection is light/weather independent |
| High latency: 200–500 ms on edge | Low latency: <33 ms (1 frame at 30 fps) |
| 50–100 m useful range | 30–200 m confirmation range |
| Can identify drone type | Cannot identify drone type (just motion) |

### 2.2 Fusion Engine

The fusion layer is the brain that turns raw sensor detections into confirmed tracked objects (threats). It uses three algorithms:

- **Extended Kalman Filter (EKF):** Maintains position and velocity estimates for each tracked object, accounting for sensor noise. Predicts future position between measurements.
- **Hungarian Algorithm:** Optimally assigns incoming sensor detections to existing tracks (or creates new tracks). Solves the assignment problem for multi-target, multi-sensor scenarios.
- **DBSCAN Clustering:** Detects coordinated swarm formations by finding spatial clusters among all active tracks. A swarm is flagged when 3+ drones are within proximity.

### 2.3 Cognition / AI Agent Layer

Four AI agents run in parallel after a track is confirmed:

| Agent | Input | Output | Latency Target |
|-------|-------|--------|---------------|
| Classifier Agent | Track signature (RF type, acoustic, radar spread) | Drone brand/type, threat tier (1–5) | <50 ms |
| Predictor Agent | Track history + EKF velocity vector | Projected route, impact point in 30 s | <20 ms |
| Scheduler Agent | All tracks + available effectors | Optimal effector-to-threat assignment | <10 ms |
| Spoof Agent | RF fingerprint + GPS position | GPS spoofing coordinates or protocol attack plan | <30 ms |

### 2.4 Mesh Network Architecture

Each node publishes sensor detections to a local MQTT broker (Mosquitto). The central hub subscribes to all nodes, aggregates detections, runs fusion, and publishes fused threats back to the mesh.

| MQTT Topic | Publisher | Subscriber | Update Rate |
|-----------|-----------|-----------|------------|
| `artemis/nodes/{id}/rf` | Each node | Hub aggregator | On detection |
| `artemis/nodes/{id}/acoustic` | Each node | Hub aggregator | Every 500 ms |
| `artemis/nodes/{id}/radar` | Each node | Hub aggregator | Every 50 ms |
| `artemis/nodes/{id}/optical` | Each node | Hub aggregator | Every 33 ms |
| `artemis/threats` | Hub | All nodes + Dashboard | On threat update |
| `artemis/commands/{id}` | Hub | Specific effector | On engagement decision |
| `artemis/nodes/{id}/status` | Each node | Hub + Dashboard | Every 1 second |

---

## 3. Corrections & Improvements to the Original README

This section documents all bugs, inaccuracies, and design improvements found during deep research.

### 3.1 Code Bug — RTL-SDR Listener (Critical)

> **🐛 Bug: RTL-SDR Stream Loop Only Runs Once Per Call**
>
> The README's `RTLSDRListener.stream()` method iterates through `FREQUENCIES` list and yields once per frequency, then exits. It should be a `while True:` outer loop to continuously scan. Without this, the stream generator terminates after one pass through the 3 frequencies.

**❌ Original (Broken):**

```python
async def stream(self):
    for freq in self.FREQUENCIES:          # Runs once, then generator ends
        self.sdr.center_freq = freq
        samples = await asyncio.to_thread(self.sdr.read_samples, self.FFT_SIZE)
        ...
        if peak_power > DETECTION_THRESHOLD:
            yield RFDetection(...)         # Only yields once per frequency
```

**✅ Fixed Version:**

```python
async def stream(self):
    while True:                            # Continuous scanning loop
        for freq in self.FREQUENCIES:
            self.sdr.center_freq = freq
            await asyncio.sleep(0.01)      # Allow frequency to settle
            samples = await asyncio.to_thread(
                self.sdr.read_samples, self.FFT_SIZE
            )
            power_spectrum = np.abs(np.fft.fft(samples)) ** 2
            peak_power = float(np.max(power_spectrum))
            if peak_power > DETECTION_THRESHOLD:
                yield RFDetection(
                    frequency=freq,
                    peak_power_db=10 * np.log10(peak_power + 1e-10),  # avoid log(0)
                    timestamp=asyncio.get_event_loop().time(),
                    source='rtlsdr'
                )
```

### 3.2 Hardware Bug — Acconeer XM125 Serial Port (Critical)

> **🐛 Bug: Wrong Serial Port Path for Acconeer XM125**
>
> The README uses `Client.open(serial_port="/dev/spidev0.0")` — SPI devices are kernel block devices, not serial ports. Acconeer's Python SDK communicates via UART serial (USB-to-UART bridge). The XM125 must be connected via its UART pins to a USB-UART adapter, appearing as `/dev/ttyUSB0` or `/dev/ttyACM0`.

**✅ Correct Acconeer XM125 Setup:**

```python
# Step 1: Flash exploration server firmware to XM125
# Download acc_exploration_server_a121.bin from developer.acconeer.com
# Flash using STM32CubeProgrammer via SWD interface

# Step 2: Connect XM125 UART to RPi via USB-UART adapter
# XM125 TX → USB-UART RX
# XM125 RX → USB-UART TX
# XM125 GND → USB-UART GND
# XM125 VDD → 3.3V

# Step 3: Correct Python code
import acconeer.exptool as et

class MicroDopplerProcessor:
    def __init__(self):
        # CORRECT — use serial port, not SPI device path
        self.client = et.a121.Client.open(serial_port='/dev/ttyUSB0')
        config = et.a121.SensorConfig(
            start_point=50, num_points=100,
            step_length=2,
            profile=et.a121.Profile.PROFILE_5
        )
        session_config = et.a121.SessionConfig(config)
        self.client.setup_session(session_config)  # Pass SessionConfig, not SensorConfig
```

### 3.3 Range Claim — Acconeer XM125 (Important Correction)

The README claims Layer 3 (radar) operates at 50–500 m range using the XM125. This is inaccurate.

| Sensor | Realistic Range | Cost | Notes |
|--------|----------------|------|-------|
| Acconeer XM125 (as-spec'd) | 0.5–20 m | $25–40 | Excellent for short-range confirmation only |
| TI IWR6843 FMCW Radar | Up to 300 m for drones | $60–120 | Recommended upgrade for Layer 3 |
| Infineon BGT60TR13C | Up to 100 m | $30–60 | Good mid-range option |
| Custom 24 GHz FMCW array | Up to 1 km | $200–500 | For serious deployment |

### 3.4 SessionConfig API Bug — Acconeer SDK

The README passes a `SensorConfig` directly to `client.setup_session()`. The Acconeer A121 Python SDK requires a `SessionConfig` wrapper object. Without this, the call raises a `TypeError` at runtime.

- ❌ Original: `client.setup_session(config)` where `config` is `SensorConfig`
- ✅ Fixed: `session_config = et.a121.SessionConfig(config); client.setup_session(session_config)`

### 3.5 Missing log(0) Guard — RF Detection

The README computes `10 * np.log10(peak_power)` without guarding against `peak_power = 0` (e.g., when no signal is present). This raises a `RuntimeWarning` and produces `-inf`.

**Fix:** use `peak_power + 1e-10` as the argument.

### 3.6 Missing asyncio.to_thread Wrapper — Acconeer

The Acconeer `client.get_next()` is a blocking synchronous call. The README's `async def stream()` calls it directly, which will block the asyncio event loop and freeze all other coroutines.

```python
# ❌ Blocks the event loop:
result = self.client.get_next()

# ✅ Correct — runs in a thread pool:
result = await asyncio.to_thread(self.client.get_next)
```

### 3.7 RF Range Expectation Management

> **ℹ️ Important: RF Detection Range Is Optimistic in Open Conditions Only**
>
> The 1–5 km RF detection range assumes line-of-sight, ideal antenna (directional Yagi or optimized dipole), and low RF noise environment. In urban environments with WiFi saturation on 2.4 GHz, realistic detection range for consumer drones is 200 m–1 km. Rural deployment can achieve 2–3 km with an RTL-SDR Blog V4 and a good omni antenna. The 5 km claim requires a high-gain directional antenna array and very low RF noise floor.

### 3.8 Acoustic Model Training — Not Included

The README references `models/acoustic_drone_cnn.tflite` as a pre-trained model, but this file does not exist in the repository. Users must train their own acoustic classifier. This is the single hardest non-code challenge in the project — collecting labeled drone audio in diverse conditions takes months of field work. See [Section 6](#6-acoustic-model-training-guide) for training guidance.

---

## 4. Full Technology Stack Analysis

| Technology | Layer | Why Used | Maturity | Risk |
|-----------|-------|---------|---------|------|
| Python 3.11 asyncio | All | Concurrent sensor reading without threads | Stable | Low |
| pyrtlsdr | RF | RTL-SDR USB dongle driver | Mature | Low |
| numpy FFT | RF | Fast power spectrum computation | Rock-solid | None |
| GNU Radio (optional) | RF | Advanced filtering/demodulation | Mature | Medium (complex) |
| sounddevice + scipy | Acoustic | STFT and mel spectrogram generation | Stable | Low |
| TensorFlow Lite | Acoustic/Optical | MobileNetV2 CNN on ARM | Stable | Low |
| acconeer.exptool | Radar | Acconeer XM125/XM112 Python SDK | Active dev | Medium |
| OpenCV MOG2 | Optical | Background subtraction (30 fps on RPi) | Mature | Low |
| Lucas-Kanade (OpenCV) | Optical | Sparse optical flow for velocity | Mature | Low |
| picamera2 | Optical | Pi Camera Module 3 driver | Active | Low |
| scipy EKF | Fusion | Extended Kalman Filter tracking | Stable | Medium |
| scikit-learn DBSCAN | Fusion | Swarm cluster detection | Stable | Low |
| paho-mqtt | Mesh | MQTT publish/subscribe client | Mature | Low |
| Mosquitto | Mesh | MQTT broker (runs on each node) | Rock-solid | None |
| FastAPI | API | Async REST + WebSocket server | Stable | Low |
| React + Three.js | Dashboard | 3D airspace visualization | Mature | Low |
| Mapbox GL JS | Dashboard | Geographic base map | Commercial API | Medium (cost) |
| Docker | Hub | Hub daemon containerization | Rock-solid | None |
| systemd | Node | Node daemon auto-restart on boot | Rock-solid | None |

### 4.1 Platform Requirements

| Requirement | Node (each RPi 5) | Hub (RPi 5 or PC) | Development Machine |
|------------|------------------|------------------|-------------------|
| OS | Raspberry Pi OS 64-bit (Bookworm) | Raspberry Pi OS / Ubuntu 22.04 | Any Linux/macOS/WSL2 |
| Python | 3.11+ | 3.11+ | 3.11+ |
| RAM | 8 GB (required for 4-sensor parallel) | 8 GB+ | 8 GB+ recommended |
| Storage | 32 GB microSD (minimum) | 64 GB+ SSD preferred | Any |
| Network | 100 Mbps LAN (PoE HAT+) | Gigabit preferred | Any |
| Docker | Not required | Required for hub daemon | Optional |
| Node.js | Not required | 14+ for dashboard build | 14+ recommended |

---

## 5. Step-by-Step Build Guide

### 5.1 Phase 0 — Simulation Mode (No Hardware — Start Here)

Start here before buying any hardware. The full simulation stack lets you develop and test the entire pipeline on any laptop.

#### Step 1: Environment Setup

```bash
# 1. Clone repository
git clone https://github.com/manu14357/Artemis.git
cd Artemis

# 2. Create Python virtual environment
python3.11 -m venv .venv
source .venv/bin/activate

# 3. Install all Python dependencies
pip install -r requirements.txt

# requirements.txt includes:
# pyrtlsdr numpy scipy scikit-learn opencv-python
# sounddevice tflite-runtime paho-mqtt fastapi uvicorn
# acconeer-exptool picamera2 asyncio aiofiles
```

#### Step 2: Run the Simulator

```bash
# Terminal 1: Start MQTT broker
mosquitto -c /etc/mosquitto/mosquitto.conf

# Terminal 2: Run drone swarm simulator
python sim/drone_swarm.py --scenario sim/scenarios/10_drone_swarm.yaml

# Terminal 3: Run hub fusion engine
python hub/main.py --config hub/config/hub_default.yaml

# Terminal 4: Build and serve dashboard
cd dashboard && npm install && npm run dev
# Open http://localhost:3000
```

### 5.2 Phase 1 — Single Node Hardware Setup (Raspberry Pi 5)

#### Step 1: Flash Raspberry Pi OS

```bash
# Use Raspberry Pi Imager
# Choose: Raspberry Pi OS (64-bit) Bookworm
# Enable SSH, set hostname: artemis-node-01
# Set WiFi or use Ethernet (PoE HAT recommended)

# After first boot, update system:
sudo apt update && sudo apt upgrade -y
```

#### Step 2: One-Command Node Setup Script

```bash
# Run the automated setup script:
curl -sSL https://raw.githubusercontent.com/manu14357/Artemis/main/scripts/setup_node.sh | bash

# The script installs:
# - Python 3.11 + pip + venv
# - RTL-SDR drivers: librtlsdr-dev rtl-sdr
# - GNU Radio: gnuradio python3-gnuradio
# - libcamera2 + picamera2
# - ALSA + PortAudio (for sounddevice)
# - Mosquitto MQTT broker
# - Acconeer exploration tool
# - ARTEMIS Python package
# - artemis-node.service systemd unit
```

#### Step 3: Sensor Wiring Guide

| Sensor | Interface | RPi Connection | Notes |
|--------|-----------|---------------|-------|
| RTL-SDR Blog V4 | USB | Any USB 3.0 port | Use USB extension for antenna positioning |
| ReSpeaker 4-Mic v2 | I2S/USB | USB port or I2S GPIO (pins 12,35,38,40) | USB version recommended for reliability |
| Acconeer XM125 | UART via USB | USB-UART adapter → any USB port | Flash exploration firmware first |
| Pi Camera Module 3 NoIR | CSI | Camera connector (CSI-2) | Use ribbon cable, enable in raspi-config |
| GPIO Relay Board | GPIO | GPIO 17,27,22,23 (pins 11,13,15,16) | Check relay board voltage — 3.3 V compatible? |
| PoE HAT+ | GPIO HAT | GPIO header (full) | Provides both power and network via PoE |

#### Step 4: Node Configuration

```yaml
# node/config/node_default.yaml
node:
  id: 'node-01'
  location:
    lat: 17.3850    # Your node's GPS coordinates
    lon: 78.4867
    alt_m: 540      # Altitude in meters

sensors:
  rf:
    enabled: true
    frequencies: [2437000000, 5780000000, 915000000]
    threshold_db: -50
  acoustic:
    enabled: true
    sample_rate: 16000
    channels: 4
    device_index: 0   # sounddevice device ID
  radar:
    enabled: true
    serial_port: /dev/ttyUSB0   # CORRECTED from original README
  optical:
    enabled: true
    resolution: [640, 480]
    fps: 30

mqtt:
  broker: 192.168.1.100   # Hub IP address
  port: 1883
  keepalive: 60
```

#### Step 5: Run Self-Test

```bash
# Test each sensor individually
python scripts/test_rf.py        # Should print: RTL-SDR OK, detected X signals
python scripts/test_acoustic.py  # Should print: Mic array OK, 4 channels active
python scripts/test_radar.py     # Should print: Acconeer XM125 OK, IQ frames streaming
python scripts/test_optical.py   # Should print: Camera OK, background model training...

# Run integrated node self-test
python node/main.py --test-mode --config node/config/node_default.yaml
```

#### Step 6: Start Node Daemon

```bash
sudo systemctl enable artemis-node
sudo systemctl start artemis-node
sudo journalctl -u artemis-node -f   # Follow logs
```

### 5.3 Phase 2 — Multi-Node Mesh Deployment

#### Network Topology

Deploy nodes at corners of the perimeter to be protected. Each node needs network connectivity to the hub (via Ethernet recommended, WiFi acceptable). The hub can be a more powerful machine — a mini PC or server is better for hub duty when running 6+ nodes.

| # Nodes | Area Coverage | Hardware Cost | Software Setup Time |
|---------|--------------|--------------|-------------------|
| 1 | ~0.3 km² (directional sensors) | $285 | 2–3 days |
| 3 | ~1 km² triangle formation | $855 | 1 week |
| 6 | ~2 km² hexagonal formation | $1,710 | 2 weeks |
| 12 | ~5 km² full area shield | $3,420 | 1 month |

```bash
# On the hub machine
python hub/main.py --config hub/config/hub_default.yaml
# Hub subscribes to artemis/nodes/+/# and aggregates all sensor streams
```

### 5.4 Phase 3 — Dashboard Setup

```bash
cd dashboard
npm install

# Configure dashboard connection to hub
# Edit src/config.ts:
# export const HUB_WS_URL = 'ws://192.168.1.100:8080/ws';
# export const HUB_REST_URL = 'http://192.168.1.100:8080';
# export const MAPBOX_TOKEN = 'your-mapbox-token-here';

# Development
npm run dev    # → http://localhost:3000

# Production build
npm run build  # Static files in dist/
# Serve with nginx or npm run preview
```

---

## 6. Acoustic Model Training Guide

The acoustic CNN is the component requiring the most original work. No pre-trained model ships with ARTEMIS v1. Here is how to build one.

### 6.1 Dataset Collection

You need two categories of labeled 500 ms audio clips recorded with your exact microphone setup:

| Class | Samples Needed | Collection Method | Diversity Required |
|-------|---------------|-----------------|-------------------|
| `drone_present` | 5,000+ clips | Record real drones at various ranges | Multiple drone models, altitudes, approach angles |
| `drone_absent` | 5,000+ clips | Record ambient noise without drones | Wind, traffic, birds, rain, silence |

### 6.2 Training Pipeline

```bash
# scripts/train_acoustic_model.py

# 1. Load audio files → compute mel spectrograms
# 2. Augment: add noise, pitch shift, time-stretch
# 3. Train MobileNetV2 on 128x128 mel spectrograms
# 4. Convert to TFLite for ARM deployment

# Run training:
python scripts/train_acoustic_model.py \
    --drone-clips data/drone/ \
    --ambient-clips data/ambient/ \
    --epochs 50 \
    --output models/acoustic_drone_cnn.tflite

# Expected accuracy (well-collected dataset): 90–96%
# Expected inference time on RPi 5: 180–280 ms
# Expected inference time with Hailo-8L: 20–40 ms
```

### 6.3 Available Public Datasets

- [DroneAudioDataset](https://github.com/gumberss/DroneAudioDataset) — 4 drone types + ambient recordings
- [ESC-50](https://github.com/karolpiczak/ESC-50) — Environmental Sound Classification (for ambient class augmentation)
- DCASE 2023 — Drone detection challenge dataset (limited, but labeled)
- Custom recording — Always best to record with your exact hardware setup

---

## 7. Performance Targets & Real-World Expectations

| Stage | Target | Realistic Expectation | Notes |
|-------|--------|----------------------|-------|
| RF detection (first alert) | <100 ms from signal | 50–150 ms | Achievable with tuned FFT |
| Acoustic classification | <300 ms | 200–400 ms | Depends on TFLite model size |
| Radar detection | <50 ms | 50–100 ms (with fix) | After correct UART setup |
| Optical detection | <33 ms | 33–66 ms | Depends on camera resolution |
| Fusion (track confirmed) | <200 ms total | 150–400 ms | Very achievable |
| Decision (threat → command) | <10 ms | 5–30 ms | Easily achievable in Python |
| End-to-end: detect → command | <500 ms from RF signal | 300 ms–1.5 s | Pipeline latency varies |
| RF detection range | 1–5 km | 200 m–2 km realistic | Depends heavily on antenna + RF noise |
| Radar range (XM125) | 50–500 m (claimed) | 0.5–20 m (actual) | Needs sensor upgrade for longer range |
| Acoustic range | 100–500 m | 50–300 m typical | Environment-dependent |

### 7.1 CPU Load Per Node (Raspberry Pi 5)

| Process | CPU Usage (approx) | RAM Usage |
|---------|-------------------|---------|
| RF FFT scanning (pyrtlsdr) | 8–15 % | 50 MB |
| Acoustic STFT + TFLite inference | 25–40 % | 150 MB |
| Radar data processing | 5–10 % | 30 MB |
| Optical flow (640×480 @ 30 fps) | 20–35 % | 80 MB |
| Fusion + Kalman filter | 5–10 % | 40 MB |
| MQTT + FastAPI | 3–5 % | 30 MB |
| **Total (all layers active)** | **65–115 % (1 core)** | **380 MB** |
| With Hailo-8L accelerator | 40–70 % (acoustic offloaded) | 350 MB |

> Raspberry Pi 5 has a 4-core ARM Cortex-A76. The above figures are per-core estimates. With proper asyncio concurrency, actual wall-clock CPU usage distributes across cores and typically stays below 80 % total.

---

## 8. Legal Framework

> **⚠️ IMPORTANT LEGAL NOTICE — Read Before Deploying**
>
> This section summarizes legal constraints. You are responsible for legal compliance in your jurisdiction. This is not legal advice.

| Component | India | USA | EU | Notes |
|-----------|-------|-----|----|-------|
| RF Listening (passive) | Legal | Legal | Legal | Receiving is legal; transmitting is not |
| Acoustic Monitoring | Legal | Legal | Legal (privacy laws apply) | Outdoor airspace monitoring OK |
| Camera Monitoring (outdoor) | Legal | Legal | Legal (GDPR may apply) | Don't capture private property |
| Radar Detection | Legal | Legal | Legal | Passive detection only |
| **RF Jamming** | **ILLEGAL** | **ILLEGAL (FCC Part 97)** | **ILLEGAL** | Serious criminal offense |
| **GPS Spoofing** | **ILLEGAL** | **ILLEGAL (18 U.S.C. § 32)** | **ILLEGAL** | Major criminal offense globally |
| Counter-drone interception | Requires MHA authorization | Requires FAA/DoD authorization | Requires national authority auth | Effector modules simulation-only by default |

### 8.1 India-Specific (Hyderabad / Telangana)

- Passive RF monitoring (receive-only) is legal under the Indian Telegraph Act.
- Active RF transmission requires a license from the Wireless Planning and Coordination Wing (WPC).
- RF jamming is a criminal offense under Section 6 of the Indian Wireless Telegraphy Act, 1933.
- Drone detection systems for research purposes are permitted under DRDO/CSIR lab frameworks.
- For civil deployment at critical infrastructure, coordination with DGCA and MHA is required.

### 8.2 Safe Implementation Strategy

- Run all effectors in simulation-only mode (default) during development and testing.
- Label your ARTEMIS nodes clearly as research equipment.
- Keep all RF jammer and GPS spoofer code behind a `--enable-effectors` flag requiring explicit authorization.
- Log all detections with timestamps for audit and research purposes.

---

## 9. Complete Repository Structure

```
Artemis/
├── README.md
├── LICENSE
├── requirements.txt
├── .gitignore
│
├── artemis/                          # Core Python package
│   ├── core/
│   │   ├── config.py                 # YAML config loader
│   │   ├── bus.py                    # asyncio event bus
│   │   ├── types.py                  # Shared dataclasses
│   │   └── logging.py
│   │
│   ├── perception/                   # Raw sensor drivers
│   │   ├── rf/
│   │   │   ├── rtlsdr_listener.py    # FIXED: continuous while True loop
│   │   │   ├── spectrum_scanner.py
│   │   │   └── fingerprinter.py
│   │   ├── acoustic/
│   │   │   ├── mic_reader.py
│   │   │   ├── stft_processor.py
│   │   │   ├── drone_classifier.py
│   │   │   └── bearing_estimator.py
│   │   ├── radar/
│   │   │   ├── acconeer_reader.py    # FIXED: /dev/ttyUSB0 serial port
│   │   │   ├── doppler_processor.py  # FIXED: asyncio.to_thread wrapper
│   │   │   └── signature_matcher.py
│   │   └── optical/
│   │       ├── camera_reader.py
│   │       ├── background_sub.py
│   │       ├── optical_flow.py
│   │       └── classifier.py
│   │
│   ├── fusion/
│   │   ├── kalman.py                 # Extended Kalman Filter
│   │   ├── track_manager.py
│   │   ├── correlator.py             # Hungarian algorithm
│   │   ├── swarm_analyzer.py         # DBSCAN swarm detection
│   │   └── threat_map.py
│   │
│   ├── cognition/
│   │   ├── agents/
│   │   │   ├── base_agent.py
│   │   │   ├── classifier_agent.py
│   │   │   ├── predictor_agent.py
│   │   │   ├── scheduler_agent.py
│   │   │   └── spoof_agent.py        # Simulation only by default
│   │   ├── orchestrator.py
│   │   └── decision_engine.py
│   │
│   ├── action/
│   │   ├── effectors/
│   │   │   ├── base_effector.py
│   │   │   ├── gpio_relay.py
│   │   │   ├── rf_jammer.py          # SIMULATION ONLY — illegal to activate
│   │   │   ├── gps_spoofer.py        # SIMULATION ONLY — illegal to activate
│   │   │   └── counter_drone.py
│   │   ├── registry.py
│   │   └── planner.py
│   │
│   ├── mesh/
│   │   ├── publisher.py
│   │   ├── subscriber.py
│   │   ├── aggregator.py
│   │   └── triangulator.py
│   │
│   └── api/
│       ├── rest.py                   # FastAPI REST
│       └── websocket.py              # WebSocket feed
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
├── dashboard/                        # React + Three.js + Mapbox
│   ├── src/
│   │   ├── components/
│   │   │   ├── ThreatMap.tsx         # 3D airspace (Three.js/Mapbox)
│   │   │   ├── NodeStatus.tsx
│   │   │   ├── DetectionFeed.tsx
│   │   │   └── EffectorPanel.tsx
│   │   └── App.tsx
│   └── package.json
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
├── models/
│   ├── acoustic_drone_cnn.tflite     # MUST BE TRAINED — not pre-supplied
│   ├── acoustic_drone_cnn.onnx
│   └── README_models.md
│
├── scripts/
│   ├── setup_node.sh
│   ├── train_acoustic_model.py
│   ├── test_rf.py
│   ├── test_acoustic.py
│   ├── test_radar.py
│   ├── test_optical.py
│   └── benchmark.py
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── load/swarm_1000.py
│
├── infra/
│   ├── docker-compose.yml
│   └── k8s/
│
└── docs/
    └── FULL_DOCUMENTATION.md        # This file
```

---

## 10. Corrected Development Roadmap

| Phase | Duration | Deliverables | Prerequisites |
|-------|----------|-------------|--------------|
| **Phase 0** — Simulation | Month 1 | Full sim stack + dashboard on any laptop | Python 3.11, Node.js 18 |
| **Phase 1** — Single Node | Months 2–3 | RF + Acoustic + Optical on live RPi | Hardware ($285) + trained acoustic model |
| **Phase 2** — Radar + Mesh | Months 4–6 | Radar integration + 2-node MQTT mesh + triangulation | XM125 with corrected firmware; 2 nodes |
| **Phase 3** — Decision + Effectors | Months 7–9 | AI agent network + GPIO relay (sim effectors) | Phase 1+2 complete |
| **Phase 4** — Area Shield | Months 10–12 | 6-node production perimeter deployment | Test range + institutional support |

### 10.1 Key Success Factors

- **Acoustic model quality is everything:** Invest heavily in dataset collection. 5,000+ diverse audio clips per class. Field-recorded with your exact hardware.
- **RF threshold tuning:** Your detection threshold will be environment-specific. Too low = constant false positives from WiFi. Too high = missed detections. Tune on-site.
- **Network reliability:** Use PoE Ethernet (not WiFi) for node-to-hub links. MQTT over WiFi in dense environments loses packets.
- **Radar sensor upgrade:** Replace XM125 with TI IWR6843 for 300 m detection range. The XM125 is great for confirmation but not long-range detection.
- **Legal authorization first:** For any deployment beyond personal research, obtain written clearance from the relevant authority (DGCA for India).

### 10.2 Final Verdict

> **✅ BUILD IT — Recommended Approach**
>
> ARTEMIS v1 is one of the most ambitious, well-designed open-source defense-tech projects published. The architecture is sound, the technology choices are correct, and the simulation-first approach is exactly right. The bugs found (Acconeer serial port, RTL-SDR loop, SessionConfig API, log(0) guard) are all fixable in minutes. The XM125 range limitation requires a sensor upgrade but doesn't invalidate the design. Start with Phase 0 simulation today — no hardware needed. The acoustic model training is your biggest investment and should start in parallel with hardware procurement.

---

*ARTEMIS v1 — Full Technical Documentation | Version 1.0.0 | May 2026*  
*Repository: [github.com/manu14357/Artemis](https://github.com/manu14357/Artemis)*
