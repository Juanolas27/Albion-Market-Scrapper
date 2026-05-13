"""Quick test to verify packet capture works and find Albion traffic."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scapy.all import sniff, UDP, IP, Raw, conf

print("=" * 60)
print("  Albion Traffic Test")
print("=" * 60)
print()

# Check Npcap
print(f"Scapy backend: {conf.use_pcap}")
print(f"Available interfaces:")
for iface_name, iface in conf.ifaces.items():
    print(f"  - {iface_name}: {iface.description if hasattr(iface, 'description') else iface}")
print()

# Try capturing ALL UDP traffic for 15 seconds
print("Capturing ALL UDP traffic for 15 seconds...")
print(">>> Open the market in Albion and search for any item! <<<")
print()

packets = sniff(filter="udp", timeout=15, count=100)

print(f"\nCaptured {len(packets)} UDP packets total")
print()

# Group by port
port_counts = {}
albion_packets = []
for pkt in packets:
    if pkt.haslayer(UDP):
        sport = pkt[UDP].sport
        dport = pkt[UDP].dport
        key = f"{sport} -> {dport}"
        port_counts[key] = port_counts.get(key, 0) + 1

        # Check if any port is 5056 or matches Albion's known ports
        if sport == 5056 or dport == 5056:
            albion_packets.append(pkt)
        elif sport in (63063, 52219, 61075) or dport in (63063, 52219, 61075):
            albion_packets.append(pkt)

print("Port pairs (top 20):")
for pair, count in sorted(port_counts.items(), key=lambda x: -x[1])[:20]:
    marker = " <<< ALBION?" if "5056" in pair or "63063" in pair or "52219" in pair or "61075" in pair else ""
    print(f"  {pair}: {count} packets{marker}")

print(f"\nAlbion-related packets: {len(albion_packets)}")

if albion_packets:
    print("\nFirst Albion packet details:")
    pkt = albion_packets[0]
    print(f"  {pkt[IP].src}:{pkt[UDP].sport} -> {pkt[IP].dst}:{pkt[UDP].dport}")
    if pkt.haslayer(Raw):
        print(f"  Payload size: {len(pkt[Raw].load)} bytes")
        print(f"  First 32 bytes: {pkt[Raw].load[:32].hex()}")
