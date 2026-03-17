# src/player_map.py
"""Player mapping via rcon status — transient, in-memory only. No IPs stored."""

import re
import socket
import time
from typing import Dict, Optional, Tuple

import redis

REFRESH_INTERVAL = 30  # seconds — rcon on every interval for accuracy

PlayerMap = Dict[int, Tuple[str, str]]  # {qport: (steamid, name)}

# rcon status line: name  score  127.0.0.1:port  ping  rate  steamid
_STATUS_RE = re.compile(
    r"^(.+?)\s+\d+\s+127\.0\.0\.1:(\d+)\s+\d+\s+\d+\s+(\d{17})\s*$"
)

RCON_HEADER = b"\xff\xff\xff\xff"


def _rcon_status(host: str, port: int, password: str, timeout: float = 2.0) -> str:
    """Send rcon status to QL server, return response string."""
    cmd = RCON_HEADER + f"rcon {password} status\n".encode()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(cmd, (host, port))
        data, _ = sock.recvfrom(4096)
        # Strip header: \xff\xff\xff\xffprint\n
        return data[len(RCON_HEADER):].decode(errors="replace").lstrip("print\n")
    except (socket.timeout, OSError):
        return ""
    finally:
        sock.close()


def _parse_status(status: str) -> Dict[int, Tuple[str, str]]:
    """Parse rcon status output into {qport: (steamid, name)}."""
    result: PlayerMap = {}
    for line in status.splitlines():
        m = _STATUS_RE.match(line.strip())
        if m:
            name = m.group(1).strip()
            qport = int(m.group(2))
            steamid = m.group(3)
            result[qport] = (steamid, name)
    return result


def _lookup_name(r: redis.Redis, steamid: str) -> str:
    """Get player display name from Redis by steamid."""
    name_bytes = r.lindex(f"minqlx:players:{steamid}", 0)
    return name_bytes.decode(errors="replace") if name_bytes else steamid


def build_player_map(
    rcon_host: str, rcon_port: int, rcon_password: str,
    redis_client: Optional[redis.Redis],
) -> PlayerMap:
    """Build transient {qport: (steamid, name)} from rcon status + Redis name lookup."""
    status = _rcon_status(rcon_host, rcon_port, rcon_password)
    players = _parse_status(status)

    if redis_client:
        # Freshen names from Redis (rcon name may have color codes stripped differently)
        for qport, (steamid, _) in players.items():
            name = _lookup_name(redis_client, steamid)
            players[qport] = (steamid, name)

    return players


class PlayerMapper:
    """Manages periodic refresh of the qport -> player mapping."""

    def __init__(
        self,
        rcon_host: str,
        rcon_port: int,
        rcon_password: Optional[str],
        redis_url: Optional[str] = None,
    ):
        self._rcon_host = rcon_host
        self._rcon_port = rcon_port
        self._rcon_password = rcon_password
        self._map: PlayerMap = {}
        self._redis: Optional[redis.Redis] = None
        self._last_refresh: float = 0

        if redis_url:
            self._redis = redis.from_url(redis_url)

    def refresh(self) -> None:
        """Rebuild the player map from rcon status."""
        if not self._rcon_password:
            return
        self._map = build_player_map(
            self._rcon_host, self._rcon_port, self._rcon_password, self._redis
        )
        self._last_refresh = time.monotonic()

    def maybe_refresh(self) -> None:
        """Refresh if REFRESH_INTERVAL has elapsed."""
        if not self._rcon_password:
            return
        if time.monotonic() - self._last_refresh >= REFRESH_INTERVAL:
            self.refresh()

    def get_map(self) -> PlayerMap:
        return self._map
