"""Terminal display formatting for packet stats."""

from typing import Dict, Optional, Tuple
import time

BUCKET_LABELS = [
    "   0 - 499 ",
    " 500 - 999 ",
    "1000 - 1472",
    "1472+  FRAG",
]


def format_histogram_bar(count: int, total: int, width: int = 40) -> str:
    """Return a '#'-bar proportional to count/total."""
    if total == 0:
        return ""
    bar_len = int((count / total) * width)
    return "#" * bar_len


def format_stats(
    stats: dict,
    player_map: Optional[Dict[str, Tuple[str, str]]] = None,
    rate_setting: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> str:
    """Format aggregated stats for terminal output.

    Args:
        stats: Output from aggregate_packets().
        player_map: Optional {ip: (steamid, name)} for per-player display.
        rate_setting: Optional rate label (e.g. "99k").
        timestamp: Optional timestamp string (defaults to current time).
    """
    ts = timestamp or time.strftime('%H:%M:%S')
    total = stats["total_packets"]

    if total == 0:
        return f"[{ts}] No packets (0) captured in this interval."

    frag = stats["fragmented_packets"]
    frag_pct = (frag / total) * 100

    lines = []
    header = f"[{ts}]"
    if rate_setting:
        header += f" rate={rate_setting}"
    header += f"  pkts={total}  frag={frag} ({frag_pct:.1f}%)  avg={stats['avg_size']:.0f}B  max={stats['max_size']}B"
    lines.append(header)

    # Histogram
    lines.append("  Size Range     Count   Pct   Distribution")
    lines.append("  " + "-" * 60)
    for i, label in enumerate(BUCKET_LABELS):
        count = stats["buckets"][i]
        pct = (count / total) * 100 if total else 0
        bar = format_histogram_bar(count, total)
        lines.append(f"  {label}  {count:>6}  {pct:>5.1f}%  {bar}")

    # Per-player breakdown
    if stats.get("per_ip") and player_map:
        lines.append("")
        lines.append("  Per-Player Breakdown:")
        lines.append(f"  {'Player':<20} {'Pkts':>6} {'Frag':>6} {'Frag%':>7} {'Avg':>6} {'Max':>6}")
        lines.append("  " + "-" * 60)
        for ip, ip_stats in sorted(stats["per_ip"].items()):
            if ip in player_map:
                _, name = player_map[ip]
            else:
                name = ip
            ip_total = ip_stats["total_packets"]
            ip_frag = ip_stats["fragmented_packets"]
            ip_frag_pct = (ip_frag / ip_total) * 100 if ip_total else 0
            lines.append(
                f"  {name:<20} {ip_total:>6} {ip_frag:>6} {ip_frag_pct:>6.1f}% "
                f"{ip_stats['avg_size']:>5.0f}B {ip_stats['max_size']:>5}B"
            )

    return "\n".join(lines)
