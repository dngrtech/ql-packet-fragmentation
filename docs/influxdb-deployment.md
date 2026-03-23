# InfluxDB Deployment

This project writes interval summaries to InfluxDB 2.x when the collector is
started with the `--influx-*` flags.

For the full host deployment flow, including package install, plugin rollout,
systemd, and verification, see [`docs/deployment-guide.md`](deployment-guide.md).

## Container Model

The current deployment uses a Docker container on the Quake Live host with:

- host networking
- persistent bind mounts under `/opt/influxdb`
- the InfluxDB HTTP API bound on port `8086`

Host networking is intentional. It keeps port `8086` under the normal host
`iptables` INPUT chain instead of Docker's forwarded-port rules.

## Persistent Paths

- `/opt/influxdb/data`
- `/opt/influxdb/config`
- `/opt/influxdb/influxdb.env`
- `/opt/influxdb/credentials.txt`
- `/opt/ql-packet-fragmentation/secrets/influxdb-token`

## Access Control

InfluxDB listens on `0.0.0.0:8086`, but host firewall rules restrict external
access.

Current allowlist:

- `154.20.139.212/32` -> TCP `8086`

The collector itself writes to `http://127.0.0.1:8086`, so local ingestion does
not depend on external firewall access.

## Collector Flags

Example:

```bash
sudo /opt/ql-packet-fragmentation/.venv/bin/python /opt/ql-packet-fragmentation/run.py \
  --interface enp1s0 \
  --ports 27960-27963 \
  --interval 10 \
  --rate-setting 99k \
  --host-tag texas \
  --redis-url redis://localhost:6379/3 \
  --influx-url http://127.0.0.1:8086 \
  --influx-org ql \
  --influx-bucket ql_packet_fragmentation \
  --influx-token-file /opt/ql-packet-fragmentation/secrets/influxdb-token
```

## systemd Service

The repo includes:

- `deploy/systemd/ql-packet-fragmentation.service`
- `deploy/systemd/ql-packet-fragmentation.env.example`
- `scripts/run-service.sh`

Recommended install on the host:

1. Copy the env example to `/etc/default/ql-packet-fragmentation`.
2. Install the unit file to `/etc/systemd/system/ql-packet-fragmentation.service`.
3. Ensure `/opt/ql-packet-fragmentation/.venv` contains `influxdb-client`.
4. Run `systemctl daemon-reload`.
5. Run `systemctl enable --now ql-packet-fragmentation.service`.

When multiple qlds hosts write to the same InfluxDB bucket, set `HOST_TAG` in
the env file so points remain attributable to the source machine.

## Measurements

- `packet_stats`
- `player_packets`

Tags written by the collector:

- `host`
- `server_port`
- `rate_setting` when configured
- `steam_id` and `player_name` for `player_packets`
