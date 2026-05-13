"""Debug fragment header layout to fix reassembly."""
import sys
import struct
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scapy.all import sniff, UDP, IP, Raw, conf

# Find Realtek
iface = None
for iface_name, iface_obj in conf.ifaces.items():
    desc = getattr(iface_obj, "description", "").lower()
    if "realtek" in desc:
        iface = iface_name
        break

print(f"Using: {iface}")
print("Capturing 20s... SEARCH FOR AN ITEM IN THE MARKET!")
print()

fragment_dumps = []


def process_packet(pkt):
    if not pkt.haslayer(UDP) or not pkt.haslayer(Raw):
        return

    data = bytes(pkt[Raw].load)
    if len(data) < 12:
        return

    cmd_count = data[3]
    offset = 12

    for _ in range(cmd_count):
        if offset + 12 > len(data):
            break

        cmd_type = data[offset]
        cmd_length = struct.unpack_from(">I", data, offset + 4)[0]

        if cmd_length < 12 or offset + cmd_length > len(data):
            offset += max(cmd_length, 12)
            continue

        if cmd_type == 8:  # Fragment
            if offset + 32 <= len(data) and len(fragment_dumps) < 10:
                # Dump raw header bytes at each 4-byte position
                print(f"Fragment command (length={cmd_length}):")
                print(f"  Raw header bytes (offset 0-31):")
                cmd_data = data[offset:offset + min(48, cmd_length)]
                print(f"  {cmd_data.hex()}")
                print()

                for pos in range(0, 32, 4):
                    val = struct.unpack_from(">I", data, offset + pos)[0]
                    print(f"  offset +{pos:2d}: {val:10d} (0x{val:08x})")

                # Also show first 16 bytes of payload after header
                payload_start = offset + 32
                if payload_start < offset + cmd_length:
                    payload = data[payload_start:offset + cmd_length]
                    print(f"  Payload ({len(payload)} bytes): {payload[:32].hex()}")

                print()
                fragment_dumps.append(True)

        offset += cmd_length


try:
    sniff(filter="udp port 5056", prn=process_packet, store=False, timeout=20, iface=iface)
except KeyboardInterrupt:
    pass

print(f"\nShowed {len(fragment_dumps)} fragment headers")
