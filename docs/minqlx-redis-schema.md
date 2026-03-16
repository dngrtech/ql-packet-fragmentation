# minqlx Redis Data Schema

## Player Data (used for packet → player correlation)

minqlx stores player information in the existing Redis instance on each Quake Live server.

### Key Patterns

```
minqlx:players:<steamid>            → list   (player name at index 0)
minqlx:players:<steamid>:ips        → set    (all known IP addresses)
minqlx:players:<steamid>:last_seen  → string (Unix timestamp)
```

### Example Queries

```bash
# Get player name
redis-cli LINDEX minqlx:players:76561197960700239 0

# Get all known IPs for a player
redis-cli SMEMBERS minqlx:players:76561197960700239:ips

# Get last seen timestamp
redis-cli GET minqlx:players:76561197960700239:last_seen
```

### Building the Reverse Index

To correlate packets with players, we build a reverse mapping at capture start:

1. Scan all keys matching `minqlx:players:*:ips`
2. For each key, extract the steamid from the key name
3. Get the player name from `minqlx:players:<steamid>` (LINDEX 0)
4. Get all IPs from the set
5. Build: `{ip_address: (steamid, player_name)}`

Refresh this mapping every 60 seconds to catch players joining/leaving.

### Important Notes

- IPs in the `:ips` set are accumulated over time (all IPs ever used by that player)
- For accurate per-match correlation, cross-reference with the current server's connected players
- Redis default port: 6379, localhost
- minqlx may use a specific Redis DB number (check server config)
