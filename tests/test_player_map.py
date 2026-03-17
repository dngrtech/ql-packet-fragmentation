# tests/test_player_map.py
import json
from unittest.mock import MagicMock, call, patch
from src.player_map import build_player_map, PlayerMapper


class TestBuildPlayerMap:
    def _make_redis(self, players):
        mock_r = MagicMock()
        mock_r.get.return_value = json.dumps({
            "port": "27962",
            "players": players,
        }).encode()
        return mock_r

    def test_single_real_player(self):
        r = self._make_redis([
            {"name": "rage^7", "steam": "76561199795317792", "udp_port": 20725, "team": "spectator"},
        ])
        result = build_player_map(r, 27962)
        assert result == {20725: ("76561199795317792", "rage")}

    def test_bots_excluded(self):
        r = self._make_redis([
            {"name": "Bot^7", "steam": "90071996842377216", "udp_port": -1, "team": "red"},
            {"name": "rage^7", "steam": "76561199795317792", "udp_port": 20725, "team": "spectator"},
        ])
        result = build_player_map(r, 27962)
        assert len(result) == 1
        assert 20725 in result
        assert -1 not in result

    def test_color_codes_stripped(self):
        r = self._make_redis([
            {"name": "^1A^2n^3a^4r^5k^6i^7", "steam": "76561198000000001", "udp_port": 12345, "team": "red"},
        ])
        result = build_player_map(r, 27962)
        assert result[12345][1] == "Anarki"

    def test_missing_key_returns_empty(self):
        mock_r = MagicMock()
        mock_r.get.return_value = None
        result = build_player_map(mock_r, 27962)
        assert result == {}

    def test_multiple_real_players(self):
        r = self._make_redis([
            {"name": "rage^7", "steam": "76561199795317792", "udp_port": 20725, "team": "spectator"},
            {"name": "rin^7",  "steam": "76561198771411283", "udp_port": 56650, "team": "red"},
            {"name": "Bot^7",  "steam": "90071996842377216", "udp_port": -1,    "team": "blue"},
        ])
        result = build_player_map(r, 27962)
        assert len(result) == 2
        assert result[20725] == ("76561199795317792", "rage")
        assert result[56650] == ("76561198771411283", "rin")


class TestPlayerMapper:
    def test_disabled_when_no_redis_url(self):
        mapper = PlayerMapper(redis_url=None, ports=[27962, 27963])
        assert mapper.get_map(27962) == {}
        assert mapper.get_map(27963) == {}

    def test_refresh_calls_build(self):
        with patch("src.player_map.build_player_map") as mock_build:
            mock_build.return_value = {20725: ("76561199795317792", "rage")}
            with patch("src.player_map.redis.from_url"):
                mapper = PlayerMapper(redis_url="redis://localhost:6379/3", ports=[27962])
                mapper.refresh()
                assert mapper.get_map(27962) == {20725: ("76561199795317792", "rage")}

    def test_multi_port_uses_derived_redis_dbs(self):
        with patch("src.player_map.redis.from_url") as mock_from_url:
            PlayerMapper(
                redis_url="redis://localhost:6379/3",
                ports=[27960, 27962],
            )
        assert mock_from_url.call_args_list == [
            call("redis://localhost:6379/1"),
            call("redis://localhost:6379/3"),
        ]

    def test_refresh_builds_map_per_server_port(self):
        with patch("src.player_map.redis.from_url") as mock_from_url:
            client_27960 = MagicMock()
            client_27962 = MagicMock()
            mock_from_url.side_effect = [client_27960, client_27962]
            mapper = PlayerMapper(
                redis_url="redis://localhost:6379/3",
                ports=[27960, 27962],
            )

        with patch("src.player_map.build_player_map") as mock_build:
            mock_build.side_effect = [
                {11111: ("76561198000000001", "anarki")},
                {22222: ("76561198000000002", "visor")},
            ]
            mapper.refresh()

        assert mock_build.call_args_list == [
            call(client_27960, 27960),
            call(client_27962, 27962),
        ]
        assert mapper.get_map(27960) == {11111: ("76561198000000001", "anarki")}
        assert mapper.get_map(27962) == {22222: ("76561198000000002", "visor")}
