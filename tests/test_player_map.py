# tests/test_player_map.py
import json
from unittest.mock import MagicMock, patch
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
            {"name": "rage^7", "steam": "76561199795317792", "qport": 20725, "team": "spectator"},
        ])
        result = build_player_map(r, 27962)
        assert result == {20725: ("76561199795317792", "rage")}

    def test_bots_excluded(self):
        r = self._make_redis([
            {"name": "Bot^7", "steam": "90071996842377216", "qport": -1, "team": "red"},
            {"name": "rage^7", "steam": "76561199795317792", "qport": 20725, "team": "spectator"},
        ])
        result = build_player_map(r, 27962)
        assert len(result) == 1
        assert 20725 in result
        assert -1 not in result

    def test_color_codes_stripped(self):
        r = self._make_redis([
            {"name": "^1A^2n^3a^4r^5k^6i^7", "steam": "76561198000000001", "qport": 12345, "team": "red"},
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
            {"name": "rage^7", "steam": "76561199795317792", "qport": 20725, "team": "spectator"},
            {"name": "rin^7",  "steam": "76561198771411283", "qport": 56650, "team": "red"},
            {"name": "Bot^7",  "steam": "90071996842377216", "qport": -1,    "team": "blue"},
        ])
        result = build_player_map(r, 27962)
        assert len(result) == 2
        assert result[20725] == ("76561199795317792", "rage")
        assert result[56650] == ("76561198771411283", "rin")


class TestPlayerMapper:
    def test_disabled_when_no_redis_url(self):
        mapper = PlayerMapper(redis_url=None, port=27962)
        assert mapper.get_map() == {}

    def test_refresh_calls_build(self):
        with patch("src.player_map.build_player_map") as mock_build:
            mock_build.return_value = {20725: ("76561199795317792", "rage")}
            with patch("src.player_map.redis.from_url"):
                mapper = PlayerMapper(redis_url="redis://localhost:6379/3", port=27962)
                mapper.refresh()
                assert mapper.get_map() == {20725: ("76561199795317792", "rage")}
