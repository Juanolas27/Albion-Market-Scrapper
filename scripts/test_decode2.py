"""Debug: inspect all message types to find where market responses are."""
import sys
import struct
from pathlib import Path
from collections import Counter

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
print("Capturing 30s... SEARCH FOR AN ITEM IN THE MARKET!")
print()

msg_types = Counter()
event_codes = Counter()
response_ops = Counter()
fragment_info = {"total": 0, "reassembled": 0, "pending": {}}
all_first_bytes = Counter()
reassembled_messages = []


def handle_message(payload, source=""):
    """Analyze a decoded message payload."""
    if len(payload) < 2:
        return

    first_byte = payload[0]
    all_first_bytes[first_byte] += 1

    # Skip protocol magic
    start = 0
    if first_byte in (0xF3, 0xF0):
        start = 1

    if start >= len(payload):
        return

    msg_type = payload[start]
    msg_types[msg_type] += 1

    if msg_type == 4:  # Event
        if start + 1 < len(payload):
            event_codes[payload[start + 1]] += 1
    elif msg_type == 3:  # OperationResponse (V18)
        if start + 1 < len(payload):
            op = payload[start + 1]
            response_ops[op] += 1
            print(f"  >>> RESPONSE op={op} ({len(payload)} bytes) [source={source}]")
            # Show first 100 bytes hex
            print(f"      hex: {payload[:100].hex()}")
    elif msg_type == 7:  # OperationResponse (V16)
        if start + 1 < len(payload):
            op = payload[start + 1]
            response_ops[op] += 1
            print(f"  >>> RESPONSE(v16) op={op} ({len(payload)} bytes) [source={source}]")
    elif msg_type == 2:  # Request
        pass  # ignore outgoing
    else:
        print(f"  Unknown msg_type={msg_type} (0x{msg_type:02x}), first_byte=0x{first_byte:02x}, len={len(payload)}, src={source}")
        print(f"      hex: {payload[:64].hex()}")


fragments = {}


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

        if cmd_type == 6:  # Reliable
            payload = data[offset + 12 : offset + cmd_length]
            if payload:
                handle_message(payload, "reliable")

        elif cmd_type == 7:  # Unreliable
            payload = data[offset + 16 : offset + cmd_length]
            if payload:
                handle_message(payload, "unreliable")

        elif cmd_type == 8:  # Fragment
            fragment_info["total"] += 1
            if offset + 32 <= len(data):
                start_seq = struct.unpack_from(">I", data, offset + 12)[0]
                frag_count = struct.unpack_from(">I", data, offset + 16)[0]
                total_length = struct.unpack_from(">I", data, offset + 20)[0]
                frag_offset = struct.unpack_from(">I", data, offset + 24)[0]
                frag_data = data[offset + 32 : offset + cmd_length]

                if start_seq not in fragments:
                    fragments[start_seq] = {
                        "total_length": total_length,
                        "frag_count": frag_count,
                        "parts": {},
                    }

                entry = fragments[start_seq]
                entry["parts"][frag_offset] = frag_data

                if len(entry["parts"]) == frag_count:
                    # Reassemble!
                    reassembled = bytearray(total_length)
                    for off, part in sorted(entry["parts"].items()):
                        end = min(off + len(part), total_length)
                        reassembled[off:end] = part[: end - off]
                    del fragments[start_seq]

                    fragment_info["reassembled"] += 1
                    payload = bytes(reassembled)
                    print(f"\n  FRAGMENT REASSEMBLED: {total_length} bytes, {frag_count} parts")
                    handle_message(payload, "fragment")

        offset += cmd_length


try:
    sniff(filter="udp port 5056", prn=process_packet, store=False, timeout=30, iface=iface)
except KeyboardInterrupt:
    pass

print()
print("=" * 60)
print("RESULTS:")
print(f"  First bytes seen: {dict(all_first_bytes.most_common(10))}")
print(f"  Message types: {dict(msg_types.most_common(10))}")
print(f"  Event codes: {dict(event_codes.most_common(10))}")
print(f"  Response op codes: {dict(response_ops.most_common(20))}")
print(f"  Fragments: {fragment_info['total']} total, {fragment_info['reassembled']} reassembled")
print(f"  Pending fragments: {len(fragments)} groups")

for seq, info in list(fragments.items())[:5]:
    print(f"    seq={seq}: {len(info['parts'])}/{info['frag_count']} parts, total={info['total_length']}")
