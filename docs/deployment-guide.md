# Deployment Guide

This guide deploys the current stack to another Quake Live host:

- `serverchecker` plugin update for player correlation
- eBPF packet collector under systemd
- InfluxDB 2.x in Docker
- firewall allowlist for external InfluxDB access

This is a how-to for an experienced Linux/qlds operator. It assumes a host
layout similar to the current deployment:

- Debian 12
- qlds/minqlx already running
- local Redis used by minqlx
- one or more QL instances in the `27960-27963` range

## Choose Deployment Values

Set these first for the new server:

```bash
export REPO_DIR=/opt/ql-packet-fragmentation
export PORTS=27960-27962
export INTERFACE=enp1s0
export RATE_SETTING=99k
export INFLUX_ALLOWLIST_IP=154.20.139.212
```

To discover the real egress interface:

```bash
ip route get 1.1.1.1 | sed -n '1p'
```

Use the `dev ...` interface from that output.

## One-Shot Installer

If you want a single non-interactive deployment command on Debian 12, the repo
now includes [`scripts/deploy-debian12.sh`](../scripts/deploy-debian12.sh).

Minimal collector-only install:

```bash
curl -fsSL https://raw.githubusercontent.com/dngrtech/ql-packet-fragmentation/main/scripts/deploy-debian12.sh | sudo env REPO_GIT_URL=https://github.com/dngrtech/ql-packet-fragmentation.git PORTS=27960-27962 INTERFACE=enp1s0 REDIS_URL=redis://localhost:6379/3 HOST_TAG=texas bash
```

With plugin deployment and local InfluxDB:

```bash
curl -fsSL https://raw.githubusercontent.com/dngrtech/ql-packet-fragmentation/main/scripts/deploy-debian12.sh | sudo env \
  REPO_GIT_URL=https://github.com/dngrtech/ql-packet-fragmentation.git \
  PORTS=27960-27962 \
  INTERFACE=enp1s0 \
  REDIS_URL=redis://localhost:6379/3 \
  HOST_TAG=texas \
  INSTALL_SERVERCHECKER=1 \
  QL_COMMON_PLUGIN_DIR=/home/ql/assets/common/minqlx-plugins \
  QL_INSTANCE_PLUGIN_DIR_TEMPLATE=/home/ql/qlds-%s/minqlx-plugins \
  INSTALL_INFLUXDB=1 \
  INFLUX_ALLOWLIST_IP=154.20.139.212 \
  bash
```

## 1. Sync the Repository

Copy the repo to the target host:

```bash
sudo mkdir -p "$REPO_DIR"
sudo chown "$USER":"$USER" "$REPO_DIR"
git clone https://github.com/dngrtech/ql-packet-fragmentation.git "$REPO_DIR"
cd "$REPO_DIR"
```

Or update an existing checkout:

```bash
cd "$REPO_DIR"
git pull --ff-only
```

## 2. Install Host Packages

Install the OS packages used by the collector and container deployment:

```bash
sudo apt-get update
sudo apt-get install -y \
  curl \
  openssl \
  python3-venv \
  python3-bpfcc \
  bpfcc-tools \
  "linux-headers-$(uname -r)" \
  redis-server \
  docker.io \
  iptables-persistent
```

Verify the Python modules:

```bash
python3 - <<'PY'
import bcc, redis, pyroute2
print("python modules ok")
PY
```

## 3. Create the Collector Virtualenv

```bash
cd "$REPO_DIR"
python3 -m venv --system-site-packages .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install .
```

That installs the project plus the `influxdb-client` dependency into the venv.

## 4. Deploy the `serverchecker` Plugin

The collector needs `udp_port` in `minqlx:server_status:<port>`.

Copy the plugin from the repo into:

- the shared/common plugin directory
- each instance-specific plugin directory

Example paths from the current qlds-ui layout:

```bash
sudo install -m 644 \
  "$REPO_DIR/minqlx-plugins/serverchecker.py" \
  /home/ql/assets/common/minqlx-plugins/serverchecker.py

for port in 27960 27961 27962; do
  sudo install -m 644 \
    "$REPO_DIR/minqlx-plugins/serverchecker.py" \
    "/home/ql/qlds-${port}/minqlx-plugins/serverchecker.py"
done
```

Restart or reload each QL instance so the plugin code is live.

If your host uses systemd instance units:

```bash
for port in 27960 27961 27962; do
  sudo systemctl restart "qlds@${port}"
done
```

## 5. Verify Redis Player Correlation

Check that the server status key exists and includes `udp_port`:

```bash
redis-cli -n 3 get minqlx:server_status:27962 | python3 -m json.tool
```

You should see player objects like:

```json
{
  "name": "rage^7",
  "steam": "76561199795317792",
  "udp_port": 48385
}
```

Notes:

- minqlx Redis DB is `server_port - 27959`
- for example, `27960 -> db1`, `27961 -> db2`, `27962 -> db3`

## 6. Deploy InfluxDB 2.x in Docker

Create persistent directories:

```bash
sudo install -d -m 700 /opt/influxdb /opt/influxdb/data /opt/influxdb/config /opt/influxdb/secrets
sudo install -d -m 700 "$REPO_DIR/secrets"
```

Generate bootstrap credentials:

```bash
sudo bash -c '
password=$(openssl rand -base64 24 | tr -d "\n")
token=$(openssl rand -hex 32)
cat > /opt/influxdb/influxdb.env <<ENV
DOCKER_INFLUXDB_INIT_MODE=setup
DOCKER_INFLUXDB_INIT_USERNAME=admin
DOCKER_INFLUXDB_INIT_PASSWORD=${password}
DOCKER_INFLUXDB_INIT_ORG=ql
DOCKER_INFLUXDB_INIT_BUCKET=ql_packet_fragmentation
DOCKER_INFLUXDB_INIT_ADMIN_TOKEN=${token}
ENV
chmod 600 /opt/influxdb/influxdb.env
cat > /opt/influxdb/credentials.txt <<CREDS
username=admin
password=${password}
org=ql
bucket=ql_packet_fragmentation
token=${token}
CREDS
chmod 600 /opt/influxdb/credentials.txt
printf %s "${token}" > '"$REPO_DIR"'/secrets/influxdb-token
chmod 600 '"$REPO_DIR"'/secrets/influxdb-token
'
```

Start Docker and run the container:

```bash
sudo systemctl enable --now docker
sudo docker rm -f influxdb2 >/dev/null 2>&1 || true
sudo docker pull influxdb:2
sudo docker run -d \
  --name influxdb2 \
  --restart unless-stopped \
  --network host \
  --env-file /opt/influxdb/influxdb.env \
  -v /opt/influxdb/data:/var/lib/influxdb2 \
  -v /opt/influxdb/config:/etc/influxdb2 \
  influxdb:2
```

Wait for health:

```bash
for _ in $(seq 1 30); do
  curl -fsS http://127.0.0.1:8086/health && break
  sleep 1
done
```

## 7. Lock Down InfluxDB with the Firewall

Allow the external IP you want and persist the rule:

```bash
sudo iptables -C INPUT -p tcp -s "$INFLUX_ALLOWLIST_IP" --dport 8086 -j ACCEPT 2>/dev/null || \
  sudo iptables -I INPUT 4 -p tcp -s "$INFLUX_ALLOWLIST_IP" --dport 8086 -j ACCEPT
sudo netfilter-persistent save
```

If `iptables-persistent` prompts during install on a fresh host, it is safe to
accept the current rules and then save again after adding the `8086` allowlist
rule above.

Why host networking:

- InfluxDB still listens on `*:8086`
- access control stays in the normal host `iptables` INPUT chain
- the collector writes locally to `127.0.0.1:8086`

## 8. Install and Configure the systemd Collector Service

Install the env file and unit:

```bash
sudo install -m 600 \
  "$REPO_DIR/deploy/systemd/ql-packet-fragmentation.env.example" \
  /etc/default/ql-packet-fragmentation

sudo install -m 644 \
  "$REPO_DIR/deploy/systemd/ql-packet-fragmentation.service" \
  /etc/systemd/system/ql-packet-fragmentation.service

sudo chmod 755 "$REPO_DIR/scripts/run-service.sh"
```

Edit `/etc/default/ql-packet-fragmentation` to match the new host:

```bash
sudoedit /etc/default/ql-packet-fragmentation
```

Recommended values:

```bash
INTERFACE=enp1s0
PORTS=27960-27962
INTERVAL=10
REDIS_URL=redis://localhost:6379/3
RATE_SETTING=99k
HOST_TAG=texas
INFLUX_URL=http://127.0.0.1:8086
INFLUX_ORG=ql
INFLUX_BUCKET=ql_packet_fragmentation
INFLUX_TOKEN_FILE=/opt/ql-packet-fragmentation/secrets/influxdb-token
```

Notes:

- `REDIS_URL` is required for player mapping
- in multi-port mode, the collector reuses the Redis host/port/credentials and
  derives the DB index from each server port automatically
- the DB path in `REDIS_URL` does not need to match every port in the range

Enable and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ql-packet-fragmentation.service
```

## 9. Verify the Deployment

Service status:

```bash
sudo systemctl status ql-packet-fragmentation.service
```

Live logs:

```bash
sudo journalctl -u ql-packet-fragmentation.service -f
```

You should see interval output with per-port summaries and per-player rows when
real players are connected.

Query InfluxDB locally:

```bash
token=$(grep '^token=' /opt/influxdb/credentials.txt | cut -d= -f2-)
sudo docker exec influxdb2 influx query \
  --host http://127.0.0.1:8086 \
  --org ql \
  --token "$token" \
  'from(bucket: "ql_packet_fragmentation") |> range(start: -10m) |> filter(fn: (r) => r._measurement == "packet_stats") |> last()'
```

Open the UI from the allowlisted client:

```text
http://YOUR_SERVER_IP:8086
```

Login with the credentials in:

```text
/opt/influxdb/credentials.txt
```

## 10. Operational Commands

Restart the collector:

```bash
sudo systemctl restart ql-packet-fragmentation.service
```

Restart InfluxDB:

```bash
sudo docker restart influxdb2
```

Check that port `8086` is listening:

```bash
sudo ss -ltnp | grep 8086
```

Check the firewall rule:

```bash
sudo iptables -S INPUT | grep 8086
```
