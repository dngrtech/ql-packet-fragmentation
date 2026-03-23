#!/usr/bin/env bash
set -euo pipefail

WORKDIR="${WORKDIR:-/opt/ql-packet-fragmentation}"
PYTHON_BIN="${PYTHON_BIN:-$WORKDIR/.venv/bin/python}"
RUN_FILE="${RUN_FILE:-$WORKDIR/run.py}"

cmd=(
  "$PYTHON_BIN" "$RUN_FILE"
  --interface "${INTERFACE:-enp1s0}"
  --ports "${PORTS:-27960-27963}"
  --interval "${INTERVAL:-10}"
)

if [[ -n "${REDIS_URL:-}" ]]; then
  cmd+=(--redis-url "$REDIS_URL")
fi

# Collect per-port rate settings (RATE_SETTING_27960=99k, etc.)
rate_map=""
for var in $(compgen -v RATE_SETTING_); do
  port="${var#RATE_SETTING_}"
  rate_map+="${rate_map:+,}${port}:${!var}"
done

if [[ -n "$rate_map" ]]; then
  cmd+=(--rate-setting "$rate_map")
elif [[ -n "${RATE_SETTING:-}" ]]; then
  cmd+=(--rate-setting "$RATE_SETTING")
fi

if [[ -n "${HOST_TAG:-}" ]]; then
  cmd+=(--host-tag "$HOST_TAG")
fi

if [[ -n "${INFLUX_URL:-}" ]]; then
  cmd+=(--influx-url "$INFLUX_URL")
fi

if [[ -n "${INFLUX_ORG:-}" ]]; then
  cmd+=(--influx-org "$INFLUX_ORG")
fi

if [[ -n "${INFLUX_BUCKET:-}" ]]; then
  cmd+=(--influx-bucket "$INFLUX_BUCKET")
fi

if [[ -n "${INFLUX_TOKEN:-}" ]]; then
  cmd+=(--influx-token "$INFLUX_TOKEN")
fi

if [[ -n "${INFLUX_TOKEN_FILE:-}" ]]; then
  cmd+=(--influx-token-file "$INFLUX_TOKEN_FILE")
fi

cd "$WORKDIR"
exec env PYTHONUNBUFFERED=1 "${cmd[@]}"
