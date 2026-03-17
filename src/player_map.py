# src/player_map.py
"""Redis-based player IP mapping using minqlx data."""

import re
import time
from typing import Dict, Optional, Tuple

import redis

# Refresh interval for the reverse index
REFRESH_INTERVAL = 60

PlayerMap = Dict[str, Tuple[str, str]]  # {ip: (steamid, name)}

STEAMID_PATTERN = re.compile(rb"minqlx:players:(\d+):ips")


def build_reverse_index(r: redis.Redis) -> PlayerMap:
    """Scan minqlx Redis keys and build {ip: (steamid, name)} mapping."""
    result: PlayerMap = {}

    for key in r.scan_iter(match=b"minqlx:players:*:ips"):
        m = STEAMID_PATTERN.match(key)
        if not m:
            continue
        steamid = m.group(1).decode()
        name_bytes = r.lindex(b"minqlx:players:" + m.group(1), 0)
        name = name_bytes.decode() if name_bytes else "unknown"
        ips = r.smembers(key)
        for ip_bytes in ips:
            result[ip_bytes.decode()] = (steamid, name)

    return result


class PlayerMapper:
    """Manages periodic refresh of the IP -> player reverse index."""

    def __init__(self, redis_url: Optional[str] = None):
        self._map: PlayerMap = {}
        self._redis: Optional[redis.Redis] = None
        self._last_refresh: float = 0

        if redis_url:
            self._redis = redis.from_url(redis_url)

    def refresh(self) -> None:
        """Rebuild the reverse index from Redis."""
        if self._redis is None:
            return
        self._map = build_reverse_index(self._redis)
        self._last_refresh = time.monotonic()

    def maybe_refresh(self) -> None:
        """Refresh if REFRESH_INTERVAL has elapsed."""
        if self._redis is None:
            return
        if time.monotonic() - self._last_refresh >= REFRESH_INTERVAL:
            self.refresh()

    def get_map(self) -> PlayerMap:
        """Return current IP -> (steamid, name) mapping."""
        return self._map
