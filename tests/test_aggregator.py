# tests/test_aggregator.py
import pytest
from src.aggregator import aggregate_packets, FRAG_THRESHOLD

# Bucket boundaries: [0, 500), [500, 1000), [1000, 1472], (1472, +inf)


class TestAggregatePackets:
    def test_empty_input(self):
        result = aggregate_packets({})
        assert result["total_packets"] == 0
        assert result["fragmented_packets"] == 0
        assert result["avg_size"] == 0.0
        assert result["max_size"] == 0
        assert result["buckets"] == [0, 0, 0, 0]

    def test_single_small_packet(self):
        # ip_data: {dest_ip: [(size, count), ...]}
        ip_data = {"10.0.0.1": [(400, 5)]}
        result = aggregate_packets(ip_data)
        assert result["total_packets"] == 5
        assert result["fragmented_packets"] == 0
        assert result["avg_size"] == 400.0
        assert result["max_size"] == 400
        assert result["buckets"] == [5, 0, 0, 0]

    def test_fragmented_packets(self):
        ip_data = {"10.0.0.1": [(1500, 3)]}
        result = aggregate_packets(ip_data)
        assert result["total_packets"] == 3
        assert result["fragmented_packets"] == 3
        assert result["avg_size"] == 1500.0
        assert result["max_size"] == 1500
        assert result["buckets"] == [0, 0, 0, 3]

    def test_boundary_exactly_1472(self):
        ip_data = {"10.0.0.1": [(FRAG_THRESHOLD, 1)]}
        result = aggregate_packets(ip_data)
        # Exactly 1472 is NOT fragmented (fits in one MTU)
        assert result["fragmented_packets"] == 0
        assert result["buckets"] == [0, 0, 1, 0]

    def test_boundary_1473(self):
        ip_data = {"10.0.0.1": [(1473, 1)]}
        result = aggregate_packets(ip_data)
        assert result["fragmented_packets"] == 1
        assert result["buckets"] == [0, 0, 0, 1]

    def test_multiple_ips_mixed(self):
        ip_data = {
            "10.0.0.1": [(200, 10), (800, 5)],
            "10.0.0.2": [(1200, 3), (1500, 2)],
        }
        result = aggregate_packets(ip_data)
        assert result["total_packets"] == 20
        assert result["fragmented_packets"] == 2
        # avg = (200*10 + 800*5 + 1200*3 + 1500*2) / 20 = (2000+4000+3600+3000)/20 = 630
        assert result["avg_size"] == 630.0
        assert result["max_size"] == 1500
        assert result["buckets"] == [10, 5, 3, 2]

    def test_per_ip_breakdown(self):
        ip_data = {
            "10.0.0.1": [(400, 5)],
            "10.0.0.2": [(1500, 3)],
        }
        result = aggregate_packets(ip_data)
        per_ip = result["per_ip"]
        assert per_ip["10.0.0.1"]["total_packets"] == 5
        assert per_ip["10.0.0.1"]["fragmented_packets"] == 0
        assert per_ip["10.0.0.2"]["total_packets"] == 3
        assert per_ip["10.0.0.2"]["fragmented_packets"] == 3
