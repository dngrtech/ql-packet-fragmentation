# minqlx Redis Data Schema

## Player Data (used for name lookup only)

minqlx stores player information in the existing Redis instance on each Quake Live server.
The Redis DB index is `server_port - 27959` (e.g. port 27962 → db3).

### Key Patterns

```
minqlx:players:<steamid>            → list   (player name at index 0)
minqlx:players:<steamid>:last_seen  → string (Unix timestamp)
```

### Example Queries

```bash
# Get player name by steamid
redis-cli -n 3 LINDEX minqlx:players:76561197960700239 0
```

### Player Correlation

Player → packet correlation is done by steamid only. IP addresses are **never stored**.

The transient IP→steamid mapping is obtained via rcon `status` at each capture interval:
1. Send rcon `status` to the QL server
2. Parse the response to get `(ip, steamid)` for currently connected players
3. Use this mapping in-memory for the duration of the interval
4. Discard after use — never written to disk or database

The player's display name is then fetched from Redis using the steamid.

### Important Notes

- Redis DB: `instance_port - 27959` (verified via `qlx_redisDatabase` cvar)
- Redis default port: 6379, localhost
- IP addresses are not read from or written to Redis by this tool
