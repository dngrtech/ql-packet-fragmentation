# src/capture.py
"""BCC-based eBPF loader and map reader for packet capture."""

from pathlib import Path
from typing import Dict, List, Tuple

from bcc import BPF
from pyroute2 import IPRoute

BPF_SOURCE = Path(__file__).parent / "bpf_program.c"

PortData = Dict[int, List[Tuple[int, int]]]  # {qport: [(size, count), ...]}


class PacketCapture:
    """Manages eBPF program lifecycle and map reading."""

    def __init__(self, interface: str, port_min: int, port_max: int):
        self.interface = interface
        self.port_min = port_min
        self.port_max = port_max
        self._bpf = None
        self._ipr = None
        self._ifindex = None

    def start(self) -> None:
        """Load BPF program and attach to TC egress via pyroute2."""
        source = BPF_SOURCE.read_text()

        self._bpf = BPF(
            text=source,
            cflags=[f"-DPORT_MIN={self.port_min}", f"-DPORT_MAX={self.port_max}"],
        )
        fn = self._bpf.load_func("classify", BPF.SCHED_CLS)

        self._ipr = IPRoute()
        self._ifindex = self._ipr.link_lookup(ifname=self.interface)[0]

        try:
            self._ipr.tc("add", "clsact", self._ifindex)
        except Exception:
            pass  # clsact qdisc may already exist

        self._ipr.tc(
            "add-filter", "bpf", self._ifindex,
            fd=fn.fd, name=fn.name,
            parent=0xFFFFFFF3,  # TC_H_CLSACT | TC_H_MIN_EGRESS
            prio=1,
            classid=1,
            direct_action=True,
        )

    def read_and_clear(self) -> PortData:
        """Read all entries from the packet_counts map and clear it.

        Returns:
            Dict mapping client qport to list of (udp_payload_size, count) tuples.
        """
        if self._bpf is None:
            return {}

        table = self._bpf["packet_counts"]
        port_data: PortData = {}

        for key, val in table.items():
            qport = key.dest_port
            size = key.size_bucket
            count = val.value
            if qport not in port_data:
                port_data[qport] = []
            port_data[qport].append((size, count))

        table.clear()
        return port_data

    def stop(self) -> None:
        """Detach TC filter and clean up."""
        if self._ipr and self._ifindex:
            try:
                self._ipr.tc("del", "clsact", self._ifindex)
            except Exception:
                pass
            self._ipr.close()
            self._ipr = None
        if self._bpf is not None:
            self._bpf.cleanup()
            self._bpf = None
