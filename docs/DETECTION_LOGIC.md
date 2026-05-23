# ARTEMIS Detection Logic

Technical reference for the per-layer detection algorithms and the multi-sensor
fusion pipeline.

---

## 1. RF Layer (`artemis/perception/rf/rtlsdr_listener.py`)

**Algorithm: FFT peak detection**

1. RTL-SDR dongle tunes to each configured frequency in round-robin.
2. 1024 IQ samples captured per read (configurable via `fft_size`).
3. Real FFT computed with NumPy; output is power spectrum in dBFS.
4. Peak power `P_max` extracted.
5. If `P_max > threshold_db`, a Detection is emitted with `confidence = (P_max - threshold_db) / 20` (clipped to 1.0).

**Key config parameters:**
```yaml
sensors:
  rf:
    frequencies: [2437000000, 5780000000, 915000000]
    fft_size: 1024
    threshold_db: -50.0
```

**Drone RF signatures monitored:**
| Band | Frequency | Protocol |
|---|---|---|
| 2.4 GHz Wi-Fi | 2437 MHz (ch 6) | DJI OcuSync, Wi-Fi RC |
| 5.8 GHz | 5780 MHz | DJI O3, FPV video |
| 900 MHz ISM | 915 MHz | LoRa, legacy RC |

---

## 2. Acoustic Layer (`artemis/perception/acoustic/classifier.py`)

**Algorithm: STFT → Mel spectrogram → TFLite CNN**

1. `sounddevice` captures audio at 16 kHz, 1–4 channels, 500 ms windows (8000 samples).
2. 40-band Mel spectrogram computed via `librosa` / NumPy STFT.
3. Single-channel spectrogram (shape: `[1, 40, T]`) fed into TFLite model `acoustic_drone_cnn.tflite`.
4. Model outputs class probabilities: `[drone, bird, wind, ambient]`.
5. If `P(drone) > confidence_threshold`, Detection emitted with `confidence = P(drone)`.

**Model training:**
- Dataset: UrbanSound8K + custom drone recordings (DJI Mini 3 Pro, FPV 5-inch).
- Architecture: 3× Conv2D (ReLU, BN, MaxPool) → 2× Dense → Softmax.
- Input: `[1, 40, 32]` (40 mel bins × 32 time frames ≈ 500 ms at 16 kHz).
- Training script: `scripts/train_acoustic_model.py`.

**Key config parameters:**
```yaml
sensors:
  acoustic:
    sample_rate: 16000
    window_ms: 500
    model_path: models/acoustic_drone_cnn.tflite
    confidence_threshold: 0.75
```

---

## 3. Radar Layer (`artemis/perception/radar/xm125_processor.py`)

**Algorithm: Pulsed coherent radar — Doppler IQ processing**

1. Acconeer XM125 configured in **Distance + Velocity** mode via `acconeer.exptool`.
2. Radar sweeps 50–150 range points (`start_point`, `num_points`, `step_length` in profile units).
3. Peak range distance `R_peak` and radial velocity `V_peak` extracted from the SDK output.
4. Confidence heuristic: `SNR_dB / 30` (clipped to 1.0) for non-zero velocity detections.
5. Detection emitted only when `|V_peak| > 0.3 m/s` (filters static clutter).

**Profile mapping:**
| Profile | Max range | Range resolution |
|---|---|---|
| `PROFILE_1` | 0.5 m | 2 mm |
| `PROFILE_3` | 3 m | 6 mm |
| `PROFILE_5` | 7 m | 14 mm |

**Key config parameters:**
```yaml
sensors:
  radar:
    serial_port: /dev/ttyUSB0
    start_point: 50
    num_points: 100
    step_length: 2
    profile: PROFILE_5
```

---

## 4. Optical Layer (`artemis/perception/optical/detector.py`)

**Algorithm: MOG2 background subtraction + Lucas-Kanade optical flow**

1. `picamera2` (RPi) or `cv2.VideoCapture` (dev) captures frames at configured FPS and resolution.
2. **MOG2** (`cv2.createBackgroundSubtractorMOG2`) computes foreground mask.
   - `mog2_learning_rate` (default 0.005) balances adaptability vs. noise.
3. Morphological `open` + `close` removes noise.
4. `cv2.connectedComponentsWithStats` extracts blobs; blobs with area < `min_blob_area` discarded.
5. For each surviving blob, **Lucas-Kanade** sparse optical flow (`cv2.calcOpticalFlowPyrLK`) tracks
   corner points between consecutive frames to estimate velocity vector.
6. Confidence = `min(blob_area / 2000, 1.0)` × motion magnitude factor.

**Key config parameters:**
```yaml
sensors:
  optical:
    resolution: [640, 480]
    fps: 30
    mog2_learning_rate: 0.005
    min_blob_area: 80
```

---

## 5. Multi-Sensor Fusion (`artemis/fusion/track_manager.py`)

### 5.1 Detection → Track Assignment

- Incoming Detections are associated with existing Tracks using **Hungarian algorithm**
  (`scipy.optimize.linear_sum_assignment`) on a Euclidean distance cost matrix.
- Max association distance: `fusion.assignment.max_distance_m` (default 50 m).
- New Detections beyond this threshold spawn new tentative tracks.

### 5.2 Per-Track EKF

Each Track maintains an **Extended Kalman Filter** with 6-state vector `[x, y, z, vx, vy, vz]`
in local East-North-Up (ENU) metres.

| Matrix | Value |
|---|---|
| Process noise Q | `diag(q, q, q, q, q, q)` where `q = process_noise_q` |
| Measurement noise R | `diag(r, r, r)` where `r = measurement_noise_r` |
| Predict step | Constant-velocity model, ∆t from timestamp diff |
| Update step | Position-only observation (3D) |

### 5.3 Track Lifecycle

| State | Condition |
|---|---|
| **Tentative** | Newly created, < `min_sensor_layers` confirmed layers |
| **Confirmed** | ≥ `min_sensor_layers` distinct sensor layers contributed |
| **Coasting** | No update for N frames (counter ≤ `max_coast_frames`) |
| **Deleted** | Coasting counter exceeded; removed from map |

### 5.4 Swarm Detection (DBSCAN)

When ≥ 3 confirmed tracks are present, **DBSCAN** (`sklearn.cluster.DBSCAN`) clusters
them in 3D ENU space:
- `eps` = `fusion.swarm.eps_m` (default 100 m)
- `min_samples` = `fusion.swarm.min_samples` (default 3)

Clusters with ≥ `min_samples` tracks are classified as swarms and published in the
ThreatMap snapshot.

---

## 6. Threat Scoring (`artemis/cognition/agents/threat_scorer.py`)

Final threat score for each track:

```
score = w_conf * avg_layer_confidence
      + w_vel  * min(speed_ms / 30.0, 1.0)
      + w_prox * max(0, 1 - range_m / 500.0)
      + w_swarm * (1.0 if in_swarm else 0.0)
```

Default weights: `w_conf=0.4, w_vel=0.2, w_prox=0.3, w_swarm=0.1`

Scores above the command threshold (default 0.7) trigger an `EngagementCommand`
routed through `CommandRouter` → `SchedulerAgent` → `EffectorManager`.
