"""Test: capture Albion packets and try to decode them in real-time."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scapy.all import sniff, UDP, IP, Raw, conf

from albion_capture.photon.decoder import PhotonDecoder
from albion_capture.photon.operations import OperationCodes

# List all interfaces and pick the right one
print("Available interfaces:")
for iface_name, iface_obj in conf.ifaces.items():
    desc = getattr(iface_obj, "description", "").lower()
    print(f"  {iface_name}: {desc}")

# Force Realtek interface
iface = None
for iface_name, iface_obj in conf.ifaces.items():
    desc = getattr(iface_obj, "description", "").lower()
    if "realtek" in desc:
        iface = iface_name
        print(f"\n>>> Using: {desc}")
        break

if not iface:
    # When Hyper-V is enabled, all traffic goes through the Hyper-V virtual switch
    for iface_name, iface_obj in conf.ifaces.items():
        desc = getattr(iface_obj, "description", "").lower()
        if "hyper-v" in desc:
            iface = iface_name
            print(f"\n>>> Using Hyper-V adapter (host traffic goes through it): {desc}")
            break

if not iface:
    print("ERROR: No suitable network interface found!")
    sys.exit(1)

# Counters
packet_count = 0
response_count = 0
event_count = 0
market_count = 0

MARKET_OPS = {
    OperationCodes.AUCTION_GET_OFFERS: "SELL_OFFERS",
    OperationCodes.AUCTION_GET_REQUESTS: "BUY_ORDERS",
    OperationCodes.AUCTION_GET_ITEM_AVERAGE_STATS: "HISTORY",
    OperationCodes.GOLD_MARKET_GET_INFOS: "GOLD_MARKET",
}


def on_response(op_code, params):
    global response_count, market_count
    response_count += 1

    if op_code in MARKET_OPS:
        market_count += 1
        print(f"\n{'='*60}")
        print(f"  MARKET DATA: {MARKET_OPS[op_code]} (op={op_code})")
        print(f"  Parameters: {len(params)} keys")
        for key, value in sorted(params.items()):
            val_str = str(value)
            if len(val_str) > 200:
                val_str = val_str[:200] + "..."
            print(f"    [{key}] ({type(value).__name__}) = {val_str}")
        print(f"{'='*60}")
    else:
        print(f"  Response op={op_code}, {len(params)} params", end="")
        if params:
            keys = list(params.keys())[:5]
            print(f" keys={keys}", end="")
        print()


def on_event(event_code, params):
    global event_count
    event_count += 1
    if event_count <= 5:
        print(f"  Event code={event_code}, {len(params)} params")


decoder = PhotonDecoder(on_response=on_response, on_event=on_event)


def process_packet(pkt):
    global packet_count
    if not pkt.haslayer(UDP) or not pkt.haslayer(Raw):
        return

    packet_count += 1
    raw = bytes(pkt[Raw].load)

    if packet_count <= 3:
        print(f"  Packet #{packet_count}: {pkt[IP].src}:{pkt[UDP].sport} -> {pkt[IP].dst}:{pkt[UDP].dport} ({len(raw)} bytes)")

    decoder.handle_payload(raw)


print()
print("=" * 60)
print("  Albion Packet Decoder Test")
print("=" * 60)
print()
print("Capturing for 30 seconds on port 5056...")
print(">>> OPEN THE MARKET IN ALBION AND SEARCH FOR AN ITEM! <<<")
print()

bpf = "udp port 5056"
print(f"BPF filter: {bpf}")
print()

try:
    sniff(filter=bpf, prn=process_packet, store=False, timeout=30, iface=iface)
except KeyboardInterrupt:
    pass

print()
print(f"Results:")
print(f"  Packets captured: {packet_count}")
print(f"  Responses decoded: {response_count}")
print(f"  Events decoded: {event_count}")
print(f"  Market data found: {market_count}")
print(f"  Decoder stats: {decoder.stats}")
