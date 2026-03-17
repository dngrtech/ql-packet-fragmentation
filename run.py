#!/usr/bin/env python3
"""Entry point for QL packet fragmentation capture."""

import argparse
import sys


def parse_args():
    parser = argparse.ArgumentParser(
        description="Capture and analyze QL server packet fragmentation via eBPF"
    )
    parser.add_argument(
        "--interface", "-i",
        default="eth0",
        help="Network interface to attach eBPF program to (default: eth0)",
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
        "--redis-url",
        default=None,
        help="Redis URL for player mapping (optional, e.g. redis://localhost:6379/0)",
    )
    parser.add_argument(
        "--rate-setting",
        choices=["25k", "99k"],
        default=None,
        help="Label for the current rate setting (for display only)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    print(f"QL Packet Fragmentation Capture")
    print(f"Interface: {args.interface}")
    print(f"Ports: {args.ports}")
    print(f"Interval: {args.interval}s")
    print(f"Redis: {args.redis_url or 'disabled'}")
    print(f"Rate: {args.rate_setting or 'unlabeled'}")
    print("(not yet implemented)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
