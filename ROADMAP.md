# quota-sentinel Roadmap

## Phase 1: Test Infrastructure (Setup)

### P1-T01: Set up pytest configuration
- **Description**: Configure pytest, add conftest.py, set up test discovery
- **Status**: DONE
- **Size**: S

### P1-T02: Create tests directory structure
- **Description**: Create tests/ directory with __init__.py, conftest.py
- **Status**: DONE
- **Size**: S

### P1-T03: Write unit tests for engine.py (VelocityTracker)
- **Description**: Test velocity calculation, exhaustion projection, linear regression
- **Status**: DONE
- **Size**: M

### P1-T04: Write unit tests for allocator.py
- **Description**: Test budget allocation logic, weight calculation
- **Status**: DONE
- **Size**: M

### P1-T05: Write unit tests for store.py
- **Description**: Test instance registration, heartbeat, GC logic
- **Status**: DONE
- **Size**: M

### P1-T06: Create Dockerfile.e2e for end-to-end tests
- **Description**: Create Dockerfile.e2e that builds image and runs e2e client simulation
- **Status**: DONE
- **Size**: M

### P1-T07: Write e2e tests (Docker-based)
- **Description**: Write tests that start container, register instance, verify API responses
- **Status**: DONE
- **Size**: L

### P1-T08: Verify CI passes with tests
- **Description**: Update CI workflow to actually run pytest, verify all pass
- **Status**: DONE
- **Size**: S

---

## Phase 2: Quality & Coverage

### P2-T01: Increase test coverage to 80%
- **Description**: Identify gaps, add tests for uncovered paths
- **Status**: TODO
- **Size**: L

### P2-T02: Fix mypy type errors
- **Description**: Fix pre-existing type errors in server.py and daemon.py
- **Status**: TODO
- **Size**: M

### P2-T03: Add provider tests (mocked HTTP)
- **Description**: Test provider fetch methods with mocked HTTP responses
- **Status**: TODO
- **Size**: L

---

## Phase 3: Features & Improvements

### P3-T01: Add configuration via environment variables
- **Description**: Support HOST, PORT, POLL_INTERVAL env vars
- **Status**: TODO
- **Size**: S

### P3-T02: Add metrics endpoint
- **Description**: Add /v1/metrics for Prometheus-compatible metrics
- **Status**: TODO
- **Size**: M

### P3-T03: Improve error handling in providers
- **Description**: Better error messages, retry logic
- **Status**: TODO
- **Size**: M

---

## Notes

- All tasks in Phase 1 must complete before Phase 2
- Ralph will execute tasks in order
- Each task should be PR-sized (one small commit per task)
