from src.influx_writer import InfluxWriter, build_records


class TestBuildRecords:
    def test_server_record_shape(self):
        stats = {
            "total_packets": 10,
            "fragmented_packets": 2,
            "avg_size": 1000.0,
            "max_size": 1500,
            "buckets": [0, 5, 3, 2],
            "per_port": {},
        }
        records = build_records(
            server_port=27962,
            stats=stats,
            rate_setting="99k",
            host_tag="test-host",
        )
        assert len(records) == 1
        record = records[0]
        assert record["measurement"] == "packet_stats"
        assert record["tags"]["server_port"] == "27962"
        assert record["tags"]["rate_setting"] == "99k"
        assert record["tags"]["host"] == "test-host"
        assert record["fields"]["fragmented_packets"] == 2
        assert record["fields"]["fragmentation_pct"] == 20.0
        assert record["fields"]["bucket_1473_plus"] == 2

    def test_player_records_only_for_mapped_ports(self):
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
                56651: {
                    "total_packets": 1,
                    "fragmented_packets": 0,
                    "avg_size": 100.0,
                    "max_size": 100,
                },
            },
        }
        player_map = {56650: ("76561197960700239", "testplayer")}
        records = build_records(
            server_port=27962,
            stats=stats,
            player_map=player_map,
            host_tag="test-host",
        )
        assert len(records) == 2
        player_record = records[1]
        assert player_record["measurement"] == "player_packets"
        assert player_record["tags"]["steam_id"] == "76561197960700239"
        assert player_record["tags"]["player_name"] == "testplayer"
        assert player_record["fields"]["client_udp_port"] == 56650
        assert player_record["fields"]["fragmentation_pct"] == 20.0


class TestInfluxWriter:
    def test_disabled_when_not_configured(self):
        writer = InfluxWriter()
        assert writer.enabled is False

