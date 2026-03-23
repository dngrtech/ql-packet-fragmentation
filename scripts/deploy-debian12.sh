#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run as root: sudo bash $0" >&2
  exit 1
fi

if [[ -r /etc/os-release ]]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  if [[ ${ID:-} != "debian" || ${VERSION_ID:-} != "12" ]]; then
    echo "This installer targets Debian 12. Detected: ${PRETTY_NAME:-unknown}" >&2
    exit 1
  fi
fi

REPO_DIR="${REPO_DIR:-/opt/ql-packet-fragmentation}"
REPO_SRC="${REPO_SRC:-}"
REPO_GIT_URL="${REPO_GIT_URL:-https://github.com/dngrtech/ql-packet-fragmentation.git}"
REPO_REF="${REPO_REF:-}"
SERVICE_NAME="${SERVICE_NAME:-ql-packet-fragmentation}"
ENV_FILE="${ENV_FILE:-/etc/default/${SERVICE_NAME}}"
SYSTEMD_UNIT_PATH="${SYSTEMD_UNIT_PATH:-/etc/systemd/system/${SERVICE_NAME}.service}"
WORKDIR="${WORKDIR:-$REPO_DIR}"
INTERFACE="${INTERFACE:-$(ip route get 1.1.1.1 | awk '/dev/ {for (i = 1; i <= NF; i++) if ($i == "dev") {print $(i + 1); exit}}')}"
PORTS="${PORTS:-27960-27963}"
INTERVAL="${INTERVAL:-10}"
REDIS_URL="${REDIS_URL:-redis://localhost:6379/1}"
RATE_SETTING="${RATE_SETTING:-99k}"
INFLUX_URL="${INFLUX_URL:-}"
INFLUX_ORG="${INFLUX_ORG:-}"
INFLUX_BUCKET="${INFLUX_BUCKET:-}"
INFLUX_TOKEN="${INFLUX_TOKEN:-}"
INFLUX_TOKEN_FILE="${INFLUX_TOKEN_FILE:-$REPO_DIR/secrets/influxdb-token}"
INSTALL_INFLUXDB="${INSTALL_INFLUXDB:-0}"
INFLUX_CONTAINER_NAME="${INFLUX_CONTAINER_NAME:-influxdb2}"
INFLUXDB_IMAGE="${INFLUXDB_IMAGE:-influxdb:2}"
INFLUXDB_DIR="${INFLUXDB_DIR:-/opt/influxdb}"
INFLUXDB_USERNAME="${INFLUXDB_USERNAME:-admin}"
INFLUXDB_PASSWORD="${INFLUXDB_PASSWORD:-}"
INFLUXDB_TOKEN="${INFLUXDB_TOKEN:-$INFLUX_TOKEN}"
INFLUXDB_ORG="${INFLUXDB_ORG:-${INFLUX_ORG:-ql}}"
INFLUXDB_BUCKET="${INFLUXDB_BUCKET:-${INFLUX_BUCKET:-ql_packet_fragmentation}}"
INFLUX_ALLOWLIST_IP="${INFLUX_ALLOWLIST_IP:-}"
INSTALL_SERVERCHECKER="${INSTALL_SERVERCHECKER:-0}"
QL_COMMON_PLUGIN_DIR="${QL_COMMON_PLUGIN_DIR:-}"
QL_INSTANCE_PLUGIN_DIR_TEMPLATE="${QL_INSTANCE_PLUGIN_DIR_TEMPLATE:-}"
QL_SYSTEMD_TEMPLATE="${QL_SYSTEMD_TEMPLATE:-qlds@%s}"
RESTART_QLDS="${RESTART_QLDS:-0}"
APT_PACKAGES="${APT_PACKAGES:-curl openssl python3-venv python3-bpfcc bpfcc-tools redis-server}"

if [[ -z "$INTERFACE" ]]; then
  echo "Failed to detect the outbound interface. Set INTERFACE explicitly." >&2
  exit 1
fi

if [[ "$INSTALL_INFLUXDB" == "1" ]]; then
  APT_PACKAGES+=" docker.io iptables-persistent"
fi

echo "Deploying ${SERVICE_NAME} to ${REPO_DIR}"
echo "Interface=${INTERFACE} Ports=${PORTS} Interval=${INTERVAL}"

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y $APT_PACKAGES

if [[ -n "$REPO_SRC" ]]; then
  echo "Using local source: ${REPO_SRC}"
  mkdir -p "$REPO_DIR"
  if [[ "$REPO_SRC" != "$REPO_DIR" ]]; then
    if command -v rsync >/dev/null 2>&1; then
      rsync -a --delete \
        --exclude '.git/' \
        --exclude '.pytest_cache/' \
        --exclude '.venv/' \
        "$REPO_SRC"/ "$REPO_DIR"/
    else
      cp -a "$REPO_SRC"/. "$REPO_DIR"/
      rm -rf "$REPO_DIR/.git" "$REPO_DIR/.pytest_cache" "$REPO_DIR/.venv"
    fi
  fi
else
  echo "Using git source: ${REPO_GIT_URL}"
  apt-get install -y git
  if [[ -d "$REPO_DIR/.git" ]]; then
    git -C "$REPO_DIR" fetch --tags origin
    if [[ -n "$REPO_REF" ]]; then
      git -C "$REPO_DIR" checkout --detach "$REPO_REF"
    else
      current_branch=$(git -C "$REPO_DIR" symbolic-ref --quiet --short HEAD || true)
      if [[ -n "$current_branch" ]]; then
        git -C "$REPO_DIR" pull --ff-only origin "$current_branch"
      else
        default_branch=$(git -C "$REPO_DIR" remote show origin | sed -n '/HEAD branch/s/.*: //p')
        git -C "$REPO_DIR" checkout "$default_branch"
        git -C "$REPO_DIR" pull --ff-only origin "$default_branch"
      fi
    fi
  else
    rm -rf "$REPO_DIR"
    git clone "$REPO_GIT_URL" "$REPO_DIR"
    if [[ -n "$REPO_REF" ]]; then
      git -C "$REPO_DIR" checkout --detach "$REPO_REF"
    fi
  fi
fi

cd "$REPO_DIR"
python3 -m venv --system-site-packages .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install .

install -d -m 700 "$REPO_DIR/secrets"
install -m 755 "$REPO_DIR/scripts/run-service.sh" "$REPO_DIR/scripts/run-service.sh"

cat > "$ENV_FILE" <<EOF
INTERFACE=${INTERFACE}
PORTS=${PORTS}
INTERVAL=${INTERVAL}
REDIS_URL=${REDIS_URL}
RATE_SETTING=${RATE_SETTING}
INFLUX_URL=${INFLUX_URL}
INFLUX_ORG=${INFLUX_ORG}
INFLUX_BUCKET=${INFLUX_BUCKET}
INFLUX_TOKEN=${INFLUX_TOKEN}
INFLUX_TOKEN_FILE=${INFLUX_TOKEN_FILE}
WORKDIR=${WORKDIR}
EOF
chmod 600 "$ENV_FILE"

install -m 644 "$REPO_DIR/deploy/systemd/ql-packet-fragmentation.service" "$SYSTEMD_UNIT_PATH"
sed -i \
  -e "s|/etc/default/ql-packet-fragmentation|$ENV_FILE|g" \
  -e "s|/opt/ql-packet-fragmentation|$REPO_DIR|g" \
  -e "s|ql-packet-fragmentation|$SERVICE_NAME|g" \
  "$SYSTEMD_UNIT_PATH"

if [[ "$INSTALL_SERVERCHECKER" == "1" ]]; then
  if [[ -z "$QL_COMMON_PLUGIN_DIR" && -z "$QL_INSTANCE_PLUGIN_DIR_TEMPLATE" ]]; then
    echo "Set QL_COMMON_PLUGIN_DIR and/or QL_INSTANCE_PLUGIN_DIR_TEMPLATE when INSTALL_SERVERCHECKER=1." >&2
    exit 1
  fi

  if [[ -n "$QL_COMMON_PLUGIN_DIR" ]]; then
    install -d "$QL_COMMON_PLUGIN_DIR"
    install -m 644 \
      "$REPO_DIR/minqlx-plugins/serverchecker.py" \
      "$QL_COMMON_PLUGIN_DIR/serverchecker.py"
  fi

  IFS='-' read -r port_start port_end <<<"$PORTS"
  if [[ -z "${port_end:-}" ]]; then
    port_end="$port_start"
  fi

  if [[ -n "$QL_INSTANCE_PLUGIN_DIR_TEMPLATE" ]]; then
    for ((port = port_start; port <= port_end; port++)); do
      instance_dir=$(printf "$QL_INSTANCE_PLUGIN_DIR_TEMPLATE" "$port")
      install -d "$instance_dir"
      install -m 644 \
        "$REPO_DIR/minqlx-plugins/serverchecker.py" \
        "$instance_dir/serverchecker.py"
      if [[ "$RESTART_QLDS" == "1" ]]; then
        systemctl restart "$(printf "$QL_SYSTEMD_TEMPLATE" "$port")"
      fi
    done
  fi
fi

if [[ "$INSTALL_INFLUXDB" == "1" ]]; then
  install -d -m 700 "$INFLUXDB_DIR" "$INFLUXDB_DIR/data" "$INFLUXDB_DIR/config" "$INFLUXDB_DIR/secrets"

  if [[ -z "$INFLUXDB_PASSWORD" ]]; then
    INFLUXDB_PASSWORD="$(openssl rand -base64 24 | tr -d '\n')"
  fi
  if [[ -z "$INFLUXDB_TOKEN" ]]; then
    INFLUXDB_TOKEN="$(openssl rand -hex 32)"
  fi
  if [[ -z "$INFLUX_URL" ]]; then
    INFLUX_URL="http://127.0.0.1:8086"
    sed -i "s|^INFLUX_URL=.*|INFLUX_URL=${INFLUX_URL}|" "$ENV_FILE"
  fi
  if [[ -z "$INFLUX_ORG" ]]; then
    INFLUX_ORG="$INFLUXDB_ORG"
    sed -i "s|^INFLUX_ORG=.*|INFLUX_ORG=${INFLUX_ORG}|" "$ENV_FILE"
  fi
  if [[ -z "$INFLUX_BUCKET" ]]; then
    INFLUX_BUCKET="$INFLUXDB_BUCKET"
    sed -i "s|^INFLUX_BUCKET=.*|INFLUX_BUCKET=${INFLUX_BUCKET}|" "$ENV_FILE"
  fi
  if [[ -z "$INFLUX_TOKEN" ]]; then
    INFLUX_TOKEN="$INFLUXDB_TOKEN"
    sed -i "s|^INFLUX_TOKEN=.*|INFLUX_TOKEN=${INFLUX_TOKEN}|" "$ENV_FILE"
  fi

  cat > "${INFLUXDB_DIR}/influxdb.env" <<EOF
DOCKER_INFLUXDB_INIT_MODE=setup
DOCKER_INFLUXDB_INIT_USERNAME=${INFLUXDB_USERNAME}
DOCKER_INFLUXDB_INIT_PASSWORD=${INFLUXDB_PASSWORD}
DOCKER_INFLUXDB_INIT_ORG=${INFLUXDB_ORG}
DOCKER_INFLUXDB_INIT_BUCKET=${INFLUXDB_BUCKET}
DOCKER_INFLUXDB_INIT_ADMIN_TOKEN=${INFLUXDB_TOKEN}
EOF
  chmod 600 "${INFLUXDB_DIR}/influxdb.env"

  cat > "${INFLUXDB_DIR}/credentials.txt" <<EOF
username=${INFLUXDB_USERNAME}
password=${INFLUXDB_PASSWORD}
org=${INFLUXDB_ORG}
bucket=${INFLUXDB_BUCKET}
token=${INFLUXDB_TOKEN}
EOF
  chmod 600 "${INFLUXDB_DIR}/credentials.txt"

  printf '%s' "$INFLUXDB_TOKEN" > "$INFLUX_TOKEN_FILE"
  chmod 600 "$INFLUX_TOKEN_FILE"

  systemctl enable --now docker
  docker rm -f "$INFLUX_CONTAINER_NAME" >/dev/null 2>&1 || true
  docker pull "$INFLUXDB_IMAGE"
  docker run -d \
    --name "$INFLUX_CONTAINER_NAME" \
    --restart unless-stopped \
    --network host \
    --env-file "${INFLUXDB_DIR}/influxdb.env" \
    -v "${INFLUXDB_DIR}/data:/var/lib/influxdb2" \
    -v "${INFLUXDB_DIR}/config:/etc/influxdb2" \
    "$INFLUXDB_IMAGE"

  for _ in $(seq 1 30); do
    if curl -fsS http://127.0.0.1:8086/health >/dev/null; then
      break
    fi
    sleep 1
  done

  if [[ -n "$INFLUX_ALLOWLIST_IP" ]]; then
    iptables -C INPUT -p tcp -s "$INFLUX_ALLOWLIST_IP" --dport 8086 -j ACCEPT 2>/dev/null || \
      iptables -I INPUT 4 -p tcp -s "$INFLUX_ALLOWLIST_IP" --dport 8086 -j ACCEPT
    netfilter-persistent save
  fi
fi

systemctl daemon-reload
systemctl enable --now "${SERVICE_NAME}.service"

echo
echo "Deployment complete."
echo "Service: systemctl status ${SERVICE_NAME}.service"
echo "Logs: journalctl -u ${SERVICE_NAME}.service -f"
if [[ "$INSTALL_INFLUXDB" == "1" ]]; then
  echo "Influx credentials: ${INFLUXDB_DIR}/credentials.txt"
fi
