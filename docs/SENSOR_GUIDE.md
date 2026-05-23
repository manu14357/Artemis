# ARTEMIS Sensor Hardware Guide

This guide covers installation, driver setup, and smoke-testing for every sensor
attached to an ARTEMIS edge node.

## Table of Contents
1. [Bill of Materials](#1-bill-of-materials)
2. [RTL-SDR (RF)](#2-rtl-sdr-rf)
3. [ReSpeaker 4-Mic Array (Acoustic)](#3-respeaker-4-mic-array-acoustic)
4. [Acconeer XM125 Radar](#4-acconeer-xm125-radar)
5. [Raspberry Pi Camera Module 3 (Optical)](#5-raspberry-pi-camera-module-3-optical)
6. [Common Errors](#6-common-errors)

---

## 1. Bill of Materials

| Component | Qty | Notes |
|---|---|---|
| Raspberry Pi 5 (8 GB) | 1 | aarch64, Bookworm OS |
| RTL-SDR Blog V4 dongle | 1 | USB-A, SMA antenna |
| ReSpeaker 4-Mic Array v2 | 1 | Hat for RPi, 4× MEMS mics |
| Acconeer XM125 Pulsed Coherent Radar | 1 | USB-UART bridge |
| Raspberry Pi Camera Module 3 | 1 | IMX708, CSI ribbon |
| 64 GB A2 microSD (or NVMe via HAT) | 1 | High-endurance |
| 5 V / 5 A USB-C PSU | 1 | RPi 5 requires ≥ 5 A |
| IP67 weatherproof enclosure | 1 | ≥ 200×150×75 mm |

---

## 2. RTL-SDR (RF)

### Driver installation
```bash
# System package (librtlsdr)
sudo apt install -y librtlsdr-dev rtl-sdr

# Python binding
pip install pyrtlsdr>=0.3.0

# Add udev rule so the dongle is accessible without root
sudo tee /etc/udev/rules.d/20-rtlsdr.rules <<'EOF'
SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2838", MODE="0664", GROUP="plugdev"
EOF
sudo udevadm control --reload-rules
sudo usermod -aG plugdev $USER
# Re-log for group change to take effect
```

### Verify
```bash
# List detected RTL-SDR devices
rtl_test -t

# Expected output (trimmed):
#   Found 1 device(s):
#   0:  Realtek, RTL2838UHIDIR, SN: ...
```

### Smoke test
```bash
python scripts/test_rf.py
# PASS — RTL-SDR opened, tuned to 2437 MHz, read 256 IQ samples
```

### Config reference (`node_default.yaml`)
```yaml
sensors:
  rf:
    enabled: true
    frequencies: [2437000000, 5780000000, 915000000]
    fft_size: 1024
    threshold_db: -50.0
```

---

## 3. ReSpeaker 4-Mic Array (Acoustic)

### Driver installation
```bash
# Kernel driver — from Seeed Studio repository
git clone --depth 1 https://github.com/HinTak/seeed-voicecard
cd seeed-voicecard
sudo ./install.sh
sudo reboot

# After reboot
sudo apt install -y portaudio19-dev python3-sounddevice
pip install sounddevice>=0.4.6
```

### Verify
```bash
# Should list "seeed-voicecard" input device
arecord -l
# Record 3 s mono test clip
arecord -D plughw:seeed4micvoicec,0 -r 16000 -c 1 -f S16_LE -d 3 /tmp/test.wav
aplay /tmp/test.wav
```

### Smoke test
```bash
python scripts/test_acoustic.py
# PASS — sounddevice opened device[N], read 512-sample block
```

### Config reference
```yaml
sensors:
  acoustic:
    enabled: true
    sample_rate: 16000
    channels: 4       # use 1 for mono development mic
    device_index: 0   # run `python -c "import sounddevice; print(sounddevice.query_devices())"` to find index
    window_ms: 500
    model_path: models/acoustic_drone_cnn.tflite
    confidence_threshold: 0.75
```

---

## 4. Acconeer XM125 Radar

### Driver installation
```bash
pip install acconeer-exptool>=7.0.0

# Grant serial-port access
sudo usermod -aG dialout $USER
```

### Firmware flash
```bash
# Connect XM125 via USB, confirm port
ls /dev/ttyUSB* /dev/ttyACM*

# Flash default firmware (required on first use or after SDK upgrade)
python -m acconeer.exptool.flash flash_default --serial-port /dev/ttyUSB0

# Confirm firmware version
python -m acconeer.exptool.flash --serial-port /dev/ttyUSB0 --print-version
```

### Verify
```bash
python -m acconeer.exptool -m distance --serial-port /dev/ttyUSB0
# Should stream range distance data to stdout
```

### Smoke test
```bash
python scripts/test_radar.py
# PASS — XM125 connected on /dev/ttyUSB0, firmware vX.Y.Z
```

### Config reference
```yaml
sensors:
  radar:
    enabled: true
    serial_port: /dev/ttyUSB0   # auto-updated by setup_node.sh
    start_point: 50
    num_points: 100
    step_length: 2
    profile: PROFILE_5
```

---

## 5. Raspberry Pi Camera Module 3 (Optical)

### Driver installation
```bash
# picamera2 is installed via apt (not pip on Bookworm)
sudo apt install -y python3-picamera2

# Confirm camera detected
libcamera-hello --list-cameras
# Output:  0 : imx708 ...
```

### Verify
```bash
# Capture a test frame
libcamera-still -o /tmp/test.jpg --width 640 --height 480
ls -lh /tmp/test.jpg
```

### Smoke test
```bash
python scripts/test_optical.py
# PASS — picamera2 grabbed 640×480 frame (RPi)
# or
# PASS — OpenCV VideoCapture(0) grabbed frame (dev machine)
```

### Config reference
```yaml
sensors:
  optical:
    enabled: true
    resolution: [640, 480]
    fps: 30
    mog2_learning_rate: 0.005
    min_blob_area: 80
```

---

## 6. Common Errors

| Error | Likely cause | Fix |
|---|---|---|
| `No supported devices found` (RTL-SDR) | Missing udev rule or wrong group | Add udev rule, `sudo usermod -aG plugdev $USER`, re-log |
| `PortAudio error: Invalid device` | Wrong `device_index` | Run `python -c "import sounddevice; print(sounddevice.query_devices())"` |
| `Permission denied: /dev/ttyUSB0` | Not in `dialout` group | `sudo usermod -aG dialout $USER`, re-log |
| `LIBUSB_ERROR_ACCESS` (RTL-SDR) | Another process holds the device | Kill `rtl_tcp`, `rtl_test` or `gnuradio` processes |
| `picamera2: No cameras available` | Ribbon not seated / camera disabled | `sudo raspi-config` → Interface Options → Camera → Enable |
| `acconeer: firmware mismatch` | SDK version changed | Reflash with `python -m acconeer.exptool.flash flash_default` |
