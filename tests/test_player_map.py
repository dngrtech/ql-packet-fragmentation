# tests/test_player_map.py
from unittest.mock import MagicMock, patch
from src.player_map import _parse_status, _lookup_name, PlayerMapper


class TestParseStatus:
    def test_single_player(self):
        status = "rage^7                  0 127.0.0.1:56650       20725 99999 76561199795317792"
        result = _parse_status(status)
        assert result == {56650: ("76561199795317792", "rage^7")}

    def test_multiple_players(self):
        status = (
            "rage^7                  0 127.0.0.1:56650       20725 99999 76561199795317792\n"
            "rin^7                   5 127.0.0.1:12345       80    25000 76561198771411283"
        )
        result = _parse_status(status)
        assert result[56650] == ("76561199795317792", "rage^7")
        assert result[12345] == ("76561198771411283", "rin^7")

    def test_empty_status(self):
        assert _parse_status("") == {}

    def test_non_player_lines_ignored(self):
        status = "map: campgrounds\nrage^7                  0 127.0.0.1:56650       20725 99999 76561199795317792"
        result = _parse_status(status)
        assert len(result) == 1
        assert 56650 in result


class TestLookupName:
    def test_name_found(self):
        mock_redis = MagicMock()
        mock_redis.lindex.return_value = b"rage^7"
        assert _lookup_name(mock_redis, "76561199795317792") == "rage^7"

    def test_name_not_found(self):
        mock_redis = MagicMock()
        mock_redis.lindex.return_value = None
        assert _lookup_name(mock_redis, "76561199795317792") == "76561199795317792"


class TestPlayerMapper:
    def test_disabled_when_no_rcon_password(self):
        mapper = PlayerMapper(
            rcon_host="127.0.0.1", rcon_port=27962, rcon_password=None
        )
        assert mapper.get_map() == {}

    def test_refresh_calls_build(self):
        with patch("src.player_map.build_player_map") as mock_build:
            mock_build.return_value = {56650: ("76561199795317792", "rage^7")}
            mapper = PlayerMapper(
                rcon_host="127.0.0.1", rcon_port=27962, rcon_password="secret"
            )
            mapper.refresh()
            assert mapper.get_map() == {56650: ("76561199795317792", "rage^7")}
