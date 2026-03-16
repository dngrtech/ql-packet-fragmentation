# Architecture

## System Overview

```
┌─────────────────────────────────────────────────┐
│  Quake Live Server (per instance)               │
│                                                  │
│  ┌──────────┐    ┌─────────────────────────┐    │
│  │ tcpdump  │───→│ Python Aggregator       │    │
│  │ (BPF     │    │  - parse packet lengths  │    │
│  │  filter) │    │  - 10s in-memory buckets │    │
│  └──────────┘    │  - periodic Redis lookup │    │
│                  │    for player mapping     │    │
│  ┌──────────┐    │  - write to InfluxDB     │    │
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

**tcpdump with BPF filter** — chosen for lowest practical overhead at ~320 packets/sec.

The BPF filter runs in kernel space, so only matching packets (outbound UDP on QL ports) are copied to userspace. At 320 pps this is negligible overhead.

For the paper, we can optionally benchmark against eBPF to prove both methods produce identical results and neither affects gameplay.

### Capture command

```bash
tcpdump -n -l -e -Q out udp and src portrange 27960-27963
```

- `-n`: no DNS resolution (saves CPU)
- `-l`: line-buffered output (for piping to Python)
- `-e`: show link-layer header (includes frame length)
- `-Q out`: outbound only

## Data Pipeline

### 1. Packet Capture (tcpdump → Python)

tcpdump outputs one line per packet. Python reads lines, extracts:
- Timestamp
- Destination IP (→ maps to player)
- Packet length (UDP payload size)

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
| Tag    | rate_setting       | Engine rate (25k, 50k, 99k)          |
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
| Tag    | rate_setting       | Engine rate for this experiment       |
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

All methods are negligible at this packet rate. tcpdump chosen for simplicity.
