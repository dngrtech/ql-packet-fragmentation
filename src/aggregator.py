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


IpData = Dict[str, List[Tuple[int, int]]]  # {ip: [(size, count), ...]}


def aggregate_packets(ip_data: IpData) -> dict:
    """Aggregate per-IP packet size data into summary stats.

    Args:
        ip_data: Dict mapping dest IP to list of (packet_size, count) tuples.
                 This is the format read from BPF maps.

    Returns:
        Dict with keys: total_packets, fragmented_packets, avg_size, max_size,
        buckets (list of 4 counts), per_ip (dict of per-IP stats).
    """
    total_packets = 0
    fragmented_packets = 0
    size_sum = 0
    max_size = 0
    buckets = [0, 0, 0, 0]
    per_ip = {}

    for ip, entries in ip_data.items():
        ip_total = 0
        ip_frag = 0
        ip_size_sum = 0
        ip_max = 0

        for size, count in entries:
            ip_total += count
            ip_size_sum += size * count
            if size > ip_max:
                ip_max = size
            if size > FRAG_THRESHOLD:
                ip_frag += count
            buckets[_bucket_index(size)] += count

        per_ip[ip] = {
            "total_packets": ip_total,
            "fragmented_packets": ip_frag,
            "avg_size": ip_size_sum / ip_total if ip_total else 0.0,
            "max_size": ip_max,
        }

        total_packets += ip_total
        fragmented_packets += ip_frag
        size_sum += ip_size_sum
        if ip_max > max_size:
            max_size = ip_max

    return {
        "total_packets": total_packets,
        "fragmented_packets": fragmented_packets,
        "avg_size": size_sum / total_packets if total_packets else 0.0,
        "max_size": max_size,
        "buckets": buckets,
        "per_ip": per_ip,
    }
