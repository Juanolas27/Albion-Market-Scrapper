from __future__ import annotations

from dataclasses import dataclass, field

import psutil

from albion_capture.core.logging import get_logger

log = get_logger("port_detector")

ALBION_PROCESS_NAME = "Albion-Online.exe"
GAME_SERVER_PORT = 5056


@dataclass
class AlbionClient:
    pid: int
    local_ports: list[int] = field(default_factory=list)


def find_albion_clients() -> list[AlbionClient]:
    """Find all running Albion Online clients and their UDP ports."""
    clients: list[AlbionClient] = []

    for proc in psutil.process_iter(["pid", "name"]):
        try:
            name = proc.info["name"]
            if not name or ALBION_PROCESS_NAME.lower() not in name.lower():
                continue

            connections = proc.net_connections(kind="udp")
            udp_ports = [conn.laddr.port for conn in connections if conn.laddr]

            if udp_ports:
                clients.append(
                    AlbionClient(pid=proc.info["pid"], local_ports=udp_ports)
                )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    log.info("albion_clients_detected", count=len(clients))
    for client in clients:
        log.info("client_found", pid=client.pid, udp_ports=client.local_ports)

    return clients


def detect_and_assign_ports(workers_config: list[dict]) -> list[dict]:
    """Auto-detect ports for workers that have local_port=None.

    Each worker gets assigned ALL ports of its corresponding Albion client
    (stored as 'local_ports' list). The sniffer will build a BPF filter
    covering all of them.
    """
    clients = find_albion_clients()
    unassigned = [w for w in workers_config if not w.get("local_port")]

    if not unassigned:
        log.info("all_ports_manually_assigned")
        return workers_config

    if len(clients) == 0:
        log.warning("no_albion_clients_found")
        return workers_config

    if len(clients) == 1 and len(unassigned) >= 1:
        # Single client: assign to the first unassigned worker,
        # store all ports so the sniffer covers all of them
        client = clients[0]
        worker = unassigned[0]
        worker["local_ports"] = client.local_ports
        worker["local_port"] = client.local_ports[0]  # primary
        log.info(
            "single_client_assigned",
            city=worker["city"],
            ports=client.local_ports,
            pid=client.pid,
        )
        return workers_config

    if len(clients) == len(unassigned):
        for worker, client in zip(unassigned, clients):
            worker["local_ports"] = client.local_ports
            worker["local_port"] = client.local_ports[0]
            log.info(
                "port_assigned",
                city=worker["city"],
                ports=client.local_ports,
                pid=client.pid,
            )
        return workers_config

    log.warning(
        "port_auto_assign_mismatch",
        unassigned_workers=len(unassigned),
        available_clients=len(clients),
    )
    return workers_config
