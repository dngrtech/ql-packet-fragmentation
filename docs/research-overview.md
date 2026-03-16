# Quake Live Packet Fragmentation Analysis

## Research Goal

Scientific analysis of network packet fragmentation in competitive Quake Live (4v4 Clan Arena) to determine the optimal `rate` engine setting. The findings will be published as a research paper.

## The Problem

Quake Live's `rate` cvar controls how much game state data the server sends per snapshot. Two common settings create a fundamental tradeoff:

- **25k rate**: Prevents fragmentation by limiting payload size, but causes "engine choke" during chaotic moments — the engine drops/delays game state (audio cues, player movement) to stay within the size budget.
- **99k rate**: Sends complete game state regardless of size, but produces packets that exceed the MTU, triggering IP-layer fragmentation. Lost fragments invalidate entire packets, causing perceived lag ("delayed rockets").

## The Hypothesis

A `rate` setting around **50k–52k** may provide the sweet spot: large enough to avoid engine choke in 4v4 Clan Arena fights, small enough to avoid routine fragmentation.

## Fragmentation Threshold (Standard Network)

```
MTU:                 1500 bytes
IPv4 Header:           20 bytes
UDP Header:             8 bytes
─────────────────────────────────
Max payload before
fragmentation:       1472 bytes
```

Any outbound UDP packet from the Quake server with a payload exceeding 1472 bytes will be fragmented at the IP layer. For UDP (connectionless), a single lost fragment means the entire datagram is dropped — there is no retransmission.

## Research Methodology

1. **Passive packet capture** on the Quake server using tcpdump with BPF kernel filtering (outbound UDP only)
2. **In-memory aggregation** in a Python daemon — 10-second bucketed stats
3. **Per-player correlation** using minqlx Redis data (steamid → IP mapping)
4. **Time-series storage** in InfluxDB with Grafana visualization
5. **Controlled experiments**: Run matches at 25k, 50k, 75k, 99k with the same players/map/mode and compare fragmentation distributions
