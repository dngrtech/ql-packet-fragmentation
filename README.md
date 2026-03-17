# QL Packet Fragmentation Analysis

Measures UDP packet fragmentation on Quake Live servers using eBPF to determine the real-world impact of the `rate` engine setting.

## Background

Quake Live's `rate` cvar has two practical settings:

- **25k** — avoids IP fragmentation but causes engine choke (dropped game state) during intense fights
- **99k (LAN)** — sends full game state but routinely produces packets exceeding the 1472-byte MTU payload limit, triggering IP fragmentation

This tool captures outbound server traffic via an eBPF program on TC egress, aggregates packet size distributions, and correlates them to individual players via minqlx Redis data.

## Requirements

- Linux with BPF support (kernel version frozen)
- Python 3.8+
- [BCC](https://github.com/iovisor/bcc) (bpfcc-tools / python3-bcc)
- pyroute2, redis-py
- Root or `CAP_BPF` + `CAP_NET_ADMIN`

## Usage

```bash
sudo python3 run.py \
  --interface eth0 \
  --ports 27960-27963 \
  --interval 10 \
  --rate-setting 99k \
  --redis-url redis://localhost:6379/0
```

Output (every 10 seconds):

```
[21:30:10] rate=99k  pkts=312  frag=47 (15.1%)  avg=1138B  max=2104B
  Size Range     Count     Pct   Distribution
  ------------------------------------------------------------
     0 - 499       89   28.5%  ###########
   500 - 999       94   30.1%  ############
  1000 - 1472      82   26.3%  ##########
  1472+  FRAG      47   15.1%  ######
```

## Project Status

- [x] Phase 1 — eBPF capture + terminal output
- [ ] Phase 2 — InfluxDB persistence + systemd service
- [ ] Phase 3 — Grafana dashboards + publication charts
- [ ] Phase 4 — Controlled 25k vs 99k experiments

## License

MIT
