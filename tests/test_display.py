# tests/test_display.py
from src.display import format_stats, format_histogram_bar


class TestFormatHistogramBar:
    def test_zero_total(self):
        assert format_histogram_bar(0, 0) == ""

    def test_full_bar(self):
        bar = format_histogram_bar(100, 100)
        assert len(bar) == 40  # default width
        assert bar == "#" * 40

    def test_half_bar(self):
        bar = format_histogram_bar(50, 100)
        assert len(bar) == 20
        assert bar == "#" * 20

    def test_custom_width(self):
        bar = format_histogram_bar(25, 100, width=20)
        assert len(bar) == 5


class TestFormatStats:
    def test_basic_output_contains_key_info(self):
        stats = {
            "total_packets": 100,
            "fragmented_packets": 10,
            "avg_size": 800.5,
            "max_size": 1600,
            "buckets": [40, 30, 20, 10],
            "per_port": {},
        }
        output = format_stats(stats)
        assert "100" in output
        assert "10.0%" in output
        assert "800" in output
        assert "1600" in output

    def test_zero_packets(self):
        stats = {
            "total_packets": 0,
            "fragmented_packets": 0,
            "avg_size": 0.0,
            "max_size": 0,
            "buckets": [0, 0, 0, 0],
            "per_port": {},
        }
        output = format_stats(stats)
        assert "0" in output
        assert "No packets" in output

    def test_per_player_included(self):
        stats = {
            "total_packets": 10,
            "fragmented_packets": 2,
            "avg_size": 1000.0,
            "max_size": 1500,
            "buckets": [0, 5, 3, 2],
            "per_port": {
                56650: {
                    "total_packets": 10,
                    "fragmented_packets": 2,
                    "avg_size": 1000.0,
                    "max_size": 1500,
                },
            },
        }
        player_map = {56650: ("76561197960700239", "testplayer")}
        output = format_stats(stats, player_map=player_map)
        assert "testplayer" in output
        assert "76561197960700239" in output
        assert "20.0%" in output
