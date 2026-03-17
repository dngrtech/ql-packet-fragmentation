# tests/test_player_map.py
from unittest.mock import MagicMock, patch
from src.player_map import build_reverse_index, PlayerMapper


class TestBuildReverseIndex:
    def test_single_player_single_ip(self):
        mock_redis = MagicMock()
        mock_redis.scan_iter.return_value = [b"minqlx:players:12345:ips"]
        mock_redis.smembers.return_value = {b"10.0.0.1"}
        mock_redis.lindex.return_value = b"TestPlayer"

        result = build_reverse_index(mock_redis)
        assert result == {"10.0.0.1": ("12345", "TestPlayer")}

    def test_player_multiple_ips(self):
        mock_redis = MagicMock()
        mock_redis.scan_iter.return_value = [b"minqlx:players:12345:ips"]
        mock_redis.smembers.return_value = {b"10.0.0.1", b"10.0.0.2"}
        mock_redis.lindex.return_value = b"TestPlayer"

        result = build_reverse_index(mock_redis)
        assert result["10.0.0.1"] == ("12345", "TestPlayer")
        assert result["10.0.0.2"] == ("12345", "TestPlayer")

    def test_no_players(self):
        mock_redis = MagicMock()
        mock_redis.scan_iter.return_value = []

        result = build_reverse_index(mock_redis)
        assert result == {}

    def test_player_with_no_name(self):
        mock_redis = MagicMock()
        mock_redis.scan_iter.return_value = [b"minqlx:players:12345:ips"]
        mock_redis.smembers.return_value = {b"10.0.0.1"}
        mock_redis.lindex.return_value = None

        result = build_reverse_index(mock_redis)
        assert result == {"10.0.0.1": ("12345", "unknown")}


class TestPlayerMapper:
    def test_disabled_when_no_url(self):
        mapper = PlayerMapper(redis_url=None)
        assert mapper.get_map() == {}

    def test_refresh_calls_build(self):
        with patch("src.player_map.build_reverse_index") as mock_build:
            mock_build.return_value = {"10.0.0.1": ("123", "Player")}
            with patch("src.player_map.redis.from_url"):
                mapper = PlayerMapper(redis_url="redis://localhost:6379/0")
                mapper.refresh()
                assert mapper.get_map() == {"10.0.0.1": ("123", "Player")}
