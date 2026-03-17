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
        # port_data: {client_udp_port: [(size, count), ...]}
        port_data = {56650: [(400, 5)]}
        result = aggregate_packets(port_data)
        assert result["total_packets"] == 5
        assert result["fragmented_packets"] == 0
        assert result["avg_size"] == 400.0
        assert result["max_size"] == 400
        assert result["buckets"] == [5, 0, 0, 0]

    def test_fragmented_packets(self):
        port_data = {56650: [(1500, 3)]}
        result = aggregate_packets(port_data)
        assert result["total_packets"] == 3
        assert result["fragmented_packets"] == 3
        assert result["avg_size"] == 1500.0
        assert result["max_size"] == 1500
        assert result["buckets"] == [0, 0, 0, 3]

    def test_boundary_exactly_1472(self):
        port_data = {56650: [(FRAG_THRESHOLD, 1)]}
        result = aggregate_packets(port_data)
        # Exactly 1472 is NOT fragmented (fits in one MTU)
        assert result["fragmented_packets"] == 0
        assert result["buckets"] == [0, 0, 1, 0]

    def test_boundary_1473(self):
        port_data = {56650: [(1473, 1)]}
        result = aggregate_packets(port_data)
        assert result["fragmented_packets"] == 1
        assert result["buckets"] == [0, 0, 0, 1]

    def test_multiple_ports_mixed(self):
        port_data = {
            56650: [(200, 10), (800, 5)],
            56651: [(1200, 3), (1500, 2)],
        }
        result = aggregate_packets(port_data)
        assert result["total_packets"] == 20
        assert result["fragmented_packets"] == 2
        # avg = (200*10 + 800*5 + 1200*3 + 1500*2) / 20 = (2000+4000+3600+3000)/20 = 630
        assert result["avg_size"] == 630.0
        assert result["max_size"] == 1500
        assert result["buckets"] == [10, 5, 3, 2]

    def test_per_port_breakdown(self):
        port_data = {
            56650: [(400, 5)],
            56651: [(1500, 3)],
        }
        result = aggregate_packets(port_data)
        per_port = result["per_port"]
        assert per_port[56650]["total_packets"] == 5
        assert per_port[56650]["fragmented_packets"] == 0
        assert per_port[56651]["total_packets"] == 3
        assert per_port[56651]["fragmented_packets"] == 3
