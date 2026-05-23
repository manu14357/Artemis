# ARTEMIS Node Setup Guide

Step-by-step guide to commission a new ARTEMIS edge node from a blank
Raspberry Pi 5 all the way to a live sensor node on the mesh.

## Prerequisites

- Raspberry Pi 5 (8 GB recommended)
- 64 GB A2 microSD card (or NVMe SSD via HAT)
- All sensors connected (see [SENSOR_GUIDE.md](SENSOR_GUIDE.md))
- Ethernet or Wi-Fi access to your ARTEMIS hub

---

## Step 1 — Flash the SD Card

1. Download [Raspberry Pi Imager](https://www.raspberrypi.com/software/).
2. Select **Raspberry Pi OS Lite (64-bit)** (Bookworm, no desktop).
3. Click the gear icon and configure:
   - Hostname: `artemis-node-01` (or a unique name)
   - Enable SSH → Use password authentication
   - Username: `pi`, set a strong password
   - Wi-Fi SSID / password (if not using Ethernet)
   - Locale / timezone
4. Write to SD card, insert into Pi, power on.

---

## Step 2 — First Login & System Update

```bash
ssh pi@artemis-node-01.local
# Accept host key fingerprint

# Full system upgrade (important on first boot)
sudo apt update && sudo apt full-upgrade -y
sudo reboot
```

---

## Step 3 — Clone the Repository

```bash
sudo apt install -y git
sudo mkdir -p /opt/artemis
sudo chown pi:pi /opt/artemis
git clone https://github.com/manu14357/Artemis /opt/artemis
cd /opt/artemis
```

---

## Step 4 — Run the Provisioning Script

```bash
# Standard install (will prompt for sudo password)
sudo bash scripts/setup_node.sh

# Options:
#   --dry-run        preview all steps without executing
#   --skip-radar     skip XM125 firmware flash (if no radar)
#   --skip-hw-check  suppress Raspberry Pi 5 model check
```

The script performs these steps automatically:
1. Pre-flight checks (hardware model, disk space, Python 3.11)
2. `apt install` system dependencies
3. Audio device detection
4. Python 3.11 virtualenv creation at `/opt/artemis/.venv`
5. `pip install -r requirements.txt`
6. XM125 radar firmware flash (if dongle detected)
7. Mosquitto MQTT broker enable & start
8. `artemis-node.service` systemd unit install & enable
9. `verify_install.py` post-install check

Expected output ends with:
```
╔═══════════════════════════════════════╗
║   ARTEMIS node setup complete! ✓      ║
╚═══════════════════════════════════════╝
```

---

## Step 5 — Configure GPS Coordinates

Edit the node config with your deployment coordinates:

```bash
nano /opt/artemis/node/config/node_default.yaml
```

Set:
```yaml
node:
  id: node-01          # unique across your mesh
  location:
    lat: 28.6139       # decimal degrees N
    lon: 77.2090       # decimal degrees E
    alt_m: 216.0       # meters above sea level
```

You can also set these via environment variables (no config edit needed):
```bash
export ARTEMIS_NODE_ID=node-site-alpha
export ARTEMIS_GPS_LAT=28.6139
export ARTEMIS_GPS_LON=77.2090
export ARTEMIS_GPS_ALT=216.0
```

---

## Step 6 — Point Node at the Hub

Edit the MQTT broker address in `node_default.yaml`:
```yaml
mqtt:
  broker: 192.168.1.10    # IP or hostname of your ARTEMIS hub
  port: 1883
  # username: artemis     # uncomment if broker auth is enabled
  # password: "…"
```

Or use env vars:
```bash
export ARTEMIS_MQTT_BROKER=192.168.1.10
export ARTEMIS_MQTT_USERNAME=artemis
export ARTEMIS_MQTT_PASSWORD=supersecret
```

---

## Step 7 — Run the Post-Install Verification

```bash
python scripts/verify_install.py
```

Expected output (with all sensors connected):
```
ARTEMIS Node Installation Verification
══════════════════════════════════════════════
[PASS] Python ≥ 3.11  3.11.x
[PASS] Package: pyyaml
[PASS] Package: numpy
[PASS] Package: fastapi
[PASS] Package: paho.mqtt.client
[PASS] Package: sounddevice
[PASS] Package: pyrtlsdr
[PASS] Package: acconeer-exptool
[PASS] Package: opencv-python
[PASS] Config file  node/config/node_default.yaml
[PASS] Mosquitto MQTT  127.0.0.1:1883
[PASS] RTL-SDR dongle  opened and closed
[PASS] Audio input device  seeed-voicecard
[PASS] Radar serial port  /dev/ttyUSB0
[PASS] Camera  picamera2 available
[PASS] Acconeer exptool
══════════════════════════════════════════════
PASS=16  WARN=0  SKIP=0  FAIL=0
```

---

## Step 8 — Start the Daemon

```bash
sudo systemctl start artemis-node
sudo systemctl status artemis-node

# Follow live logs
sudo journalctl -u artemis-node -f
```

You should see messages like:
```
INFO  node.main  ARTEMIS node starting: id=node-01 test_mode=False
INFO  node.main  MQTT connected to 192.168.1.10:1883
INFO  node.main  RF driver enabled
INFO  node.main  Acoustic driver enabled
INFO  node.main  Radar driver enabled
INFO  node.main  Optical driver enabled
INFO  node.main  sd_notify: READY=1
```

---

## Step 9 — Join the Mesh

On the hub machine, open the dashboard:
```
http://<hub-ip>:3000
```

Your node should appear on the **Nodes** panel within ~10 seconds after the
first heartbeat is received.

---

## Troubleshooting

| Symptom | Check |
|---|---|
| Service not starting | `sudo journalctl -u artemis-node -n 50` |
| MQTT connection refused | `sudo systemctl status mosquitto` on hub machine |
| RTL-SDR driver error | Check udev rule; `sudo usermod -aG plugdev pi` |
| Radar not detected | Run `python scripts/test_radar.py`; reflash firmware |
| Audio not working | Run `arecord -l`; check `device_index` in config |
| High CPU / memory | Disable unused sensors in `node_default.yaml` |

---

## Resetting a Node

To undo everything `setup_node.sh` did (stop service, delete venv):
```bash
sudo bash scripts/reset_node.sh

# To also delete the repository (WARNING: loses config edits)
sudo bash scripts/reset_node.sh --remove-repo
```
