# Architecture

## Current System Overview

```
┌────────────────────────────────────────────────────────────┐
│ Quake Live host                                            │
│                                                            │
│  ┌────────────────┐     ┌───────────────────────────────┐  │
│  │ TC egress eBPF │────→│ Python userspace (`run.py`)   │  │
│  │ on `enp1s0`    │     │ - read BPF map every N sec    │  │
│  │                │     │ - aggregate packet sizes      │  │
│  │ key:           │     │ - join with Redis player map  │  │
│  │ (server port,  │     │ - print terminal summary      │  │
│  │  dest port,    │     │   per server instance         │  │
│  │  payload size) │     └───────────────────────────────┘  │
│  └────────────────┘                    ▲                   │
│                                        │                   │
│  ┌──────────────────────────────┐      │                   │
│  │ minqlx `serverchecker` plugin│──────┘                   │
│  │ Redis key:                   │                          │
│  │ `minqlx:server_status:<port>`│                          │
│  │ player fields include        │                          │
│  │ `name`, `steam`, `udp_port`  │                          │
│  └──────────────────────────────┘                          │
└────────────────────────────────────────────────────────────┘
```

InfluxDB persistence is now implemented in the Python collector. The current
deployment also runs the collector under systemd. Grafana and longer-term
retention/export work remain later phases.

## Capture Method

**eBPF** — chosen for in-kernel aggregation with zero userspace packet copies.

An eBPF program attached to TC egress on the real outbound interface inspects
UDP packets whose source port matches the Quake Live server port range. Packet
metadata `(server UDP port, destination UDP port, UDP payload length)` is
aggregated directly into a BPF hash map, which Python reads on a fixed
interval.

### Why eBPF over tcpdump

- No per-packet copy to userspace — aggregation happens in kernel
- BPF maps provide structured data directly (no line parsing)
- Lower overhead at any packet rate
- Kernel version frozen, so BPF CO-RE portability is not a concern

## Data Pipeline

### 1. Packet Capture

The kernel program runs on TC egress, filters outbound UDP packets for the QL
server port range, and increments counters keyed by `(server_port,
client_udp_port, udp_payload_size)`.

### 2. In-Memory Aggregation

Every interval, Python computes server-level and per-client-port stats for each
captured QL server port:
- Total packet count
- Fragmented packet count (payload > 1472 bytes)
- Average packet size
- Max packet size
- Histogram buckets: [0-500, 500-1000, 1000-1472, 1472+]

### 3. Player Mapping

The bundled `serverchecker` plugin writes
`minqlx:server_status:<server_port>` to the same Redis instance already used by
minqlx. Each player entry includes `name`, `steam`, and `udp_port`.

Userspace reads that JSON payload and builds a transient map:

`{udp_port: (steamid, cleaned_name)}`

That `udp_port` matches the packet destination port captured by eBPF, so no
IP-based correlation or rcon query is needed.

### 4. Terminal Output

The collector prints a terminal report per interval:

- server-level fragmentation summary
- histogram buckets
- per-player rows when Redis mapping is available

### 5. InfluxDB Write

When configured, the collector also writes each interval to InfluxDB 2.x using
the official Python client.

Measurements:

- `packet_stats`: one point per `(host, server_port)` interval
- `player_packets`: one point per mapped player per `(host, server_port)` interval

Tags:

- `host`
- `server_port`
- `rate_setting` when supplied
- `steam_id` and `player_name` on `player_packets`

## Planned Extensions

Later phases will add:

- Grafana dashboards
- retention and operational hardening
- controlled 25k vs 99k experiment exports

## Overhead Analysis

| Method | Overhead per packet | At 320 pps | Player impact |
|--------|-------------------|------------|---------------|
| eBPF   | ~100ns            | ~32μs/sec  | None          |
| tcpdump (BPF) | ~1-5μs     | ~0.5-1.6ms/sec | None     |
| scapy  | ~50-100μs         | ~16-32ms/sec | None        |

All methods are negligible at this packet rate. eBPF chosen for in-kernel aggregation and zero userspace copies. Kernel version is frozen to avoid verifier compatibility issues.
