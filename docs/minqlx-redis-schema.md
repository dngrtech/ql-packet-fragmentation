# minqlx Redis Data Schema

## Primary Key Used by This Tool

This tool reads the live server status key written by the bundled
`minqlx-plugins/serverchecker.py` plugin.

The Redis DB index is `server_port - 27959` (for example, port `27962` uses
DB `3`).

### Key Pattern

```
minqlx:server_status:<port>  → JSON document
```

### Example Query

```bash
# Get live status for port 27962
redis-cli -n 3 get minqlx:server_status:27962
```

### JSON Shape

Example fields used by the capture tool:

```json
{
  "port": "27962",
  "players": [
    {
      "name": "rage^7",
      "steam": "76561199795317792",
      "udp_port": 20725,
      "team": "spectator"
    }
  ],
  "updated": 1760000000
}
```

### Player Correlation

Player correlation is done by UDP port, not IP and not Quake protocol `qport`:

1. eBPF records outbound packets by destination UDP port.
2. `serverchecker` writes each live player's `udp_port` from minqlx's raw
   `"ip"` player field.
3. Userspace builds an in-memory map:

   `{udp_port: (steamid, stripped_name)}`

4. Bots and unknown players are excluded because their `udp_port` is missing or
   negative.

No IP addresses are stored by this tool.

## Legacy minqlx Player Keys

minqlx also keeps persistent per-player keys such as:

```text
minqlx:players:<steamid>
minqlx:players:<steamid>:last_seen
```

Those keys are not required by the current capture path.

## Important Notes

- Redis DB: `instance_port - 27959` (verified via `qlx_redisDatabase` cvar)
- Redis default port: 6379, localhost
- `udp_port` must be present in `minqlx:server_status:<port>` for per-player
  packet attribution to work
- In multi-server capture mode, the collector reuses the `--redis-url`
  host/port/credentials and derives the DB index from each server port
