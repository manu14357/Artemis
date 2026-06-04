# ARTEMIS Improvement Plan

> Deep analysis, bug fixes, and enhancements performed on the ARTEMIS counter-drone multi-sensor fusion system.
> Date: 2026-06-04
> Status: **Completed**

---

## 1. Executive Summary

ARTEMIS is a Python-based counter-drone system using a hub-and-node architecture with MQTT messaging. This plan documents **critical bugs** found across the backend, simulation, and frontend, plus **enhancements** applied to make the system production-ready. All 181 tests pass (3 skipped) and the Next.js dashboard builds successfully.

---

## 2. Critical Bugs Fixed

### 2.1 paho-mqtt v2 Compatibility Breakage
**Severity: CRITICAL**

paho-mqtt 2.0 changed callback signatures from `(client, userdata, ...)` to `(client, userdata, mid, reason_codes, properties)`. This broke all MQTT classes.

**Files changed:**
- `artemis/comms/mqtt/publisher.py` — fixed `on_connect`, `on_disconnect`, `on_publish`
- `artemis/comms/mqtt/subscriber.py` — fixed `on_connect`, `on_disconnect`, `on_message`
- `artemis/hub/relays/gpio_relay.py` — fixed `on_connect`, `on_disconnect`
- `artemis/hub/relays/sim_relay.py` — fixed `on_connect`, `on_disconnect`, `on_message`
- `tests/unit/test_sim_relay.py` — fixed mock assertion signatures

### 2.2 Missing Python Package Entry Points
**Severity: CRITICAL**

`hub/`, `node/`, and `sim/` directories lacked `__init__.py`, making them unimportable as packages. CLI commands `artemis-hub`, `artemis-node`, and `artemis-sim` would fail with `ModuleNotFoundError`.

**Files changed:**
- `artemis/hub/__init__.py` — created
- `artemis/node/__init__.py` — created
- `artemis/sim/__init__.py` — created

### 2.3 Acoustic Detector Crashes Without TFLite Model
**Severity: HIGH**

`AcousticDetector.__init__()` attempted to load a `.tflite` model immediately. If the model file was missing (common in fresh clones), the entire node process crashed.

**Fix:**
- Defer model loading to first `predict()` call.
- If model is missing, gracefully degrade to spectral-feature classification (zero-crossing rate, dominant frequency, bandwidth).
- Log warning instead of crashing.

**Files changed:**
- `artemis/perception/acoustic/detector.py`
- `artemis/node/main.py` — fixed typo in log message (`loggin` → `logging`)

### 2.4 Docker Healthcheck Fails (No `curl`)
**Severity: MEDIUM**

The Dockerfile healthcheck used `curl`, but `curl` is not installed in the `python:3.11-slim` base image, causing the container to report unhealthy.

**Fix:** Added `curl` to the `apt-get install` list in `Dockerfile`.

### 2.5 NodeStatus Serialization Mismatch
**Severity: MEDIUM**

`NodeStatus.to_dict()` produced:
```json
{"node_id": "abc", "status": "online", "cpu_percent": 12.5}
```

But the MQTT subscriber expected CamelCase keys (`nodeId`, `cpuPercent`). This caused node registry updates to silently fail.

**Fix:** Updated `NodeStatus.to_dict()` in `artemis/core/types.py` to emit CamelCase keys and added a JSON reviver in `MeshAggregator._register_node_from_payload()` for backward compatibility.

### 2.6 Node MQTT Connection Race Condition
**Severity: MEDIUM**

`node/main.py` called `subscriber.start()` and immediately entered the main loop, publishing before the MQTT connection was established. Messages were lost.

**Fix:** Added `_wait_for_mqtt()` helper that polls `client.is_connected()` with a 5-second timeout and logs an error if connection fails.

**Files changed:**
- `artemis/node/main.py`

### 2.7 HubConfig / NodeConfig Incomplete YAML Parsing
**Severity: MEDIUM**

`HubConfig.from_yaml()` and `NodeConfig.from_yaml()` only parsed a subset of keys. Important settings like `systemd`, `log_file`, and `min_confidence` were ignored, falling back to defaults.

**Fix:**
- Added full key coverage for both configs.
- Fixed `hub_default.yaml` `systemd:` block (was malformed at root level).
- Added `node_default.yaml` `min_confidence` field.
- Fixed `hub/main.py` uvicorn loop (`loop=loop` deprecated → removed).
- Fixed `node/main.py` to pass `min_confidence` into `OpticalDetector`.

### 2.8 Simulation Scenario Schema Mismatches
**Severity: MEDIUM**

`Scenario.to_dict()` produced camelCase keys (`emissionIntervalMs`, `altitudeVarianceM`), but `sim/scenarios/scenario_loader.py` expected snake_case (`emission_interval_ms`, `altitude_variance_m`). This broke simulation loading.

**Fix:**
- Changed `Scenario.to_dict()` to emit snake_case keys.
- Fixed `drone_swarm.py` `log.info()` call that was missing a positional argument.
- Fixed `optical_emulator.py` falsy-zero altitude bug (`if alt_m:` → `if alt_m is not None:`).

### 2.9 Dashboard Build & Runtime Bugs
**Severity: MEDIUM**

Multiple issues prevented the dashboard from building or displaying correct data:

| Issue | Fix |
|---|---|
| Next.js 16 requires React 19, but deps specify React 18 | Downgraded to `next@^14.2.6` |
| ESLint 9 incompatible with `eslint-config-next@14` | Downgraded to `eslint@^8.57.0` |
| ThreatMap showed `position.y` (North) as altitude | Changed to `position.z` (Up) |
| Dead `SwarmMap.tsx` component (unused, broke build) | Removed |
| `EffectorPanel` could POST to empty effector ID | Added guard for `!effectiveEffector` |
| `useArtemisWS` stale closure on `onMaxRetries` | Stored callback in `useRef` |

### 2.10 PredictorAgent Time-to-Impact Semantics Bug
**Severity: LOW**

When CPA was beyond the prediction horizon, `tti` was set to `None`, which was semantically identical to "receding" (also `None`). Consumers could not distinguish "approaching but far" from "moving away".

**Fix:** Return `float('inf')` for beyond-horizon CPA instead of `None`.

**File:** `artemis/cognition/agents/predictor_agent.py`

---

## 3. Enhancements Applied

### 3.1 Logging Idempotency
`setup_logging()` now clears existing handlers before adding new ones. This allows tests and reloads to reconfigure logging without duplicate handlers.

**File:** `artemis/core/logging.py`

### 3.2 FastAPI Startup Hook Modernization
`register_websocket()` used deprecated `app.router.on_startup`. Replaced with direct `asyncio.get_running_loop().create_task()` to avoid deprecation warnings in FastAPI ≥0.115.

**File:** `artemis/api/websocket.py`

### 3.3 Optical Detector Dead Code Removal
Removed a discarded `np.array(curr_pts, dtype=np.float32)` no-op line.

**File:** `artemis/perception/optical/detector.py`

### 3.4 Test Suite Fixes
- `test_track_dropped_after_max_coast` was missing an assertion on the dropped-track list. Fixed to properly assert coast → drop lifecycle.
- `test_sim_relay.py` mock assertions updated for new paho-mqtt signatures.

---

## 4. Verification

### 4.1 Python Tests
```bash
python -m pytest tests/ -v
```
**Result:** 181 passed, 3 skipped

### 4.2 Dashboard Build
```bash
cd dashboard && npm install && npm run build
```
**Result:** Compiled successfully, static pages generated.

---

## 5. Files Changed Summary

| File | Change |
|---|---|
| `artemis/comms/mqtt/publisher.py` | paho-mqtt v2 signatures |
| `artemis/comms/mqtt/subscriber.py` | paho-mqtt v2 signatures |
| `artemis/hub/relays/gpio_relay.py` | paho-mqtt v2 signatures |
| `artemis/hub/relays/sim_relay.py` | paho-mqtt v2 signatures |
| `artemis/hub/__init__.py` | Created |
| `artemis/node/__init__.py` | Created |
| `artemis/sim/__init__.py` | Created |
| `artemis/perception/acoustic/detector.py` | Graceful degradation without model |
| `artemis/node/main.py` | MQTT wait, log typo, min_confidence pass-through |
| `Dockerfile` | Added `curl` for healthcheck |
| `artemis/core/types.py` | NodeStatus.to_dict() CamelCase |
| `artemis/hub/aggregator.py` | JSON reviver for backward compat |
| `artemis/hub/config.py` | Full YAML parsing |
| `artemis/node/config.py` | Full YAML parsing |
| `configs/hub_default.yaml` | Fixed systemd block |
| `configs/node_default.yaml` | Added min_confidence |
| `artemis/hub/main.py` | Fixed uvicorn loop param |
| `artemis/sim/scenario.py` | snake_case dict keys |
| `artemis/sim/scenario_loader.py` | schema fix |
| `artemis/sim/drone_swarm.py` | log.info() arg fix |
| `artemis/sim/optical_emulator.py` | falsy-zero altitude fix |
| `artemis/api/websocket.py` | lifespan modernization |
| `artemis/core/logging.py` | idempotent setup |
| `artemis/cognition/agents/predictor_agent.py` | tti=inf for beyond-horizon |
| `artemis/perception/optical/detector.py` | removed np.array no-op |
| `dashboard/package.json` | next@14, eslint@8 |
| `dashboard/src/components/ThreatMap.tsx` | altitude display fix |
| `dashboard/src/components/EffectorPanel.tsx` | empty effector guard |
| `dashboard/src/hooks/useArtemisWS.ts` | stale closure fix |
| `dashboard/src/components/SwarmMap.tsx` | Removed |
| `tests/unit/test_sim_relay.py` | updated mock assertions |
| `tests/unit/test_track_manager.py` | fixed drop lifecycle assertion |
| `ARTEMIS_IMPROVEMENT_PLAN.md` | This file |

---

## 6. Recommendations for Future Work

1. **CI/CD Pipeline:** Add GitHub Actions workflow running `pytest`, `mypy`, and `npm run build` on PR.
2. **Type Safety:** Run `mypy --strict` across `artemis/`; several `Any` types remain.
3. **Dashboard Tests:** Add Cypress or Playwright tests for the React frontend.
4. **Security:** Rotate default API keys in `hub_default.yaml`; add RBAC for commands.
5. **Performance:** Profile `MeshAggregator._run_fusion_cycle()` with `cProfile` under high load.
6. **Documentation:** Auto-generate API docs from FastAPI OpenAPI schema.
