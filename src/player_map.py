# src/player_map.py
"""Player mapping via minqlx server_status Redis key — transient, in-memory only."""

import json
import re
import time
from typing import Dict, Iterable, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

import redis

REFRESH_INTERVAL = 30  # seconds

PlayerMap = Dict[int, Tuple[str, str]]  # {client_udp_port: (steamid, name)}
PlayerMaps = Dict[int, PlayerMap]  # {server_port: PlayerMap}

# Strip Quake color codes (^N or ^X where X is a digit/color char)
_COLOR_RE = re.compile(r'\^\d')


def _strip_colors(name: str) -> str:
    return _COLOR_RE.sub('', name)


def _redis_db_for_port(port: int) -> int:
    """Return the default minqlx Redis DB index for a QL server port."""
    db = port - 27959
    if db < 0:
        raise ValueError(f"Cannot derive Redis DB for port {port}")
    return db


def _redis_url_for_db(redis_url: str, db: int) -> str:
    """Return a Redis URL with the DB path replaced."""
    parts = urlsplit(redis_url)
    if parts.scheme not in ("redis", "rediss"):
        return redis_url
    return urlunsplit((parts.scheme, parts.netloc, f"/{db}", parts.query, parts.fragment))


def build_player_map(r: redis.Redis, port: int) -> PlayerMap:
    """Read minqlx:server_status:<port> and return {client_udp_port: (steamid, name)}.

    `udp_port` is taken from minqlx's raw `"ip"` player field, so it matches
    the UDP destination port observed by eBPF. Bots expose `udp_port == -1`
    and are excluded. No IP addresses are stored by this tool.
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
        client_port = p.get("udp_port")
        if not client_port or client_port < 0:
            continue  # bot or unknown
        steamid = str(p.get("steam", ""))
        name = _strip_colors(p.get("name", steamid))
        result[client_port] = (steamid, name)

    return result


class PlayerMapper:
    """Manages periodic refresh of per-server client-port player mappings."""

    def __init__(self, redis_url: Optional[str], ports: Iterable[int]):
        self._ports = tuple(sorted(set(ports)))
        self._maps: PlayerMaps = {port: {} for port in self._ports}
        self._redis_by_port: Dict[int, redis.Redis] = {}
        self._last_refresh: float = 0

        if redis_url:
            if len(self._ports) == 1:
                port = self._ports[0]
                self._redis_by_port[port] = redis.from_url(redis_url)
            else:
                for port in self._ports:
                    redis_url_for_port = _redis_url_for_db(redis_url, _redis_db_for_port(port))
                    self._redis_by_port[port] = redis.from_url(redis_url_for_port)

    def refresh(self) -> None:
        if not self._redis_by_port:
            return
        for port, client in self._redis_by_port.items():
            self._maps[port] = build_player_map(client, port)
        self._last_refresh = time.monotonic()

    def maybe_refresh(self) -> None:
        if not self._redis_by_port:
            return
        if time.monotonic() - self._last_refresh >= REFRESH_INTERVAL:
            self.refresh()

    def get_map(self, port: int) -> PlayerMap:
        return self._maps.get(port, {})
