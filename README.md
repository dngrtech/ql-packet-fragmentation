# QL Packet Fragmentation Analysis

Measures UDP packet fragmentation on Quake Live servers using eBPF to determine the real-world impact of the `rate` engine setting.

## Background

Quake Live's `rate` cvar has two practical settings:

- **25k** — avoids IP fragmentation but causes engine choke (dropped game state) during intense fights
- **99k (LAN)** — sends full game state but routinely produces packets exceeding the 1472-byte MTU payload limit, triggering IP fragmentation

This tool captures outbound server traffic via an eBPF program on TC egress,
aggregates packet size distributions, and correlates them to individual
players via the Redis status payload written by the bundled
[`serverchecker` plugin](minqlx-plugins/serverchecker.py). It can also write
interval summaries to InfluxDB 2.x.

## Requirements

- Linux with BPF support (kernel version frozen)
- Python 3.8+
- [BCC](https://github.com/iovisor/bcc) (bpfcc-tools / python3-bcc)
- Kernel headers (`linux-headers-$(uname -r)`) — required for BCC to compile eBPF programs at runtime
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
  --rate-setting '27960:99k,27961:25k,27962:25k,27963:99k' \
  --host-tag texas \
  --redis-url redis://localhost:6379/3 \
  --influx-url http://127.0.0.1:8086 \
  --influx-org ql \
  --influx-bucket ql_packet_fragmentation \
  --influx-token-file /opt/ql-packet-fragmentation/secrets/influxdb-token
```

Notes:

- `--ports` accepts a single QL port or a range.
- In multi-port mode, the collector prints one report per server port.
- `--rate-setting` accepts a single value (`99k`) applied to all ports, or a
  per-port mapping (`27960:99k,27961:25k`). Servers on the same host often
  differ — check `sv_lanForceRate` in each instance's process args.
- When `--redis-url` is set for a range, its host/port/credentials are reused
  and the Redis DB index is derived from each server port (`27960 -> db1`,
  `27961 -> db2`, `27962 -> db3`, and so on).
- InfluxDB writes are optional. If any of `--influx-url`, `--influx-org`,
  `--influx-bucket`, or a token/token file are omitted, the collector runs in
  terminal-only mode.
- When multiple qlds hosts write into one InfluxDB bucket, set `--host-tag`
  or `HOST_TAG` so points remain attributable to a specific machine.

## Debian 12 Deployment

For a one-shot Debian 12 deployment on a qlds host, use
[`scripts/deploy-debian12.sh`](scripts/deploy-debian12.sh). Example:

```bash
curl -fsSL https://raw.githubusercontent.com/dngrtech/ql-packet-fragmentation/main/scripts/deploy-debian12.sh | sudo env REPO_GIT_URL=https://github.com/dngrtech/ql-packet-fragmentation.git PORTS=27960-27962 INTERFACE=enp1s0 REDIS_URL=redis://localhost:6379/3 HOST_TAG=texas bash
```

Optional features are controlled by environment variables:

- `INSTALL_SERVERCHECKER=1` plus `QL_COMMON_PLUGIN_DIR` and/or `QL_INSTANCE_PLUGIN_DIR_TEMPLATE`
- `INSTALL_INFLUXDB=1` plus optional `INFLUX_ALLOWLIST_IP`
- `REPO_REF=<tag-or-commit>` if you want to deploy a specific revision

The full manual process remains documented in
[`docs/deployment-guide.md`](docs/deployment-guide.md).

## InfluxDB Measurements

When InfluxDB is enabled, each interval writes:

- `packet_stats`: one point per QL server port with total packets,
  fragmented packets, average size, max size, and histogram bucket counts
- `player_packets`: one point per mapped player per QL server port with
  fragmented packet counts and average/max packet size

InfluxDB tags include:

- `host`
- `server_port`
- `rate_setting` per-port when provided
- `steam_id` and `player_name` for `player_packets`

Deployment details for the current containerized setup are in
[`docs/influxdb-deployment.md`](docs/influxdb-deployment.md).

For a full end-to-end deployment on another host, use
[`docs/deployment-guide.md`](docs/deployment-guide.md).

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

## License

MIT
