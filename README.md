# QL Packet Fragmentation Analysis

Measures UDP packet fragmentation on Quake Live servers using eBPF to determine the real-world impact of the `rate` engine setting.

## Background

Quake Live's `rate` cvar has two practical settings:

- **25k** — avoids IP fragmentation but causes engine choke (dropped game state) during intense fights
- **99k (LAN)** — sends full game state but routinely produces packets exceeding the 1472-byte MTU payload limit, triggering IP fragmentation

This tool captures outbound server traffic via an eBPF program on TC egress,
aggregates packet size distributions, and correlates them to individual
players via the Redis status payload written by the bundled
[`serverchecker` plugin](minqlx-plugins/serverchecker.py).

## Requirements

- Linux with BPF support (kernel version frozen)
- Python 3.8+
- [BCC](https://github.com/iovisor/bcc) (bpfcc-tools / python3-bcc)
- pyroute2, redis-py
- Root or `CAP_BPF` + `CAP_NET_ADMIN`

## Player Mapping Prerequisite

Per-player output depends on the `serverchecker` minqlx plugin in this repo.
It must be deployed to the server so Redis key `minqlx:server_status:<port>`
includes each player's `udp_port`. That field is derived from minqlx's raw
`"ip"` player field and matches the UDP destination port seen by eBPF.

Example Redis DB mapping:

- QL server `27962` -> Redis DB `3`

Verify it before running capture:

```bash
redis-cli -n 3 get minqlx:server_status:27962 | python3 -m json.tool
```

## Usage

```bash
sudo python3 run.py \
  --interface enp1s0 \
  --ports 27960-27963 \
  --interval 10 \
  --rate-setting 99k \
  --redis-url redis://localhost:6379/3
```

Notes:

- `--ports` accepts a single QL port or a range.
- In multi-port mode, the collector prints one report per server port.
- When `--redis-url` is set for a range, its host/port/credentials are reused
  and the Redis DB index is derived from each server port (`27960 -> db1`,
  `27961 -> db2`, `27962 -> db3`, and so on).

Output (every 10 seconds):

```
[21:30:10] rate=99k  pkts=312  frag=47 (15.1%)  avg=1138B  max=2104B
  Size Range     Count     Pct   Distribution
  ------------------------------------------------------------
     0 - 499       89   28.5%  ###########
  500 - 999       94   30.1%  ############
  1000 - 1472      82   26.3%  ##########
  1472+  FRAG      47   15.1%  ######

  Per-Player Breakdown:
  Player                           SteamID   Pkts   Frag   Frag%    Avg    Max
  ------------------------------------------------------------------------
  rage                     76561199795317792    102     21   20.6%  1187B  2104B
```

## Project Status

- [x] Phase 1 — eBPF capture + terminal output
  - TC egress capture on the real egress interface (`enp1s0` on the current host)
  - Per-player correlation via `minqlx:server_status:<port>` -> `udp_port`
- [ ] Phase 2 — InfluxDB persistence + systemd service
- [ ] Phase 3 — Grafana dashboards + publication charts
- [ ] Phase 4 — Controlled 25k vs 99k experiments

## License

MIT
