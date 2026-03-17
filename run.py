#!/usr/bin/env python3
"""Entry point for QL packet fragmentation capture."""

import argparse
import signal
import sys
import time
from pathlib import Path

from src.aggregator import aggregate_packets
from src.capture import PacketCapture
from src.display import format_stats
from src.influx_writer import InfluxWriter
from src.player_map import PlayerMapper


def parse_args():
    parser = argparse.ArgumentParser(
        description="Capture and analyze QL server packet fragmentation via eBPF"
    )
    parser.add_argument(
        "--interface", "-i",
        default="enp1s0",
        help="Network interface to attach eBPF program to (default: enp1s0)",
    )
    parser.add_argument(
        "--ports",
        default="27960-27963",
        help="QL server port or range (default: 27960-27963)",
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
        help=(
            "Redis URL for player mapping. In multi-port mode, the host/port/"
            "credentials are reused and the DB index is derived per server "
            "port (e.g. redis://localhost:6379/3)"
        ),
    )
    parser.add_argument(
        "--rate-setting",
        choices=["25k", "99k"],
        default=None,
        help="Label for the current rate setting (for display only)",
    )
    parser.add_argument(
        "--influx-url",
        default=None,
        help="InfluxDB base URL (e.g. http://127.0.0.1:8086)",
    )
    parser.add_argument(
        "--influx-org",
        default=None,
        help="InfluxDB organization name",
    )
    parser.add_argument(
        "--influx-bucket",
        default=None,
        help="InfluxDB bucket name",
    )
    parser.add_argument(
        "--influx-token",
        default=None,
        help="InfluxDB API token",
    )
    parser.add_argument(
        "--influx-token-file",
        default=None,
        help="Path to a file containing the InfluxDB API token",
    )
    return parser.parse_args()


def parse_port_range(port_str: str):
    """Parse 'min-max' or 'port' into (min, max) ints."""
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


def read_secret(path: str) -> str:
    """Read a secret file and strip trailing whitespace."""
    try:
        return Path(path).read_text().strip()
    except OSError as exc:
        print(f"Error: failed to read secret file '{path}': {exc}", file=sys.stderr)
        sys.exit(1)


def main():
    global running
    args = parse_args()

    port_min, port_max = parse_port_range(args.ports)
    server_ports = list(range(port_min, port_max + 1))

    print("QL Packet Fragmentation Capture (eBPF)")
    print(f"Interface: {args.interface}  Ports: {port_min}-{port_max}  Interval: {args.interval}s")
    if args.rate_setting:
        print(f"Rate setting: {args.rate_setting}")
    print()

    def handle_signal(signum, frame):
        global running
        running = False

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    influx_token = args.influx_token
    if args.influx_token_file:
        influx_token = read_secret(args.influx_token_file)

    capture = PacketCapture(args.interface, port_min, port_max)
    player_mapper = PlayerMapper(redis_url=args.redis_url, ports=server_ports)
    influx_writer = InfluxWriter(
        url=args.influx_url,
        token=influx_token,
        org=args.influx_org,
        bucket=args.influx_bucket,
    )

    try:
        capture.start()
        print("eBPF program attached. Capturing...\n")
        player_mapper.refresh()

        while running:
            time.sleep(args.interval)
            timestamp_ns = time.time_ns()

            player_mapper.maybe_refresh()
            server_data = capture.read_and_clear()
            outputs = []
            for server_port in server_ports:
                stats = aggregate_packets(server_data.get(server_port, {}))
                player_map = player_mapper.get_map(server_port)
                outputs.append(
                    format_stats(
                        stats,
                        player_map=player_map,
                        rate_setting=args.rate_setting,
                        server_port=server_port if len(server_ports) > 1 else None,
                    )
                )
                influx_writer.write_server_stats(
                    server_port=server_port,
                    stats=stats,
                    player_map=player_map,
                    rate_setting=args.rate_setting,
                    timestamp_ns=timestamp_ns,
                )
            print("\n\n".join(outputs))
            print()

    finally:
        influx_writer.close()
        capture.stop()
        print("\nCapture stopped.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
