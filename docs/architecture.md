# Architecture

## System Overview

```
┌─────────────────────────────────────────────────┐
│  Quake Live Server (per instance)               │
│                                                  │
│  ┌──────────┐    ┌─────────────────────────┐    │
│  │ eBPF     │───→│ Python Userspace        │    │
│  │ (TC/XDP  │    │  - read BPF maps (10s)   │    │
│  │  egress) │    │  - periodic Redis lookup │    │
│  └──────────┘    │    for player mapping     │    │
│                  │  - write to InfluxDB     │    │
│  ┌──────────┐    │                           │    │
│  │ Redis    │───→│                           │    │
│  │ (minqlx) │    └─────────────────────────┘    │
│  └──────────┘                                    │
└──────────────────────┬──────────────────────────┘
                       │
                       ▼
              ┌─────────────────┐
              │   InfluxDB      │
              │                 │
              │ Measurements:   │
              │ - packet_stats  │
              │   (aggregated)  │
              │ - player_frag   │
              │   (per-player)  │
              └────────┬────────┘
                       │
                       ▼
              ┌─────────────────┐
              │   Grafana       │
              │                 │
              │ - Frag % over   │
              │   time          │
              │ - Per-player    │
              │   frag rates    │
              │ - Size distrib  │
              │   histogram     │
              └─────────────────┘
```

## Capture Method

**eBPF** — chosen for in-kernel aggregation with zero userspace packet copies.

An eBPF program attached to the network interface (TC egress or XDP) inspects outbound UDP packets on QL ports. Packet metadata (length, destination IP, port) is recorded into BPF maps, which the Python userspace component reads on a 10-second interval. The kernel version is frozen to avoid BPF verifier compatibility issues.

### Why eBPF over tcpdump

- No per-packet copy to userspace — aggregation happens in kernel
- BPF maps provide structured data directly (no line parsing)
- Lower overhead at any packet rate
- Kernel version frozen, so BPF CO-RE portability is not a concern

## Data Pipeline

### 1. Packet Capture (eBPF → BPF Maps → Python)

eBPF program runs in kernel, inspects each outbound UDP packet on QL ports. Per-packet metadata (destination IP, UDP payload length) is aggregated directly into BPF maps (per-IP histograms). Python reads maps every 10 seconds.

### 2. In-Memory Aggregation

Every 10 seconds, the aggregator computes per-port and per-player stats:
- Total packet count
- Fragmented packet count (payload > 1472 bytes)
- Average packet size
- Max packet size
- Histogram buckets: [0-500, 500-1000, 1000-1472, 1472+]

### 3. Player Mapping (Redis → Python)

At capture start and every 60 seconds, query minqlx Redis:

```
minqlx:players:<steamid>          → list  (player name at index 0)
minqlx:players:<steamid>:ips      → set   (IP addresses)
minqlx:players:<steamid>:last_seen → string (timestamp)
```

Build reverse index: `{ip: (steamid, player_name)}`

### 4. InfluxDB Write

Every 10 seconds, flush aggregated data to InfluxDB.

## InfluxDB Schema

### Measurement: `packet_stats` (10-second server-level aggregates)

| Type   | Name               | Description                          |
|--------|--------------------|--------------------------------------|
| Tag    | server_port        | QL server port (e.g., 27960)         |
| Tag    | rate_setting       | Engine rate (25k or 99k)             |
| Field  | total_packets      | Total outbound packets               |
| Field  | fragmented_packets | Packets with payload > 1472 bytes    |
| Field  | avg_size           | Average payload size in bytes        |
| Field  | max_size           | Maximum payload size in bytes        |
| Field  | bucket_0_500       | Count of packets 0–500 bytes         |
| Field  | bucket_500_1000    | Count of packets 500–1000 bytes      |
| Field  | bucket_1000_1472   | Count of packets 1000–1472 bytes     |
| Field  | bucket_1472_plus   | Count of packets > 1472 bytes        |

### Measurement: `player_packets` (10-second per-player aggregates)

| Type   | Name               | Description                          |
|--------|--------------------|--------------------------------------|
| Tag    | server_port        | QL server port                       |
| Tag    | steam_id           | Player's Steam ID                    |
| Tag    | player_name        | Player name (from minqlx Redis)      |
| Tag    | player_ip          | Player's IP address                  |
| Tag    | rate_setting       | Engine rate (25k or 99k)             |
| Field  | total_packets      | Packets sent to this player          |
| Field  | fragmented_packets | Fragmented packets to this player    |
| Field  | avg_size           | Avg payload size to this player      |
| Field  | max_size           | Max payload size to this player      |

## Overhead Analysis

| Method | Overhead per packet | At 320 pps | Player impact |
|--------|-------------------|------------|---------------|
| eBPF   | ~100ns            | ~32μs/sec  | None          |
| tcpdump (BPF) | ~1-5μs     | ~0.5-1.6ms/sec | None     |
| scapy  | ~50-100μs         | ~16-32ms/sec | None        |

All methods are negligible at this packet rate. eBPF chosen for in-kernel aggregation and zero userspace copies. Kernel version is frozen to avoid verifier compatibility issues.
