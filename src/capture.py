# src/capture.py
"""BCC-based eBPF loader and map reader for packet capture."""

import socket
import struct
from pathlib import Path
from typing import Dict, List, Tuple

from bcc import BPF
from pyroute2 import IPRoute

BPF_SOURCE = Path(__file__).parent / "bpf_program.c"

IpData = Dict[str, List[Tuple[int, int]]]  # {ip_str: [(size, count), ...]}


def _int_to_ip(addr: int) -> str:
    """Convert a raw u32 from BPF map to dotted IP string.

    BPF stores ip->daddr in network byte order. BCC reads it as a
    native-endian ctypes u32, so we use native pack format.
    """
    return socket.inet_ntoa(struct.pack("I", addr))


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

        # Attach to TC egress using pyroute2
        self._ipr = IPRoute()
        self._ifindex = self._ipr.link_lookup(ifname=self.interface)[0]

        try:
            self._ipr.tc("add", "clsact", self._ifindex)
        except Exception:
            pass  # clsact qdisc may already exist

        self._ipr.tc(
            "add-filter", "bpf", self._ifindex,
            fd=fn.fd, name=fn.name,
            parent=0xFFF0FFF3,  # TC_H_CLSACT | TC_H_MIN_EGRESS
            prio=1,
            classid=1,
            direct_action=True,
        )

    def read_and_clear(self) -> IpData:
        """Read all entries from the packet_counts map and clear it.

        Returns:
            Dict mapping dest IP string to list of (udp_payload_size, count) tuples.
        """
        if self._bpf is None:
            return {}

        table = self._bpf["packet_counts"]
        ip_data: IpData = {}

        for key, val in table.items():
            ip = _int_to_ip(key.dest_ip)
            size = key.size_bucket
            count = val.value
            if ip not in ip_data:
                ip_data[ip] = []
            ip_data[ip].append((size, count))

        table.clear()
        return ip_data

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
