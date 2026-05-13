"""Packet capture using Scapy with BPF filtering per worker."""
from __future__ import annotations

from typing import Callable

from scapy.all import AsyncSniffer, UDP, IP, Raw, conf

from albion_capture.core.logging import get_logger

log = get_logger("sniffer")

PacketCallback = Callable[[bytes, str, int, str, int], None]


def find_real_interface() -> str | None:
    """Find the real network interface (not virtual/loopback/VPN)."""
    keywords_skip = [
        "loopback", "hyper-v", "openvpn", "tap-windows", "wintun", "wan miniport",
        "virtualbox", "vbox", "vmware", "host-only", "virtual",
    ]
    keywords_want = ["realtek", "intel", "ethernet", "wi-fi", "wireless"]

    for iface_name, iface in conf.ifaces.items():
        desc = ""
        if hasattr(iface, "description"):
            desc = iface.description.lower()
        elif hasattr(iface, "name"):
            desc = iface.name.lower()

        if any(kw in desc for kw in keywords_skip):
            continue

        if any(kw in desc for kw in keywords_want):
            log.info("auto_detected_interface", name=iface_name, description=desc)
            return iface_name

    return None


class AlbionSniffer:
    """Captures UDP packets on the Albion game port."""

    def __init__(
        self,
        game_port: int = 5056,
        local_ports: list[int] | None = None,
        callback: PacketCallback | None = None,
        iface: str | None = None,
    ):
        self.game_port = game_port
        self.local_ports = local_ports or []
        self.callback = callback
        self.iface = iface or find_real_interface()
        self._sniffer: AsyncSniffer | None = None
        self._packet_count = 0

    def _build_bpf_filter(self) -> str:
        """Build BPF filter string."""
        if self.local_ports:
            # Filter for game port AND any of the local ports
            port_filters = " or ".join(
                f"src port {p} or dst port {p}" for p in self.local_ports
            )
            return f"udp port {self.game_port} and ({port_filters})"
        return f"udp port {self.game_port}"

    def start(self) -> None:
        bpf = self._build_bpf_filter()
        log.info("sniffer_starting", bpf_filter=bpf, iface=self.iface)

        kwargs = {
            "filter": bpf,
            "prn": self._process_packet,
            "store": False,
        }
        if self.iface:
            kwargs["iface"] = self.iface

        self._sniffer = AsyncSniffer(**kwargs)
        self._sniffer.start()
        log.info("sniffer_started")

    def stop(self) -> None:
        if self._sniffer:
            self._sniffer.stop()
            log.info("sniffer_stopped", packets_captured=self._packet_count)

    @property
    def packet_count(self) -> int:
        return self._packet_count

    def _process_packet(self, packet) -> None:
        try:
            if not packet.haslayer(UDP) or not packet.haslayer(Raw):
                return

            ip_layer = packet[IP]
            udp_layer = packet[UDP]
            raw_data = bytes(packet[Raw].load)

            self._packet_count += 1

            if self._packet_count <= 3:
                log.info(
                    "packet_captured",
                    src=f"{ip_layer.src}:{udp_layer.sport}",
                    dst=f"{ip_layer.dst}:{udp_layer.dport}",
                    size=len(raw_data),
                )

            if self.callback:
                self.callback(
                    raw_data,
                    ip_layer.src,
                    udp_layer.sport,
                    ip_layer.dst,
                    udp_layer.dport,
                )
        except Exception as e:
            log.debug("packet_process_error", error=str(e))
