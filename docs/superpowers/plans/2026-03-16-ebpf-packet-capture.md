# eBPF Packet Capture for QL Fragmentation Analysis — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Phase 1 proof-of-concept that captures outbound Quake Live UDP packets via eBPF (TC egress), aggregates packet size stats in BPF maps, and prints fragmentation analysis to the terminal every 10 seconds — with optional per-player breakdown via minqlx Redis.

**Architecture:** An eBPF C program attached to TC egress filters outbound UDP on configurable ports (default 27960-27963). It records per-destination-IP packet size data into BPF hash maps. A Python userspace daemon reads these maps every 10 seconds, correlates IPs to players via Redis, and prints bucketed histograms + fragmentation percentages.

**Tech Stack:** Python 3.8+, BCC (bpfcc-tools / python3-bcc), redis-py, Linux kernel with BPF + TC support (frozen version).

---

## File Structure

```
ql-packet-fragmentation/
├── src/
│   ├── __init__.py                  # Package marker
│   ├── bpf_program.c               # eBPF C program (TC egress classifier)
│   ├── capture.py                   # Python: loads BPF, reads maps, runs main loop
│   ├── aggregator.py                # Python: aggregation logic (bucket stats from raw map data)
│   ├── player_map.py                # Python: Redis reverse index (IP → steamid/name)
│   └── display.py                   # Python: terminal output formatting
├── tests/
│   ├── __init__.py
│   ├── test_aggregator.py           # Unit tests for aggregation logic
│   ├── test_player_map.py           # Unit tests for player mapping (mocked Redis)
│   └── test_display.py              # Unit tests for display formatting
├── run.py                           # Entry point (CLI arg parsing, wires components)
├── pyproject.toml                   # Project metadata, dependencies, scripts
└── docs/
    └── (existing docs)
```

**Design rationale:**
- `bpf_program.c` is a standalone C file loaded as a string by BCC — no build step needed.
- `capture.py` owns all BPF/kernel interaction. Everything else is pure Python and independently testable.
- `aggregator.py` is a pure function: takes raw map snapshots, returns structured stats. No I/O.
- `player_map.py` isolates Redis dependency — can be disabled entirely.
- `display.py` is pure string formatting — trivially testable.

---

## Chunk 1: Project Skeleton + Aggregation Logic

### Task 1: Project skeleton and pyproject.toml

**Files:**
- Create: `pyproject.toml`
- Create: `src/__init__.py`
- Create: `tests/__init__.py`
- Create: `run.py` (stub)

- [ ] **Step 1: Create pyproject.toml**

```toml
[project]
name = "ql-packet-fragmentation"
version = "0.1.0"
description = "eBPF-based packet fragmentation analysis for Quake Live"
requires-python = ">=3.8"
dependencies = [
    "redis>=4.0.0",
    "pyroute2>=0.7.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
]

[project.scripts]
ql-capture = "run:main"
```

- [ ] **Step 2: Create package init files**

```python
# src/__init__.py
# empty
```

```python
# tests/__init__.py
# empty
```

- [ ] **Step 3: Create run.py stub**

```python
#!/usr/bin/env python3
"""Entry point for QL packet fragmentation capture."""

import argparse
import sys


def parse_args():
    parser = argparse.ArgumentParser(
        description="Capture and analyze QL server packet fragmentation via eBPF"
    )
    parser.add_argument(
        "--interface", "-i",
        default="eth0",
        help="Network interface to attach eBPF program to (default: eth0)",
    )
    parser.add_argument(
        "--ports",
        default="27960-27963",
        help="QL server port range (default: 27960-27963)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=10,
        help="Aggregation interval in seconds (default: 10)",
    )
    parser.add_argument(
        "--redis-url",
        default=None,
        help="Redis URL for player mapping (optional, e.g. redis://localhost:6379/0)",
    )
    parser.add_argument(
        "--rate-setting",
        choices=["25k", "99k"],
        default=None,
        help="Label for the current rate setting (for display only)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    print(f"QL Packet Fragmentation Capture")
    print(f"Interface: {args.interface}")
    print(f"Ports: {args.ports}")
    print(f"Interval: {args.interval}s")
    print(f"Redis: {args.redis_url or 'disabled'}")
    print(f"Rate: {args.rate_setting or 'unlabeled'}")
    print("(not yet implemented)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Verify skeleton runs**

Run: `python3 run.py --help`
Expected: Help text with all flags listed.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/__init__.py tests/__init__.py run.py
git commit -m "feat: project skeleton with CLI arg parsing"
```

---

### Task 2: Aggregation logic — data structures and bucket computation

**Files:**
- Create: `src/aggregator.py`
- Create: `tests/test_aggregator.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_aggregator.py
import pytest
from src.aggregator import aggregate_packets, FRAG_THRESHOLD

# Bucket boundaries: [0, 500), [500, 1000), [1000, 1472], (1472, +inf)


class TestAggregatePackets:
    def test_empty_input(self):
        result = aggregate_packets({})
        assert result["total_packets"] == 0
        assert result["fragmented_packets"] == 0
        assert result["avg_size"] == 0.0
        assert result["max_size"] == 0
        assert result["buckets"] == [0, 0, 0, 0]

    def test_single_small_packet(self):
        # ip_data: {dest_ip: [(size, count), ...]}
        ip_data = {"10.0.0.1": [(400, 5)]}
        result = aggregate_packets(ip_data)
        assert result["total_packets"] == 5
        assert result["fragmented_packets"] == 0
        assert result["avg_size"] == 400.0
        assert result["max_size"] == 400
        assert result["buckets"] == [5, 0, 0, 0]

    def test_fragmented_packets(self):
        ip_data = {"10.0.0.1": [(1500, 3)]}
        result = aggregate_packets(ip_data)
        assert result["total_packets"] == 3
        assert result["fragmented_packets"] == 3
        assert result["avg_size"] == 1500.0
        assert result["max_size"] == 1500
        assert result["buckets"] == [0, 0, 0, 3]

    def test_boundary_exactly_1472(self):
        ip_data = {"10.0.0.1": [(FRAG_THRESHOLD, 1)]}
        result = aggregate_packets(ip_data)
        # Exactly 1472 is NOT fragmented (fits in one MTU)
        assert result["fragmented_packets"] == 0
        assert result["buckets"] == [0, 0, 1, 0]

    def test_boundary_1473(self):
        ip_data = {"10.0.0.1": [(1473, 1)]}
        result = aggregate_packets(ip_data)
        assert result["fragmented_packets"] == 1
        assert result["buckets"] == [0, 0, 0, 1]

    def test_multiple_ips_mixed(self):
        ip_data = {
            "10.0.0.1": [(200, 10), (800, 5)],
            "10.0.0.2": [(1200, 3), (1500, 2)],
        }
        result = aggregate_packets(ip_data)
        assert result["total_packets"] == 20
        assert result["fragmented_packets"] == 2
        # avg = (200*10 + 800*5 + 1200*3 + 1500*2) / 20 = (2000+4000+3600+3000)/20 = 630
        assert result["avg_size"] == 630.0
        assert result["max_size"] == 1500
        assert result["buckets"] == [10, 5, 3, 2]

    def test_per_ip_breakdown(self):
        ip_data = {
            "10.0.0.1": [(400, 5)],
            "10.0.0.2": [(1500, 3)],
        }
        result = aggregate_packets(ip_data)
        per_ip = result["per_ip"]
        assert per_ip["10.0.0.1"]["total_packets"] == 5
        assert per_ip["10.0.0.1"]["fragmented_packets"] == 0
        assert per_ip["10.0.0.2"]["total_packets"] == 3
        assert per_ip["10.0.0.2"]["fragmented_packets"] == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_aggregator.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.aggregator'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/aggregator.py
"""Pure aggregation logic for packet size data from BPF maps."""

from typing import Dict, List, Tuple

# UDP payload threshold before IP fragmentation occurs (standard 1500 MTU)
FRAG_THRESHOLD = 1472

# Bucket boundaries (upper bound exclusive): [0,500), [500,1000), [1000,1472], (1472,+inf)
BUCKET_BOUNDS = [500, 1000, FRAG_THRESHOLD]


def _bucket_index(size: int) -> int:
    """Return bucket index for a given packet size.

    Buckets: [0,500), [500,1000), [1000,1472], (1472,+inf)
    """
    if size > FRAG_THRESHOLD:
        return 3
    for i, bound in enumerate(BUCKET_BOUNDS):
        if size < bound:
            return i
    return 2  # [1000, 1472] — fits in MTU


IpData = Dict[str, List[Tuple[int, int]]]  # {ip: [(size, count), ...]}


def aggregate_packets(ip_data: IpData) -> dict:
    """Aggregate per-IP packet size data into summary stats.

    Args:
        ip_data: Dict mapping dest IP to list of (packet_size, count) tuples.
                 This is the format read from BPF maps.

    Returns:
        Dict with keys: total_packets, fragmented_packets, avg_size, max_size,
        buckets (list of 4 counts), per_ip (dict of per-IP stats).
    """
    total_packets = 0
    fragmented_packets = 0
    size_sum = 0
    max_size = 0
    buckets = [0, 0, 0, 0]
    per_ip = {}

    for ip, entries in ip_data.items():
        ip_total = 0
        ip_frag = 0
        ip_size_sum = 0
        ip_max = 0

        for size, count in entries:
            ip_total += count
            ip_size_sum += size * count
            if size > ip_max:
                ip_max = size
            if size > FRAG_THRESHOLD:
                ip_frag += count
            buckets[_bucket_index(size)] += count

        per_ip[ip] = {
            "total_packets": ip_total,
            "fragmented_packets": ip_frag,
            "avg_size": ip_size_sum / ip_total if ip_total else 0.0,
            "max_size": ip_max,
        }

        total_packets += ip_total
        fragmented_packets += ip_frag
        size_sum += ip_size_sum
        if ip_max > max_size:
            max_size = ip_max

    return {
        "total_packets": total_packets,
        "fragmented_packets": fragmented_packets,
        "avg_size": size_sum / total_packets if total_packets else 0.0,
        "max_size": max_size,
        "buckets": buckets,
        "per_ip": per_ip,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_aggregator.py -v`
Expected: All 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aggregator.py tests/test_aggregator.py
git commit -m "feat: aggregation logic with bucket computation and per-IP breakdown"
```

---

### Task 3: Display formatting

**Files:**
- Create: `src/display.py`
- Create: `tests/test_display.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_display.py
from src.display import format_stats, format_histogram_bar


class TestFormatHistogramBar:
    def test_zero_total(self):
        assert format_histogram_bar(0, 0) == ""

    def test_full_bar(self):
        bar = format_histogram_bar(100, 100)
        assert len(bar) == 40  # default width
        assert bar == "#" * 40

    def test_half_bar(self):
        bar = format_histogram_bar(50, 100)
        assert len(bar) == 20
        assert bar == "#" * 20

    def test_custom_width(self):
        bar = format_histogram_bar(25, 100, width=20)
        assert len(bar) == 5


class TestFormatStats:
    def test_basic_output_contains_key_info(self):
        stats = {
            "total_packets": 100,
            "fragmented_packets": 10,
            "avg_size": 800.5,
            "max_size": 1600,
            "buckets": [40, 30, 20, 10],
            "per_ip": {},
        }
        output = format_stats(stats)
        assert "100" in output
        assert "10.0%" in output  # frag percentage
        assert "800" in output
        assert "1600" in output

    def test_zero_packets(self):
        stats = {
            "total_packets": 0,
            "fragmented_packets": 0,
            "avg_size": 0.0,
            "max_size": 0,
            "buckets": [0, 0, 0, 0],
            "per_ip": {},
        }
        output = format_stats(stats)
        assert "0" in output
        assert "No packets" in output

    def test_per_player_included(self):
        stats = {
            "total_packets": 10,
            "fragmented_packets": 2,
            "avg_size": 1000.0,
            "max_size": 1500,
            "buckets": [0, 5, 3, 2],
            "per_ip": {
                "10.0.0.1": {
                    "total_packets": 10,
                    "fragmented_packets": 2,
                    "avg_size": 1000.0,
                    "max_size": 1500,
                },
            },
        }
        player_map = {"10.0.0.1": ("76561197960700239", "testplayer")}
        output = format_stats(stats, player_map=player_map)
        assert "testplayer" in output
        assert "20.0%" in output  # per-player frag %
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_display.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/display.py
"""Terminal display formatting for packet stats."""

from typing import Dict, Optional, Tuple
import time

BUCKET_LABELS = [
    "   0 - 499 ",
    " 500 - 999 ",
    "1000 - 1472",
    "1472+  FRAG",
]


def format_histogram_bar(count: int, total: int, width: int = 40) -> str:
    """Return a '#'-bar proportional to count/total."""
    if total == 0:
        return ""
    bar_len = int((count / total) * width)
    return "#" * bar_len


def format_stats(
    stats: dict,
    player_map: Optional[Dict[str, Tuple[str, str]]] = None,
    rate_setting: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> str:
    """Format aggregated stats for terminal output.

    Args:
        stats: Output from aggregate_packets().
        player_map: Optional {ip: (steamid, name)} for per-player display.
        rate_setting: Optional rate label (e.g. "99k").
        timestamp: Optional timestamp string (defaults to current time).
    """
    ts = timestamp or time.strftime('%H:%M:%S')
    total = stats["total_packets"]

    if total == 0:
        return f"[{ts}] No packets captured in this interval."

    frag = stats["fragmented_packets"]
    frag_pct = (frag / total) * 100

    lines = []
    header = f"[{ts}]"
    if rate_setting:
        header += f" rate={rate_setting}"
    header += f"  pkts={total}  frag={frag} ({frag_pct:.1f}%)  avg={stats['avg_size']:.0f}B  max={stats['max_size']}B"
    lines.append(header)

    # Histogram
    lines.append("  Size Range     Count   Pct   Distribution")
    lines.append("  " + "-" * 60)
    for i, label in enumerate(BUCKET_LABELS):
        count = stats["buckets"][i]
        pct = (count / total) * 100 if total else 0
        bar = format_histogram_bar(count, total)
        lines.append(f"  {label}  {count:>6}  {pct:>5.1f}%  {bar}")

    # Per-player breakdown
    if stats.get("per_ip") and player_map:
        lines.append("")
        lines.append("  Per-Player Breakdown:")
        lines.append(f"  {'Player':<20} {'Pkts':>6} {'Frag':>6} {'Frag%':>7} {'Avg':>6} {'Max':>6}")
        lines.append("  " + "-" * 60)
        for ip, ip_stats in sorted(stats["per_ip"].items()):
            if ip in player_map:
                _, name = player_map[ip]
            else:
                name = ip
            ip_total = ip_stats["total_packets"]
            ip_frag = ip_stats["fragmented_packets"]
            ip_frag_pct = (ip_frag / ip_total) * 100 if ip_total else 0
            lines.append(
                f"  {name:<20} {ip_total:>6} {ip_frag:>6} {ip_frag_pct:>6.1f}% "
                f"{ip_stats['avg_size']:>5.0f}B {ip_stats['max_size']:>5}B"
            )

    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_display.py -v`
Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/display.py tests/test_display.py
git commit -m "feat: terminal display formatting with histogram bars and per-player breakdown"
```

---

## Chunk 2: Player Mapping + eBPF Capture

### Task 4: Redis player mapping

**Files:**
- Create: `src/player_map.py`
- Create: `tests/test_player_map.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_player_map.py
from unittest.mock import MagicMock, patch
from src.player_map import build_reverse_index, PlayerMapper


class TestBuildReverseIndex:
    def test_single_player_single_ip(self):
        mock_redis = MagicMock()
        mock_redis.scan_iter.return_value = [b"minqlx:players:12345:ips"]
        mock_redis.smembers.return_value = {b"10.0.0.1"}
        mock_redis.lindex.return_value = b"TestPlayer"

        result = build_reverse_index(mock_redis)
        assert result == {"10.0.0.1": ("12345", "TestPlayer")}

    def test_player_multiple_ips(self):
        mock_redis = MagicMock()
        mock_redis.scan_iter.return_value = [b"minqlx:players:12345:ips"]
        mock_redis.smembers.return_value = {b"10.0.0.1", b"10.0.0.2"}
        mock_redis.lindex.return_value = b"TestPlayer"

        result = build_reverse_index(mock_redis)
        assert result["10.0.0.1"] == ("12345", "TestPlayer")
        assert result["10.0.0.2"] == ("12345", "TestPlayer")

    def test_no_players(self):
        mock_redis = MagicMock()
        mock_redis.scan_iter.return_value = []

        result = build_reverse_index(mock_redis)
        assert result == {}

    def test_player_with_no_name(self):
        mock_redis = MagicMock()
        mock_redis.scan_iter.return_value = [b"minqlx:players:12345:ips"]
        mock_redis.smembers.return_value = {b"10.0.0.1"}
        mock_redis.lindex.return_value = None

        result = build_reverse_index(mock_redis)
        assert result == {"10.0.0.1": ("12345", "unknown")}


class TestPlayerMapper:
    def test_disabled_when_no_url(self):
        mapper = PlayerMapper(redis_url=None)
        assert mapper.get_map() == {}

    def test_refresh_calls_build(self):
        with patch("src.player_map.build_reverse_index") as mock_build:
            mock_build.return_value = {"10.0.0.1": ("123", "Player")}
            with patch("src.player_map.redis.from_url"):
                mapper = PlayerMapper(redis_url="redis://localhost:6379/0")
                mapper.refresh()
                assert mapper.get_map() == {"10.0.0.1": ("123", "Player")}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_player_map.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/player_map.py
"""Redis-based player IP mapping using minqlx data."""

import re
import time
from typing import Dict, Optional, Tuple

import redis

# Refresh interval for the reverse index
REFRESH_INTERVAL = 60

PlayerMap = Dict[str, Tuple[str, str]]  # {ip: (steamid, name)}

STEAMID_PATTERN = re.compile(rb"minqlx:players:(\d+):ips")


def build_reverse_index(r: redis.Redis) -> PlayerMap:
    """Scan minqlx Redis keys and build {ip: (steamid, name)} mapping."""
    result: PlayerMap = {}

    for key in r.scan_iter(match=b"minqlx:players:*:ips"):
        m = STEAMID_PATTERN.match(key)
        if not m:
            continue
        steamid = m.group(1).decode()
        name_bytes = r.lindex(b"minqlx:players:" + m.group(1), 0)
        name = name_bytes.decode() if name_bytes else "unknown"
        ips = r.smembers(key)
        for ip_bytes in ips:
            result[ip_bytes.decode()] = (steamid, name)

    return result


class PlayerMapper:
    """Manages periodic refresh of the IP → player reverse index."""

    def __init__(self, redis_url: Optional[str] = None):
        self._map: PlayerMap = {}
        self._redis: Optional[redis.Redis] = None
        self._last_refresh: float = 0

        if redis_url:
            self._redis = redis.from_url(redis_url)

    def refresh(self) -> None:
        """Rebuild the reverse index from Redis."""
        if self._redis is None:
            return
        self._map = build_reverse_index(self._redis)
        self._last_refresh = time.monotonic()

    def maybe_refresh(self) -> None:
        """Refresh if REFRESH_INTERVAL has elapsed."""
        if self._redis is None:
            return
        if time.monotonic() - self._last_refresh >= REFRESH_INTERVAL:
            self.refresh()

    def get_map(self) -> PlayerMap:
        """Return current IP → (steamid, name) mapping."""
        return self._map
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_player_map.py -v`
Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/player_map.py tests/test_player_map.py
git commit -m "feat: Redis player mapping with periodic refresh"
```

---

### Task 5: eBPF C program

**Files:**
- Create: `src/bpf_program.c`

The eBPF program is loaded as a string by BCC at runtime — no separate compilation step. It attaches to TC egress and records per-destination-IP packet size histograms into a BPF hash map.

- [ ] **Step 1: Write the BPF C program**

```c
/* src/bpf_program.c
 *
 * eBPF TC egress classifier for Quake Live packet size capture.
 * Filters outbound UDP packets on configurable port range,
 * records (dest_ip, packet_size) into a BPF hash map.
 *
 * Loaded by BCC at runtime — port range injected via cflags (-DPORT_MIN, -DPORT_MAX).
 */

#include <uapi/linux/bpf.h>
#include <uapi/linux/if_ether.h>
#include <uapi/linux/ip.h>
#include <uapi/linux/udp.h>
#include <uapi/linux/pkt_cls.h>

/* PORT_MIN and PORT_MAX are injected by Python via BCC cflags:
 *   -DPORT_MIN=27960 -DPORT_MAX=27963
 */

struct packet_key {
    u32 dest_ip;
    u32 size_bucket;  /* UDP payload size, bucketed in userspace */
};

/* Map: (dest_ip, udp_payload_size) -> packet_count */
BPF_HASH(packet_counts, struct packet_key, u64, 16384);

int classify(struct __sk_buff *skb) {
    void *data = (void *)(long)skb->data;
    void *data_end = (void *)(long)skb->data_end;

    /* Parse Ethernet header */
    struct ethhdr *eth = data;
    if ((void *)(eth + 1) > data_end)
        return TC_ACT_OK;
    if (eth->h_proto != __constant_htons(ETH_P_IP))
        return TC_ACT_OK;

    /* Parse IP header */
    struct iphdr *ip = (void *)(eth + 1);
    if ((void *)(ip + 1) > data_end)
        return TC_ACT_OK;
    if (ip->protocol != IPPROTO_UDP)
        return TC_ACT_OK;

    /* Parse UDP header (account for variable IP header length) */
    if (ip->ihl < 5)
        return TC_ACT_OK;
    struct udphdr *udp = (void *)ip + (ip->ihl * 4);
    if ((void *)(udp + 1) > data_end)
        return TC_ACT_OK;

    u16 sport = bpf_ntohs(udp->source);
    if (sport < PORT_MIN || sport > PORT_MAX)
        return TC_ACT_OK;

    /* UDP payload size = total UDP length - 8 byte header */
    u16 udp_len = bpf_ntohs(udp->len);
    if (udp_len < 8)
        return TC_ACT_OK;
    u16 udp_payload = udp_len - 8;

    struct packet_key key = {};
    key.dest_ip = ip->daddr;
    key.size_bucket = udp_payload;

    u64 *count = packet_counts.lookup_or_try_init(&key, &(u64){0});
    if (count) {
        __sync_fetch_and_add(count, 1);
    }

    return TC_ACT_OK;  /* Don't interfere with traffic */
}
```

- [ ] **Step 2: Verify file is syntactically plausible**

Run: `python3 -c "open('src/bpf_program.c').read(); print('BPF C source OK')"`
Expected: "BPF C source OK"

- [ ] **Step 3: Commit**

```bash
git add src/bpf_program.c
git commit -m "feat: eBPF TC egress classifier for QL UDP packet capture"
```

---

### Task 6: Capture module — BCC loader and main loop

**Files:**
- Create: `src/capture.py`

This module loads the BPF program, attaches it to TC egress, and provides functions to read+clear the map.

- [ ] **Step 1: Write capture.py**

```python
# src/capture.py
"""BCC-based eBPF loader and map reader for packet capture."""

import socket
import struct
from pathlib import Path
from typing import Dict, List, Tuple

from bcc import BPF
from pyroute2 import IPRoute

BPF_SOURCE = Path(__file__).parent / "bpf_program.c"

IpData = Dict[str, List[Tuple[int, int]]]  # {ip_str: [(size, count), ...]}


def _int_to_ip(addr: int) -> str:
    """Convert a raw u32 from BPF map to dotted IP string.

    BPF stores ip->daddr in network byte order. BCC reads it as a
    native-endian ctypes u32, so we use native pack format.
    """
    return socket.inet_ntoa(struct.pack("I", addr))


class PacketCapture:
    """Manages eBPF program lifecycle and map reading."""

    def __init__(self, interface: str, port_min: int, port_max: int):
        self.interface = interface
        self.port_min = port_min
        self.port_max = port_max
        self._bpf = None
        self._ipr = None
        self._ifindex = None

    def start(self) -> None:
        """Load BPF program and attach to TC egress via pyroute2."""
        source = BPF_SOURCE.read_text()

        self._bpf = BPF(
            text=source,
            cflags=[f"-DPORT_MIN={self.port_min}", f"-DPORT_MAX={self.port_max}"],
        )
        fn = self._bpf.load_func("classify", BPF.SCHED_CLS)

        # Attach to TC egress using pyroute2
        self._ipr = IPRoute()
        self._ifindex = self._ipr.link_lookup(ifname=self.interface)[0]

        try:
            self._ipr.tc("add", "clsact", self._ifindex)
        except Exception:
            pass  # clsact qdisc may already exist

        self._ipr.tc(
            "add-filter", "bpf", self._ifindex,
            fd=fn.fd, name=fn.name,
            parent=0xFFF0FFF3,  # TC_H_CLSACT | TC_H_MIN_EGRESS
            prio=1,
            classid=1,
            direct_action=True,
        )

    def read_and_clear(self) -> IpData:
        """Read all entries from the packet_counts map and clear it.

        Returns:
            Dict mapping dest IP string to list of (udp_payload_size, count) tuples.
        """
        if self._bpf is None:
            return {}

        table = self._bpf["packet_counts"]
        ip_data: IpData = {}

        for key, val in table.items():
            ip = _int_to_ip(key.dest_ip)
            size = key.size_bucket
            count = val.value
            if ip not in ip_data:
                ip_data[ip] = []
            ip_data[ip].append((size, count))

        table.clear()
        return ip_data

    def stop(self) -> None:
        """Detach TC filter and clean up."""
        if self._ipr and self._ifindex:
            try:
                self._ipr.tc("del", "clsact", self._ifindex)
            except Exception:
                pass
            self._ipr.close()
            self._ipr = None
        if self._bpf is not None:
            self._bpf.cleanup()
            self._bpf = None
```

- [ ] **Step 2: Verify import structure**

Run: `python3 -c "import ast; ast.parse(open('src/capture.py').read()); print('Syntax OK')"`
Expected: "Syntax OK"

- [ ] **Step 3: Commit**

```bash
git add src/capture.py
git commit -m "feat: BCC loader for eBPF TC egress packet capture"
```

---

## Chunk 3: Integration and Entry Point

### Task 7: Wire everything together in run.py

**Files:**
- Modify: `run.py`

- [ ] **Step 1: Update run.py with full main loop**

```python
#!/usr/bin/env python3
"""Entry point for QL packet fragmentation capture."""

import argparse
import signal
import sys
import time

from src.aggregator import aggregate_packets
from src.capture import PacketCapture
from src.display import format_stats
from src.player_map import PlayerMapper


def parse_args():
    parser = argparse.ArgumentParser(
        description="Capture and analyze QL server packet fragmentation via eBPF"
    )
    parser.add_argument(
        "--interface", "-i",
        default="eth0",
        help="Network interface to attach eBPF program to (default: eth0)",
    )
    parser.add_argument(
        "--ports",
        default="27960-27963",
        help="QL server port range (default: 27960-27963)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=10,
        help="Aggregation interval in seconds (default: 10)",
    )
    parser.add_argument(
        "--redis-url",
        default=None,
        help="Redis URL for player mapping (optional, e.g. redis://localhost:6379/0)",
    )
    parser.add_argument(
        "--rate-setting",
        choices=["25k", "99k"],
        default=None,
        help="Label for the current rate setting (for display only)",
    )
    return parser.parse_args()


def parse_port_range(port_str: str):
    """Parse 'min-max' into (min, max) ints."""
    try:
        parts = port_str.split("-")
        if len(parts) == 2:
            return int(parts[0]), int(parts[1])
        port = int(parts[0])
        return port, port
    except ValueError:
        print(f"Error: invalid port range '{port_str}' (expected e.g. 27960-27963)", file=sys.stderr)
        sys.exit(1)


running = True


def main():
    global running
    args = parse_args()

    port_min, port_max = parse_port_range(args.ports)

    print(f"QL Packet Fragmentation Capture (eBPF)")
    print(f"Interface: {args.interface}  Ports: {port_min}-{port_max}  Interval: {args.interval}s")
    if args.rate_setting:
        print(f"Rate setting: {args.rate_setting}")
    print()

    # Set up signal handler for clean shutdown
    def handle_signal(signum, frame):
        global running
        running = False

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # Initialize components
    capture = PacketCapture(args.interface, port_min, port_max)
    player_mapper = PlayerMapper(redis_url=args.redis_url)

    try:
        capture.start()
        print("eBPF program attached. Capturing...\n")
        player_mapper.refresh()

        while running:
            time.sleep(args.interval)

            player_mapper.maybe_refresh()
            ip_data = capture.read_and_clear()
            stats = aggregate_packets(ip_data)
            output = format_stats(
                stats,
                player_map=player_mapper.get_map(),
                rate_setting=args.rate_setting,
            )
            print(output)
            print()

    finally:
        capture.stop()
        print("\nCapture stopped.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('run.py').read()); print('Syntax OK')"`
Expected: "Syntax OK"

- [ ] **Step 3: Commit**

```bash
git add run.py
git commit -m "feat: wire up main loop — eBPF capture, aggregation, display"
```

---

### Task 8: Integration test on live system

**Files:** None (manual verification)

This task validates the full pipeline on the actual QL server. It requires root and a running QL server.

- [ ] **Step 1: Verify BCC is installed**

Run: `python3 -c "from bcc import BPF; print('BCC version:', BPF.kernel_struct_has_field)"`
Expected: No ImportError.

- [ ] **Step 2: Run capture against loopback for smoke test**

Run: `sudo python3 run.py --interface lo --ports 27960-27960 --interval 5`
Then in another terminal (note: source port must be in QL range since BPF filters on sport):
`echo test | nc -u -p 27960 127.0.0.1 12345`
Expected: Output shows at least 1 packet in bucket [0-500).

- [ ] **Step 3: Run against real interface with QL traffic**

Run: `sudo python3 run.py --interface eth0 --ports 27960-27963 --interval 10 --rate-setting 99k`
Expected: Histogram output with packets, non-zero fragmentation at 99k rate during active gameplay.

- [ ] **Step 4: Test with Redis player mapping**

Run: `sudo python3 run.py -i eth0 --ports 27960-27963 --interval 10 --redis-url redis://localhost:6379/0 --rate-setting 99k`
Expected: Per-player breakdown shows player names from minqlx Redis.

- [ ] **Step 5: Commit any fixes from integration testing**

```bash
git add -u
git commit -m "fix: adjustments from integration testing"
```

---

## Notes

### TC Attach via pyroute2

The `capture.py` module uses `pyroute2` (not BCC's `attach_func`) for TC egress attachment. This is the reliable, version-independent approach. The `clsact` qdisc is added to the interface, then a BPF filter is attached to the egress parent (`0xFFF0FFF3` = `TC_H_CLSACT | TC_H_MIN_EGRESS`). The `stop()` method removes the `clsact` qdisc (which also removes the filter).

### Kernel Requirements

Minimum kernel config needed:
```
CONFIG_BPF=y
CONFIG_BPF_SYSCALL=y
CONFIG_NET_CLS_BPF=m  (or =y)
CONFIG_NET_ACT_BPF=m  (or =y)
CONFIG_BPF_JIT=y
```
