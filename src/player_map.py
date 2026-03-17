# src/player_map.py
"""Player mapping via minqlx server_status Redis key — transient, in-memory only."""

import json
import re
import time
from typing import Dict, Optional, Tuple

import redis

REFRESH_INTERVAL = 30  # seconds

PlayerMap = Dict[int, Tuple[str, str]]  # {qport: (steamid, name)}

# Strip Quake color codes (^N or ^X where X is a digit/color char)
_COLOR_RE = re.compile(r'\^\d')


def _strip_colors(name: str) -> str:
    return _COLOR_RE.sub('', name)


def build_player_map(r: redis.Redis, port: int) -> PlayerMap:
    """Read minqlx:server_status:<port> and return {qport: (steamid, name)}.

    Bots have qport == -1 and are excluded. No IP addresses involved.
    """
    raw = r.get(f"minqlx:server_status:{port}")
    if not raw:
        return {}

    try:
        status = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}

    result: PlayerMap = {}
    for p in status.get("players", []):
        qport = p.get("udp_port")
        if not qport or qport < 0:
            continue  # bot or unknown
        steamid = str(p.get("steam", ""))
        name = _strip_colors(p.get("name", steamid))
        result[qport] = (steamid, name)

    return result


class PlayerMapper:
    """Manages periodic refresh of the qport -> (steamid, name) mapping."""

    def __init__(self, redis_url: Optional[str], port: int):
        self._port = port
        self._map: PlayerMap = {}
        self._redis: Optional[redis.Redis] = None
        self._last_refresh: float = 0

        if redis_url:
            self._redis = redis.from_url(redis_url)

    def refresh(self) -> None:
        if self._redis is None:
            return
        self._map = build_player_map(self._redis, self._port)
        self._last_refresh = time.monotonic()

    def maybe_refresh(self) -> None:
        if self._redis is None:
            return
        if time.monotonic() - self._last_refresh >= REFRESH_INTERVAL:
            self.refresh()

    def get_map(self) -> PlayerMap:
        return self._map
