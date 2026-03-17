"""Optional InfluxDB persistence for packet fragmentation stats."""

import socket
import sys
import time
from typing import Dict, List, Optional, Tuple


PlayerMap = Dict[int, Tuple[str, str]]  # {client_udp_port: (steamid, name)}


def _frag_pct(fragmented_packets: int, total_packets: int) -> float:
    if total_packets == 0:
        return 0.0
    return (fragmented_packets / total_packets) * 100.0


def build_records(
    server_port: int,
    stats: dict,
    player_map: Optional[PlayerMap] = None,
    rate_setting: Optional[str] = None,
    host_tag: Optional[str] = None,
) -> List[dict]:
    """Build InfluxDB record dictionaries from a capture interval."""
    tags = {
        "server_port": str(server_port),
        "host": host_tag or socket.gethostname(),
    }
    if rate_setting:
        tags["rate_setting"] = rate_setting

    records = [
        {
            "measurement": "packet_stats",
            "tags": tags,
            "fields": {
                "total_packets": int(stats["total_packets"]),
                "fragmented_packets": int(stats["fragmented_packets"]),
                "fragmentation_pct": float(
                    _frag_pct(stats["fragmented_packets"], stats["total_packets"])
                ),
                "avg_size": float(stats["avg_size"]),
                "max_size": int(stats["max_size"]),
                "bucket_0_499": int(stats["buckets"][0]),
                "bucket_500_999": int(stats["buckets"][1]),
                "bucket_1000_1472": int(stats["buckets"][2]),
                "bucket_1473_plus": int(stats["buckets"][3]),
            },
        }
    ]

    if not player_map:
        return records

    for client_port, port_stats in sorted(stats.get("per_port", {}).items()):
        if client_port not in player_map:
            continue
        steamid, name = player_map[client_port]
        player_tags = dict(tags)
        player_tags["steam_id"] = steamid
        player_tags["player_name"] = name
        records.append(
            {
                "measurement": "player_packets",
                "tags": player_tags,
                "fields": {
                    "client_udp_port": int(client_port),
                    "total_packets": int(port_stats["total_packets"]),
                    "fragmented_packets": int(port_stats["fragmented_packets"]),
                    "fragmentation_pct": float(
                        _frag_pct(
                            port_stats["fragmented_packets"],
                            port_stats["total_packets"],
                        )
                    ),
                    "avg_size": float(port_stats["avg_size"]),
                    "max_size": int(port_stats["max_size"]),
                },
            }
        )

    return records


class InfluxWriter:
    """Writes capture intervals to InfluxDB when configured."""

    def __init__(
        self,
        url: Optional[str] = None,
        token: Optional[str] = None,
        org: Optional[str] = None,
        bucket: Optional[str] = None,
        host_tag: Optional[str] = None,
    ):
        self._url = url
        self._token = token
        self._org = org
        self._bucket = bucket
        self._host_tag = host_tag or socket.gethostname()
        self._client = None
        self._write_api = None
        self._Point = None

        if not all([url, token, org, bucket]):
            return

        try:
            import influxdb_client
            from influxdb_client.client.write_api import SYNCHRONOUS
        except ImportError as exc:
            raise RuntimeError(
                "InfluxDB support requires the 'influxdb-client' package"
            ) from exc

        self._Point = influxdb_client.Point
        self._client = influxdb_client.InfluxDBClient(
            url=url,
            token=token,
            org=org,
        )
        self._write_api = self._client.write_api(write_options=SYNCHRONOUS)

    @property
    def enabled(self) -> bool:
        return self._write_api is not None

    def write_server_stats(
        self,
        server_port: int,
        stats: dict,
        player_map: Optional[PlayerMap] = None,
        rate_setting: Optional[str] = None,
        timestamp_ns: Optional[int] = None,
    ) -> None:
        if not self.enabled:
            return

        record_time = timestamp_ns if timestamp_ns is not None else time.time_ns()
        points = []
        for record in build_records(
            server_port=server_port,
            stats=stats,
            player_map=player_map,
            rate_setting=rate_setting,
            host_tag=self._host_tag,
        ):
            point = self._Point(record["measurement"])
            for key, value in record["tags"].items():
                point.tag(key, value)
            for key, value in record["fields"].items():
                point.field(key, value)
            point.time(record_time)
            points.append(point)

        try:
            self._write_api.write(
                bucket=self._bucket,
                org=self._org,
                record=points,
            )
        except Exception as exc:  # pragma: no cover - depends on external service
            print(f"Warning: failed to write to InfluxDB: {exc}", file=sys.stderr)

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
