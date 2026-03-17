"""Pure aggregation logic for packet size data from BPF maps."""

from typing import Dict, List, Tuple

# UDP payload threshold before IP fragmentation occurs (standard 1500 MTU)
FRAG_THRESHOLD = 1472

# Bucket boundaries (upper bound exclusive): [0,500), [500,1000), [1000,1472], (1472,+inf)
BUCKET_BOUNDS = [500, 1000, FRAG_THRESHOLD]


def _bucket_index(size: int) -> int:
    """Return bucket index for a given packet size.

    Buckets: [0,500), [500,1000), [1000,1472], (1472,+inf)
    """
    if size > FRAG_THRESHOLD:
        return 3
    for i, bound in enumerate(BUCKET_BOUNDS):
        if size < bound:
            return i
    return 2  # [1000, 1472] — fits in MTU


PortData = Dict[int, List[Tuple[int, int]]]  # {client_udp_port: [(size, count), ...]}


def aggregate_packets(port_data: PortData) -> dict:
    """Aggregate per-client-port packet size data into summary stats.

    Args:
        port_data: Dict mapping client UDP port to list of (packet_size, count)
                   tuples. This is the format read from BPF maps.

    Returns:
        Dict with keys: total_packets, fragmented_packets, avg_size, max_size,
        buckets (list of 4 counts), per_port (dict of per-port stats).
    """
    total_packets = 0
    fragmented_packets = 0
    size_sum = 0
    max_size = 0
    buckets = [0, 0, 0, 0]
    per_port = {}

    for client_port, entries in port_data.items():
        port_total = 0
        port_frag = 0
        port_size_sum = 0
        port_max = 0

        for size, count in entries:
            port_total += count
            port_size_sum += size * count
            if size > port_max:
                port_max = size
            if size > FRAG_THRESHOLD:
                port_frag += count
            buckets[_bucket_index(size)] += count

        per_port[client_port] = {
            "total_packets": port_total,
            "fragmented_packets": port_frag,
            "avg_size": port_size_sum / port_total if port_total else 0.0,
            "max_size": port_max,
        }

        total_packets += port_total
        fragmented_packets += port_frag
        size_sum += port_size_sum
        if port_max > max_size:
            max_size = port_max

    return {
        "total_packets": total_packets,
        "fragmented_packets": fragmented_packets,
        "avg_size": size_sum / total_packets if total_packets else 0.0,
        "max_size": max_size,
        "buckets": buckets,
        "per_port": per_port,
    }
