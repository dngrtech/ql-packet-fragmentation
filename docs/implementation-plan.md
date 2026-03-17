# Implementation Plan

## Phase 1 — Proof of Concept (Terminal Output)

**Goal:** Validate that we can capture QL packet sizes and that fragmentation occurs at 99k rate.

### Deliverables
- eBPF program (C) that captures outbound UDP packet metadata on QL ports
- Python userspace script that reads BPF maps every 10 seconds
- Every 10 seconds prints to terminal:
  - Histogram of packet sizes (bucketed)
  - Fragmentation percentage
  - Per-player breakdown (if Redis is available)

### Requirements
- Python 3.8+
- bcc or bpfcc-tools (eBPF toolchain)
- Linux kernel with BPF support (frozen version)
- Root/CAP_BPF + CAP_NET_ADMIN
- Redis (optional, for player mapping)

---

## Phase 2 — Persistent Collection

**Goal:** Store measurements in InfluxDB for long-term analysis.

### Deliverables
- Systemd service unit for the capture daemon
- InfluxDB integration (influxdb-client-python)
- Configurable via CLI args or config file:
  - Port range
  - InfluxDB connection
  - Redis connection
  - Aggregation interval
  - Rate setting label (for experiment tagging)
- Retention policy (auto-purge old data)

---

## Phase 3 — Visualization & Analysis

**Goal:** Grafana dashboards and data export for the paper.

### Deliverables
- Grafana dashboard JSON (importable)
  - Fragmentation % over time
  - Per-player fragmentation rates
  - Packet size distribution histogram
  - Comparison view: 25k vs 99k
- Python script to export data as CSV for statistical analysis
- Matplotlib/seaborn scripts for publication-quality charts

---

## Phase 4 — Controlled Experiments

**Goal:** Run structured A/B tests for the paper.

### Experiment Design
1. Same 8 players, same map (e.g., campgrounds), same mode (CA)
2. Run N rounds at each rate setting: 25k, 99k
3. Capture packet data + player subjective feedback
4. Compare distributions across settings

### Data Points Per Experiment
- Fragmentation rate (% of packets > 1472 bytes)
- Average/median/p95/p99 packet sizes
- Per-player fragmentation variance
- Correlation: player count in PVS vs packet size
