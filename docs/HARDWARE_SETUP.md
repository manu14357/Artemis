# ARTEMIS Hardware Setup Guide

Complete step-by-step instructions for assembling, wiring, and commissioning
one ARTEMIS sensor node (Raspberry Pi 5 + 4 sensors) and connecting it to
the hub.

---

## Table of Contents

1. [Bill of Materials](#1-bill-of-materials)
2. [Raspberry Pi 5 — First Boot](#2-raspberry-pi-5--first-boot)
3. [Sensor 1 — RTL-SDR Blog V4 (RF)](#3-sensor-1--rtl-sdr-blog-v4-rf)
4. [Sensor 2 — ReSpeaker 4-Mic Array (Acoustic)](#4-sensor-2--respeaker-4-mic-array-acoustic)
5. [Sensor 3 — Acconeer XM125 (Radar)](#5-sensor-3--acconeer-xm125-radar)
6. [Sensor 4 — Pi Camera Module 3 NoIR (Optical)](#6-sensor-4--pi-camera-module-3-noir-optical)
7. [Optional — GPIO Relay Board (Effectors)](#7-optional--gpio-relay-board-effectors)
8. [Full Wiring Diagram](#8-full-wiring-diagram)
9. [Power Requirements](#9-power-requirements)
10. [Software Installation](#10-software-installation)
11. [Testing Each Sensor](#11-testing-each-sensor)
12. [Configuring the Node](#12-configuring-the-node)
13. [Connecting to the Hub](#13-connecting-to-the-hub)
14. [Deploying the Node Daemon (systemd)](#14-deploying-the-node-daemon-systemd)
15. [Troubleshooting](#15-troubleshooting)

---

## 1. Bill of Materials

### Per Node (~$285)

| # | Component | Exact Model | Where to Buy | Cost |
|---|-----------|-------------|-------------|------|
| 1 | SBC | Raspberry Pi 5 (8 GB) | raspberrypi.com / Adafruit | $80 |
| 2 | RF dongle | RTL-SDR Blog V4 (with dipole antenna kit) | rtl-sdr.com | $35 |
| 3 | Microphone array | ReSpeaker 4-Mic Array for Raspberry Pi v2 (USB) | Seeed Studio | $40 |
| 4 | Radar | Acconeer XM125 Pulsed Coherent Radar | acconeer.com / Digikey | $30 |
| 5 | USB-UART adapter | CP2102 USB-to-Serial (for XM125) | Amazon / AliExpress | $5 |
| 6 | Camera | Raspberry Pi Camera Module 3 NoIR (wide) | raspberrypi.com | $35 |
| 7 | Power | Raspberry Pi PoE+ HAT | raspberrypi.com | $30 |
| 8 | Storage | 64 GB microSD A2-rated (Samsung Pro Endurance) | Amazon | $15 |
| 9 | Enclosure | IP65 weatherproof ABS box (≥200×150×75 mm) | Amazon | $15 |
| 10 | Misc | USB hub (4-port), jumper wires, M2.5 standoffs | Amazon | ~$5 |
| | **Total** | | | **~$290** |

### Hub Machine (runs once, shared by all nodes)

Any machine on the same LAN — a spare Raspberry Pi 4/5, laptop, or server.
Docker is the easiest way to run the hub.

| Component | Minimum Spec |
|-----------|-------------|
| CPU | 2-core ARMv8 or x86-64 |
| RAM | 2 GB |
| Storage | 20 GB |
| Network | Ethernet recommended |

---

## 2. Raspberry Pi 5 — First Boot

### 2a. Flash the SD Card

1. Download [Raspberry Pi Imager](https://www.raspberrypi.com/software/).
2. Select:
   - **Device:** Raspberry Pi 5
   - **OS:** Raspberry Pi OS (64-bit) — full or Lite both work
   - **Storage:** your microSD card
3. Click the gear icon (⚙) and configure:
   - Hostname: `artemis-node-01`
   - Enable SSH (use password or your public key)
   - Set username: `pi`, password: something strong
   - Set your WiFi SSID/password (or use Ethernet)
4. Flash and insert the card into the Pi.

### 2b. First Login

```bash
ssh pi@artemis-node-01.local
```

Run the mandatory first-boot updates:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git vim
```

### 2c. Enable the Camera Interface

```bash
sudo raspi-config
# Navigate: Interface Options → Camera → Enable
# Reboot when prompted
```

Or directly edit `/boot/firmware/config.txt` (Pi OS Bookworm):

```ini
# Add/uncomment these lines:
camera_auto_detect=1
```

### 2d. Expand the Filesystem (if not done automatically)

```bash
sudo raspi-config
# Advanced Options → Expand Filesystem
sudo reboot
```

---

## 3. Sensor 1 — RTL-SDR Blog V4 (RF)

### What It Does

Passively scans 2.4 GHz (Wi-Fi/DJI control link), 5.8 GHz (video downlink),
and 900 MHz (FPV long-range) for energy peaks characteristic of drone RF
transmissions. Detection range: 200 m – 3 km depending on antenna and terrain.

### Physical Connection

```
RTL-SDR Blog V4 dongle
        │
        │  USB 3.0 cable (A to A or A to micro-B)
        │
  ┌─────▼──────────────────┐
  │  Raspberry Pi 5        │
  │  USB 3.0 Port (blue)   │  ← use the BLUE USB port (USB 3.0) for best throughput
  └────────────────────────┘
```

Use the **short 30 cm USB extension cable** included in the RTL-SDR kit.
Do **not** plug the dongle directly into the Pi — it generates heat that
degrades ADC performance.

### Antenna Placement

- Use the included **dipole antenna kit** (silver telescopic antennas).
- Adjust both dipoles to quarter-wave length for each band:

| Band | Quarter-wave length | Dipole setting |
|------|--------------------|-|
| 2.4 GHz | 31 mm | Collapse to shortest |
| 5.8 GHz | 13 mm | Collapse fully, extend 13 mm |
| 900 MHz | 83 mm | Extend to ~83 mm |

- Mount the antenna **outside** the enclosure — RF does not penetrate metal.
- Elevate the antenna above ground obstructions for best range.

### Driver Setup (included in `setup_node.sh`)

```bash
# Blacklist the default DVB-T driver (conflicts with rtlsdr)
echo "blacklist dvb_usb_rtl28xxu" | sudo tee /etc/modprobe.d/rtlsdr.conf
sudo rmmod dvb_usb_rtl28xxu 2>/dev/null || true

# Test the dongle
rtl_test -t
# Expected: "Found 1 device(s)... No E4000 tuner found, device is not an E4000"
# (V4 uses Rafael Micro R820T2, so "no E4000" is correct)
```

### Verify in Python

```bash
python - <<'EOF'
from rtlsdr import RtlSdr
sdr = RtlSdr()
print(f"Gains: {sdr.valid_gains_db}")
sdr.close()
print("RTL-SDR OK")
EOF
```

---

## 4. Sensor 2 — ReSpeaker 4-Mic Array (Acoustic)

### What It Does

Captures 4-channel audio at 16 kHz, runs a mel-spectrogram through a
MobileNetV2 TFLite model to classify drone vs. background noise, and
estimates drone bearing using GCC-PHAT TDOA across the four microphones.
Detection range: 50 – 300 m in quiet outdoor environments.

### Which Version to Buy

Buy the **USB version** (ReSpeaker 4-Mic Array for Raspberry Pi v2 — USB).
The I2S HAT version requires kernel driver compilation; the USB version
works out-of-the-box with ALSA.

### Physical Connection

```
ReSpeaker 4-Mic Array (USB)
        │
        │  USB cable (included)
        │
  ┌─────▼──────────────────┐
  │  Raspberry Pi 5        │
  │  USB 2.0 Port (black)  │  ← any USB 2.0 port is fine for audio
  └────────────────────────┘
```

Mount the microphone array **horizontally**, facing skyward, on the top of
your enclosure for omnidirectional coverage. Avoid mounting inside a closed
enclosure (muffles high frequencies).

### Find the Device Index

```bash
python -m sounddevice
# Look for "ReSpeaker 4 Mic Array" in the output
# Note the device index number — typically 1 or 2
```

Set `device_index` in `node/config/node_default.yaml` to match.

### Check 4-Channel Recording

```bash
arecord -D hw:CARD=ArrayUAC10,DEV=0 -c 4 -r 16000 -f S16_LE -d 3 /tmp/test.wav
aplay /tmp/test.wav   # Should play back 3 seconds of ambient audio
```

### Acoustic Model

The TFLite model (`models/acoustic_drone_cnn.tflite`) is **not included** —
you must train it with your own data. See
[Training the Acoustic Model](#acoustic-model-training) in the main README,
or train via:

```bash
python scripts/train_acoustic_model.py \
    --drone-clips data/drone/ \
    --ambient-clips data/ambient/ \
    --output models/acoustic_drone_cnn.tflite
```

Place the trained `.tflite` file at the path specified in `model_path` in
the node config.

---

## 5. Sensor 3 — Acconeer XM125 (Radar)

### What It Does

Pulsed coherent radar operating at 60 GHz. Detects presence and measures
micro-Doppler spread (rotor blade rotation frequency) to confirm a drone
at 0.3 – 20 m range. Acts as a final-confirmation layer for targets already
tracked by RF and/or acoustic.

### What You Need

- Acconeer XM125 module (EVK or bare module)
- CP2102 USB-to-UART breakout board (3.3 V logic level)
- 4× jumper wires (female-female)

### Step 1 — Flash Exploration Server Firmware

The XM125 must run Acconeer's **Exploration Server** firmware to accept
commands from `acconeer-exptool`.

1. Download [Acconeer SDK](https://developer.acconeer.com/software/).
2. Flash `acc_exploration_server_xm125.bin` using the J-Link or STM32CubeProgrammer:

```bash
# Using STM32CubeProgrammer CLI:
STM32_Programmer_CLI -c port=SWD -w acc_exploration_server_xm125.bin 0x08000000 -rst
```

Alternatively, use the [XM125 Firmware Update Tool](https://developer.acconeer.com/software/)
in the Acconeer Exploration Tool GUI on Windows.

### Step 2 — Wire XM125 to CP2102 Adapter

| XM125 Pin | CP2102 Pin | Wire Color (suggestion) |
|-----------|-----------|------------------------|
| GND | GND | Black |
| VCC (3.3V) | 3.3V OUT | Red |
| TX (UART out) | RXD | Green |
| RX (UART in) | TXD | Yellow |

> **Important:** The XM125 is **3.3 V logic**. Never connect it to a 5 V UART adapter.
> The CP2102 has a 3.3 V header pin — use that, not the 5 V rail.

### Step 3 — Wire CP2102 to Raspberry Pi

```
XM125 module
    │
    │  4× jumper wires (GND / 3.3V / TX / RX)
    │
  CP2102 USB-UART adapter
        │
        │  USB cable
        │
  ┌─────▼──────────────────┐
  │  Raspberry Pi 5        │
  │  USB 2.0 Port          │
  └────────────────────────┘

# The adapter appears as /dev/ttyUSB0 (check with: ls /dev/ttyUSB*)
```

### Step 4 — Set Serial Port Permissions

```bash
sudo usermod -aG dialout pi
# Log out and back in, then:
ls -l /dev/ttyUSB0   # Should show rw-rw---- (group dialout)
```

### Step 5 — Verify with acconeer-exptool

```bash
pip install acconeer-exptool
python -c "
import acconeer.exptool as et
client = et.UARTClient(serial_port='/dev/ttyUSB0')
client.connect()
print('XM125 connected, protocol version:', client.server_info)
client.disconnect()
"
```

### Node Config

```yaml
radar:
  serial_port: /dev/ttyUSB0   # adjust if your adapter appears as ttyUSB1 or ttyACM0
  start_point: 50
  num_points: 100
  step_length: 2
  profile: PROFILE_5
```

---

## 6. Sensor 4 — Pi Camera Module 3 NoIR (Optical)

### What It Does

Captures video at 640×480 @ 30 fps. OpenCV MOG2 background subtraction
isolates moving objects; Lucas-Kanade optical flow estimates velocity.
Range pinhole model estimates distance. Detection range: 5 – 200 m
(NoIR filter allows night use with IR illumination).

### Physical Connection

```
Pi Camera Module 3 NoIR
        │
        │  15-pin to 22-pin FFC ribbon cable (included)
        │  (15-pin end → camera; 22-pin end → Pi 5 connector)
        │
  ┌─────▼──────────────────────────────┐
  │  Raspberry Pi 5                    │
  │  CAM0 connector (left of USB ports)│  ← lift the tab, insert ribbon, press tab down
  └────────────────────────────────────┘
```

**Note:** The Pi 5 uses a **22-pin** (0.5 mm pitch) camera connector, not the
15-pin connector on Pi 4. The Camera Module 3 ships with an adapter cable.
If you do not have the correct cable, order "Pi 5 camera cable" (200 mm length
recommended for enclosure routing).

### Verify Camera Works

```bash
libcamera-hello --timeout 2000   # Should open a preview window for 2 seconds
libcamera-still -o /tmp/test.jpg  # Capture a test image
```

### Check in Python (PiCamera2)

```bash
python - <<'EOF'
from picamera2 import Picamera2
cam = Picamera2()
cam.configure(cam.create_video_configuration(main={"size": (640, 480)}))
cam.start()
import time; time.sleep(1)
frame = cam.capture_array()
print(f"Frame shape: {frame.shape}")  # Expected: (480, 640, 3)
cam.stop()
EOF
```

### Pointing and Mounting

- Mount at 45° downward tilt on a pole or mast for sky coverage.
- Avoid pointing directly at the sun (even with NoIR filter, overexposure degrades MOG2).
- For night use: pair with an 850 nm IR LED array (12 V, 5 W) aimed upward.

---

## 7. Optional — GPIO Relay Board (Effectors)

> **Warning:** All physical effectors are **disabled by default** and legal
> authorization is required before enabling them. See `docs/LEGAL.md`.

### What It Does

The GPIO relay board controls external hardware (sirens, lights, physical
barriers). RF jammers and GPS spoofers are **simulation-only** and cannot
be enabled through this GPIO relay.

### Wiring

```
  Raspberry Pi 5 GPIO Header (40-pin)
  ┌─────────────────────────────────┐
  │ Pin 1  (3.3V)  ──► Relay VCC   │
  │ Pin 6  (GND)   ──► Relay GND   │
  │ Pin 11 (GPIO17)──► Relay IN1   │
  │ Pin 13 (GPIO27)──► Relay IN2   │
  │ Pin 15 (GPIO22)──► Relay IN3   │
  │ Pin 16 (GPIO23)──► Relay IN4   │
  └─────────────────────────────────┘
```

> Use a **3.3 V relay module** (not 5 V) — the Pi 5 GPIO is 3.3 V.
> For 5 V relay boards, add a level-shifter (e.g. BSS138 MOSFET breakout).

### Enable in Config

```yaml
# node/config/node_default.yaml
effectors:
  gpio_relay:
    enabled: true   # Only set true if you have legal authorization
    pins: [17, 27, 22, 23]
```

---

## 8. Full Wiring Diagram

```
                    ╔═══════════════════════════════════════════════╗
                    ║          ARTEMIS SENSOR NODE                  ║
                    ║         Raspberry Pi 5 (8 GB)                 ║
                    ╠═══════════════════════════════════════════════╣
                    ║                                               ║
  RTL-SDR Blog V4 ──╫──► USB 3.0 (blue)                           ║
  (2.4/5.8/900 MHz) ║                                               ║
  dipole antenna    ║                                               ║
                    ║                                               ║
  ReSpeaker 4-Mic ──╫──► USB 2.0 (black, port 1)                  ║
  Array (USB)       ║                                               ║
  skyward mount     ║                                               ║
                    ║                                               ║
  CP2102 UART ──────╫──► USB 2.0 (black, port 2)                  ║
  adapter           ║                                               ║
      │             ║                                               ║
      └── XM125 ──► ║  (3.3V / GND / TX / RX jumper wires)        ║
  60 GHz radar      ║                                               ║
                    ║                                               ║
  Camera Module 3 ──╫──► CAM0 (22-pin FFC ribbon)                 ║
  NoIR              ║                                               ║
                    ║                                               ║
  4-ch Relay Board──╫──► GPIO 17/27/22/23 + 3.3V + GND            ║
  (optional)        ║                                               ║
                    ║                                               ║
  PoE+ HAT ─────────╫──► 40-pin GPIO header (powers RPi via PoE)  ║
                    ║                                               ║
  Ethernet ─────────╫──► Gigabit Ethernet port ──► Switch ──► HUB ║
                    ╚═══════════════════════════════════════════════╝

USB summary:
  USB 3.0 (blue)  [port 1]: RTL-SDR Blog V4
  USB 2.0 (black) [port 2]: ReSpeaker 4-Mic Array
  USB 2.0 (black) [port 3]: CP2102 (XM125 radar)
  USB 2.0 (black) [port 4]: spare / USB hub if needed
```

---

## 9. Power Requirements

| Component | Current (typical) | Peak |
|-----------|------------------|------|
| Raspberry Pi 5 (8 GB) | 2.5 A @ 5V | 5 A @ 5V |
| RTL-SDR Blog V4 | 0.3 A | 0.5 A |
| ReSpeaker 4-Mic | 0.15 A | 0.25 A |
| XM125 (via CP2102) | 0.1 A | 0.2 A |
| Pi Camera Module 3 | 0.1 A | 0.2 A |
| Relay board (4ch) | 0.1 A | 0.4 A |
| **Total node** | **~3.25 A @ 5V (16.25 W)** | **~6.5 A (32.5 W)** |

### Power Options

| Option | Notes |
|--------|-------|
| **PoE+ HAT** (recommended) | Single Ethernet cable delivers power + data. Requires 802.3at PoE+ switch port (25.5 W). |
| Official 27 W USB-C PSU | Use only in weatherproof enclosure with conduit entry. |
| 12 V battery + 12V→5V 5A DC-DC | For off-grid / remote deployments. |

---

## 10. Software Installation

### Automated (recommended)

```bash
# On the Raspberry Pi, after cloning the repository:
cd /opt/artemis
sudo bash scripts/setup_node.sh
```

The script installs all system packages, Python dependencies, configures
Mosquitto, and registers the systemd service.

### Manual Step-by-Step

```bash
# 1. System packages
sudo apt update && sudo apt install -y \
  git python3.11 python3.11-venv python3.11-dev \
  librtlsdr-dev rtl-sdr \
  portaudio19-dev libportaudio2 alsa-utils \
  python3-picamera2 libcamera-apps \
  mosquitto mosquitto-clients \
  cmake build-essential

# 2. Blacklist DVB-T driver (conflicts with RTL-SDR)
echo "blacklist dvb_usb_rtl28xxu" | sudo tee /etc/modprobe.d/rtlsdr.conf

# 3. Python virtual environment
python3.11 -m venv /opt/artemis/.venv
source /opt/artemis/.venv/bin/activate
pip install -r requirements.txt

# 4. acconeer-exptool (XM125 radar SDK)
pip install acconeer-exptool>=7.0.0

# 5. Mosquitto (local broker — only needed if this node also runs a broker)
sudo systemctl enable mosquitto
sudo systemctl start mosquitto
```

---

## 11. Testing Each Sensor

Run these tests **before** starting the full node daemon. Each test confirms
the driver can open hardware and receive data.

```bash
cd /opt/artemis
source .venv/bin/activate

# RF — expects: "RTL-SDR OK, detected X signals"
python scripts/test_rf.py

# Acoustic — expects: "Mic array OK, 4 channels active"
python scripts/test_acoustic.py

# Radar — expects: "XM125 OK, IQ frames streaming"
python scripts/test_radar.py

# Optical — expects: "Camera OK, background model training..."
python scripts/test_optical.py

# Full integrated smoke test (10-second run, then exits cleanly)
python node/main.py --test-mode --config node/config/node_default.yaml
```

Expected output from the integrated test:

```
INFO  [node.main] Loaded config: node-01 @ 17.3850, 78.4867
INFO  [node.main] Starting drivers: rf, acoustic, radar, optical
INFO  [perception.rf] RTLSDRListener started on [2437000000, 5780000000, 915000000]
INFO  [perception.acoustic] AcousticClassifier started, device=0, channels=4
INFO  [perception.radar] XM125Processor connected on /dev/ttyUSB0
INFO  [perception.optical] OpticalDetector started (PiCamera2) 640x480@30fps
INFO  [node.main] Test mode — running for 10 s then exiting
INFO  [node.main] Shutdown complete
```

---

## 12. Configuring the Node

Edit `node/config/node_default.yaml` before starting the daemon:

```yaml
node:
  id: 'node-01'          # Unique ID — change for each node (node-01, node-02, …)
  location:
    lat: 17.3850          # GPS latitude of this node's physical position
    lon: 78.4867          # GPS longitude
    alt_m: 540            # Altitude in metres above sea level

sensors:
  rf:
    enabled: true
    frequencies:
      - 2437000000        # 2.4 GHz — DJI/consumer drone control links
      - 5780000000        # 5.8 GHz — video downlinks
      - 915000000         # 900 MHz — FPV long-range
    fft_size: 1024
    threshold_db: -50     # Raise to -40 in high-RF-noise environments

  acoustic:
    enabled: true
    device_index: 1       # Get this from: python -m sounddevice
    channels: 4
    sample_rate: 16000
    window_ms: 500
    model_path: models/acoustic_drone_cnn.tflite
    confidence_threshold: 0.75

  radar:
    enabled: true
    serial_port: /dev/ttyUSB0   # Check: ls /dev/ttyUSB*
    start_point: 50
    num_points: 100
    step_length: 2
    profile: PROFILE_5

  optical:
    enabled: true
    resolution: [640, 480]
    fps: 30
    mog2_learning_rate: 0.005
    min_blob_area: 80

mqtt:
  broker: 192.168.1.100   # IP address of your hub machine — CHANGE THIS
  port: 1883

logging:
  level: INFO
  file: logs/artemis-node.log
```

To find your hub machine's IP:

```bash
# On the hub machine:
hostname -I | awk '{print $1}'
```

---

## 13. Connecting to the Hub

### Hub Machine Setup

Run the hub on any machine on the same network. The easiest path is Docker
Compose:

```bash
# On the hub machine — clone the repo and start services
git clone https://github.com/your-org/artemis.git
cd artemis
docker compose -f infra/docker-compose.yml up -d

# Services started:
#   artemis-mosquitto  :1883 (MQTT), :9001 (WebSocket)
#   artemis-hub        :8080 (REST API + WebSocket)
#   artemis-dashboard  :3000 (Browser UI)
```

Or run the hub Python process directly:

```bash
source .venv/bin/activate
python hub/main.py --config hub/config/hub_default.yaml
```

### Verify Node → Hub Connection

```bash
# On the hub machine — subscribe to all node topics:
mosquitto_sub -h localhost -t "artemis/nodes/#" -v

# On the node — start the daemon:
sudo systemctl start artemis-node

# Within a few seconds you should see MQTT messages like:
# artemis/nodes/node-01/rf   {"threat_id": "...", "frequency_hz": 2437000000, ...}
# artemis/nodes/node-01/status  {"node_id": "node-01", "online": true, ...}
```

### Dashboard

Open `http://<hub-ip>:3000` in your browser. You should see:

- **● LIVE** in the top-right (WebSocket connected)
- Node-01 appearing in the **Sensor Nodes** panel
- Detections appearing in **Detection Feed** when a drone is in range
- Drone spheres appearing in the **3D Threat Map**

---

## 14. Deploying the Node Daemon (systemd)

After confirming the node works correctly, register it as a system service so
it starts automatically on boot:

```bash
# Copy the unit file
sudo cp node/systemd/artemis-node.service /etc/systemd/system/

# Reload systemd and enable the service
sudo systemctl daemon-reload
sudo systemctl enable artemis-node
sudo systemctl start artemis-node

# Check status
sudo systemctl status artemis-node

# Follow live logs
sudo journalctl -u artemis-node -f
```

The service is configured with `Restart=always` and `RestartSec=5` — it
will automatically restart if any driver crashes.

---

## 15. Troubleshooting

### RTL-SDR — "No RTL-SDR devices found"

```bash
# Check USB device is detected by the kernel
lsusb | grep RTL

# Reload the driver (don't use sudo for pyrtlsdr)
sudo rmmod dvb_usb_rtl28xxu rtl2832 rtl2830 2>/dev/null || true
rtl_test -t   # Should print "Found 1 device(s)"
```

### ReSpeaker — "No input device found" / wrong channel count

```bash
# List ALSA devices
arecord -l

# List sounddevice devices
python -m sounddevice

# Try recording manually (replace hw:1 with the card number from arecord -l)
arecord -D hw:1,0 -c 4 -r 16000 -f S16_LE -d 2 /tmp/test.wav
```

### XM125 — "Permission denied: /dev/ttyUSB0"

```bash
sudo usermod -aG dialout pi
# Logout and login again
ls -l /dev/ttyUSB0   # should be rw-rw---- (group dialout)
```

### XM125 — "Failed to connect" / no response

```bash
# Check the device exists
ls /dev/ttyUSB*

# Check firmware is the Exploration Server build
# Use dmesg to see USB device:
dmesg | grep ttyUSB

# Try a lower baud rate or reset the module power
python - <<'EOF'
import serial
with serial.Serial('/dev/ttyUSB0', 115200, timeout=1) as s:
    s.write(b'\n')
    print(s.read(100))
EOF
```

### Camera — "Failed to create preview window" / "No cameras available"

```bash
# Check camera is connected
libcamera-hello --list-cameras

# Check /boot/firmware/config.txt has camera_auto_detect=1
grep camera /boot/firmware/config.txt

# Test Picamera2 directly
python -c "from picamera2 import Picamera2; c = Picamera2(); print(c.camera_properties)"
```

### MQTT — Node not showing in dashboard

```bash
# Check Mosquitto is running on the hub
sudo systemctl status mosquitto

# Test connectivity from the node
mosquitto_pub -h 192.168.1.100 -t test/ping -m "hello"
mosquitto_sub -h 192.168.1.100 -t test/ping -C 1

# Check node config has the correct broker IP
grep broker node/config/node_default.yaml
```

### High CPU Usage

```bash
# Check which driver is spinning
top -b -n1 | grep python

# Reduce optical FPS if needed:
# fps: 15 (instead of 30) in node config

# Disable unused sensors to reduce load:
# acoustic: enabled: false
```

### Acoustic model not found / inference errors

```bash
# Check model exists
ls -lh models/acoustic_drone_cnn.tflite

# Verify TFLite runtime is installed
python -c "import tflite_runtime.interpreter as tflite; print('TFLite OK')"
# If that fails:
pip install tflite-runtime
```

---

## Multi-Node Checklist

When deploying more than one node:

- [ ] Each node has a **unique `node.id`** in its config (`node-01`, `node-02`, …)
- [ ] Each node's `mqtt.broker` points to the hub machine IP
- [ ] Nodes are positioned with **20–30% overlap** in detection coverage
- [ ] All nodes are on the same LAN / VLAN as the hub
- [ ] Hub `hub/config/hub_default.yaml` `fusion.confirmation.min_sensor_layers` is set to `2` (requires at least 2 independent sensor types to confirm a threat)
- [ ] Mosquitto on the hub accepts connections from all node IPs (check `infra/mosquitto/config/mosquitto.conf`)
- [ ] Dashboard env vars point to hub: `NEXT_PUBLIC_HUB_URL=http://<hub-ip>:8080`

---

*For architecture details see [docs/artemis.md](artemis.md).*
*For legal guidance see [node/config/node_default.yaml](../node/config/node_default.yaml) and the Legal Notice in the main README.*
