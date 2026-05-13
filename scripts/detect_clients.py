"""Utility script to detect running Albion Online clients and their UDP ports."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from albion_capture.capture.port_detector import find_albion_clients
from albion_capture.core.logging import setup_logging


def main() -> None:
    setup_logging()

    print("=" * 60)
    print("  Albion Online Client Detector")
    print("=" * 60)
    print()
    print("Searching for running Albion-Online.exe processes...")
    print()

    clients = find_albion_clients()

    if not clients:
        print("No Albion Online clients detected.")
        print()
        print("Make sure:")
        print("  1. Albion Online is running")
        print("  2. You are logged in and connected to a server")
        print("  3. This script is running with administrator privileges")
        return

    print(f"Found {len(clients)} client(s):")
    print()
    print(f"{'PID':<10} {'UDP Ports'}")
    print("-" * 40)

    for client in clients:
        ports_str = ", ".join(str(p) for p in client.local_ports)
        print(f"{client.pid:<10} {ports_str}")

    print()
    print("Copy the local ports to config/settings.yaml and assign each to a city.")
    print()
    print("Example config:")
    print()

    cities = [
        "Bridgewatch", "Fort Sterling", "Lymhurst", "Martlock",
        "Thetford", "Caerleon", "Black Market", "Brecilien",
    ]

    for i, client in enumerate(clients):
        city = cities[i] if i < len(cities) else f"City {i + 1}"
        print(f"  - city: {city}")
        print(f"    local_port: {client.local_port}")
        print()


if __name__ == "__main__":
    main()
