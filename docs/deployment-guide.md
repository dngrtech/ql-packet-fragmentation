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

The repo includes [`scripts/deploy-debian12.sh`](../scripts/deploy-debian12.sh)
for single-command deployment. The script runs with `set -euo pipefail` — any
step failure aborts the entire run. If it fails partway through, see
[Troubleshooting](#troubleshooting) to identify what was and wasn't completed.

### Running via SSH from a management host

Typical pattern using an SSH key from the qlds-ui terraform directory:

```bash
sudo ssh -i /opt/qlds-ui/terraform/ssh-keys/<HOST_KEY> \
  -o StrictHostKeyChecking=accept-new root@<SERVER_IP> \
  'curl -fsSL https://raw.githubusercontent.com/dngrtech/ql-packet-fragmentation/main/scripts/deploy-debian12.sh | env \
    REPO_GIT_URL=https://github.com/dngrtech/ql-packet-fragmentation.git \
    PORTS=27960-27963 \
    INTERFACE=eth0 \
    REDIS_URL=redis://localhost:6379/3 \
    HOST_TAG=<location> \
    INSTALL_INFLUXDB=1 \
    bash'
```

Note: when running via SSH as root, `sudo` is not needed inside the command.

### Running directly on the target host

Minimal collector-only install:

```bash
curl -fsSL https://raw.githubusercontent.com/dngrtech/ql-packet-fragmentation/main/scripts/deploy-debian12.sh | sudo env REPO_GIT_URL=https://github.com/dngrtech/ql-packet-fragmentation.git PORTS=27960-27962 INTERFACE=enp1s0 REDIS_URL=redis://localhost:6379/3 HOST_TAG=texas bash
```

Full install with plugins, InfluxDB, and firewall allowlist:

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

### Installer Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `REPO_GIT_URL` | `https://github.com/dngrtech/ql-packet-fragmentation.git` | Git clone URL |
| `REPO_REF` | *(latest main)* | Tag or commit to deploy |
| `REPO_DIR` | `/opt/ql-packet-fragmentation` | Install directory |
| `INTERFACE` | *(auto-detected)* | Network interface for eBPF capture |
| `PORTS` | `27960-27963` | QL server port range |
| `INTERVAL` | `10` | Capture interval in seconds |
| `REDIS_URL` | `redis://localhost:6379/1` | Redis URL for player mapping |
| `RATE_SETTING` | `99k` | QL rate setting tag for InfluxDB (all ports) |
| `RATE_SETTING_<port>` | *(empty)* | Per-port rate override (e.g. `RATE_SETTING_27960=99k`) |
| `HOST_TAG` | *(empty)* | Host identifier for InfluxDB — set this to distinguish hosts |
| `INSTALL_INFLUXDB` | `0` | Set to `1` to deploy InfluxDB in Docker |
| `INFLUX_ALLOWLIST_IP` | *(empty)* | External IP to allow through firewall to InfluxDB |
| `INSTALL_SERVERCHECKER` | `0` | Set to `1` to deploy the minqlx plugin |
| `QL_COMMON_PLUGIN_DIR` | *(empty)* | Shared minqlx plugin directory |
| `QL_INSTANCE_PLUGIN_DIR_TEMPLATE` | *(empty)* | Per-instance plugin dir (printf template, `%s` = port) |
| `RESTART_QLDS` | `0` | Set to `1` to restart QL instances after plugin deploy |
| `SERVICE_NAME` | `ql-packet-fragmentation` | systemd service name |

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
HOST_TAG=texas
INFLUX_URL=http://127.0.0.1:8086
INFLUX_ORG=ql
INFLUX_BUCKET=ql_packet_fragmentation
INFLUX_TOKEN_FILE=/opt/ql-packet-fragmentation/secrets/influxdb-token

# Rate setting — per-port (preferred when ports differ):
RATE_SETTING_27960=99k
RATE_SETTING_27961=25k
RATE_SETTING_27962=25k

# Or a single value for all ports:
# RATE_SETTING=99k
```

Notes:

- per-port `RATE_SETTING_<port>` vars take precedence; if any exist, bare
  `RATE_SETTING` is ignored
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

### Collector service

```bash
sudo systemctl status ql-packet-fragmentation.service
```

A healthy service shows `active (running)` and the process command line should
include the expected `--interface`, `--ports`, and `--host-tag` flags.

Check the journal for the eBPF attach confirmation:

```bash
sudo journalctl -u ql-packet-fragmentation.service -n 20 --no-pager
```

You should see:

```
QL Packet Fragmentation Capture (eBPF)
Interface: eth0  Ports: 27960-27963  Interval: 10s
eBPF program attached. Capturing...
```

If the service is crash-looping instead, see [Troubleshooting](#troubleshooting).

### Env file

Confirm the env file has the correct values for this host:

```bash
sudo cat /etc/default/ql-packet-fragmentation
```

### InfluxDB (if deployed)

```bash
sudo docker ps --filter name=influxdb2
curl -fsS http://127.0.0.1:8086/health
```

Query recent data:

```bash
token=$(grep '^token=' /opt/influxdb/credentials.txt | cut -d= -f2-)
sudo docker exec influxdb2 influx query \
  --host http://127.0.0.1:8086 \
  --org ql \
  --token "$token" \
  'from(bucket: "ql_packet_fragmentation") |> range(start: -10m) |> filter(fn: (r) => r._measurement == "packet_stats") |> last()'
```

Open the UI from the allowlisted client at `http://YOUR_SERVER_IP:8086`.
Login credentials are in `/opt/influxdb/credentials.txt`.

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

## 11. Updating an Existing Deployment

To update the collector code on a running server:

```bash
cd /opt/ql-packet-fragmentation
git pull --ff-only origin main
.venv/bin/pip install . --quiet
sudo systemctl restart ql-packet-fragmentation.service
```

Via SSH from the management host:

```bash
sudo ssh -i /opt/qlds-ui/terraform/ssh-keys/<HOST_KEY> root@<SERVER_IP> \
  'cd /opt/ql-packet-fragmentation && git pull --ff-only origin main && .venv/bin/pip install . --quiet && systemctl restart ql-packet-fragmentation.service && sleep 3 && systemctl status ql-packet-fragmentation.service'
```

## Troubleshooting

Check the service journal for errors:

```bash
sudo journalctl -u ql-packet-fragmentation.service -n 30 --no-pager
```

### "Permission denied" (exit code 203/EXEC)

The `run-service.sh` script is not executable:

```bash
sudo chmod 755 /opt/ql-packet-fragmentation/scripts/run-service.sh
sudo systemctl restart ql-packet-fragmentation.service
```

### "Failed to compile BPF module" / "Unable to find kernel headers"

Kernel headers are missing. BCC compiles eBPF programs at runtime and needs
headers matching the running kernel:

```bash
sudo apt-get install -y "linux-headers-$(uname -r)"
sudo systemctl restart ql-packet-fragmentation.service
```

### "failed to read secret file ... influxdb-token"

The InfluxDB token file was not created. This happens when the one-shot
installer fails before reaching the InfluxDB setup phase. Either re-run the
installer or create the token manually:

```bash
sudo install -d -m 700 /opt/ql-packet-fragmentation/secrets
token=$(grep '^token=' /opt/influxdb/credentials.txt | cut -d= -f2-)
printf '%s' "$token" | sudo tee /opt/ql-packet-fragmentation/secrets/influxdb-token > /dev/null
sudo chmod 600 /opt/ql-packet-fragmentation/secrets/influxdb-token
sudo systemctl restart ql-packet-fragmentation.service
```

### One-shot installer failed partway through

The script uses `set -e` so any command failure aborts the rest. Check what
was completed:

| Check | Command |
|-------|---------|
| Repo cloned? | `ls /opt/ql-packet-fragmentation/.git` |
| Venv created? | `ls /opt/ql-packet-fragmentation/.venv/bin/python` |
| Env file created? | `cat /etc/default/ql-packet-fragmentation` |
| Systemd unit installed? | `cat /etc/systemd/system/ql-packet-fragmentation.service` |
| InfluxDB running? | `docker ps --filter name=influxdb2` |
| Token file exists? | `ls -la /opt/ql-packet-fragmentation/secrets/influxdb-token` |
| Service running? | `systemctl status ql-packet-fragmentation.service` |

Resume from the failed step using the manual instructions in this guide, or
re-run the installer (it is safe to re-run — it will update an existing clone
and overwrite config files).
