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
        default="lo",
        help="Network interface to attach eBPF program to (default: lo)",
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
        "--rcon-password",
        default=None,
        help="QL server rcon password for player identification",
    )
    parser.add_argument(
        "--rcon-host",
        default="127.0.0.1",
        help="QL server host for rcon (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--redis-url",
        default=None,
        help="Redis URL for player name lookup (e.g. redis://localhost:6379/3)",
    )
    parser.add_argument(
        "--rate-setting",
        choices=["25k", "99k"],
        default=None,
        help="Label for the current rate setting (for display only)",
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


def main():
    global running
    args = parse_args()

    port_min, port_max = parse_port_range(args.ports)

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

    capture = PacketCapture(args.interface, port_min, port_max)
    player_mapper = PlayerMapper(
        rcon_host=args.rcon_host,
        rcon_port=port_min,
        rcon_password=args.rcon_password,
        redis_url=args.redis_url,
    )

    try:
        capture.start()
        print("eBPF program attached. Capturing...\n")
        player_mapper.refresh()

        while running:
            time.sleep(args.interval)

            player_mapper.maybe_refresh()
            port_data = capture.read_and_clear()
            stats = aggregate_packets(port_data)
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
