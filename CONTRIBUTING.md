# Contributing to ARTEMIS

Thank you for your interest in improving ARTEMIS. This guide explains how to
set up a development environment, make changes, and open a pull request.

---

## Quick start

```bash
git clone https://github.com/manu14357/Artemis
cd Artemis
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install ruff black pytest pytest-asyncio

# Run the full test suite
pytest tests/ -q
```

---

## Branch naming

| Prefix | Purpose |
|---|---|
| `feat/` | New features |
| `fix/` | Bug fixes |
| `docs/` | Documentation only |
| `test/` | Test-only changes |
| `chore/` | Dependency updates, CI, tooling |

Example: `feat/radar-velocity-filter`

---

## Coding standards

- **Python 3.11+**, type annotations required on all public functions.
- **ruff** for linting: `ruff check .`
- **black** for formatting: `black --check .`

CI fails on any lint or format violations. Run before pushing:
```bash
ruff check . && black .
```

---

## Sensor driver changes

When adding or modifying a PerceptionDriver:

1. Inherit from `artemis.perception.base.PerceptionDriver`.
2. Implement `start()`, `stop()`, and `stream()` (async generator).
3. Ensure `stream()` yields `Detection` objects — use `artemis.core.types`.
4. Add or update the corresponding entry in `node/config/node_default.yaml`.
5. Update `scripts/test_<sensor>.py` with a real smoke test.
6. Add unit tests in `tests/unit/test_perception_<sensor>.py`.

---

## Tests

- All tests live under `tests/` and use `pytest`.
- **Unit tests**: `tests/unit/` — must not require hardware; mock sensor I/O.
- **Integration tests**: `tests/integration/` — may start in-process FastAPI servers.
- **Load tests**: `tests/load/` — optional, not run in CI.
- Hardware tests use `@pytest.mark.hardware` and are excluded from CI (`-m "not hardware"`).

Run with coverage:
```bash
pytest tests/unit tests/integration -q --tb=short
```

---

## Pull Request checklist

- [ ] `ruff check .` passes
- [ ] `black --check .` passes  
- [ ] `pytest tests/unit tests/integration -q` passes
- [ ] New public functions have docstrings and type annotations
- [ ] Sensor changes update `node_default.yaml` + smoke test script
- [ ] Config schema changes update `docs/` (NODE_SETUP.md, SENSOR_GUIDE.md)
- [ ] No credentials, API keys, or IP addresses committed

---

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(radar): add velocity threshold filter to XM125Processor
fix(mqtt): handle broker disconnect without raising unhandled exception
docs(api): document JWT token refresh flow
```

---

## Getting help

Open an issue or start a Discussion on GitHub.
For security vulnerabilities, see [SECURITY.md](SECURITY.md) — do NOT open a
public issue.
