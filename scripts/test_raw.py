"""Inspect raw Albion packet structure to debug the Photon decoder."""
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

print("Capturing packets for 20 seconds... OPEN THE MARKET AND SEARCH!")
print()

packets_data = []


def capture(pkt):
    if pkt.haslayer(UDP) and pkt.haslayer(Raw):
        raw = bytes(pkt[Raw].load)
        src = f"{pkt[IP].src}:{pkt[UDP].sport}"
        dst = f"{pkt[IP].dst}:{pkt[UDP].dport}"
        packets_data.append((raw, src, dst))


sniff(filter="udp port 5056", prn=capture, store=False, timeout=20, iface=iface)

print(f"Captured {len(packets_data)} packets")
print()

# Analyze first 10 packets in detail
for i, (raw, src, dst) in enumerate(packets_data[:15]):
    print(f"{'='*70}")
    print(f"Packet #{i+1}: {src} -> {dst} ({len(raw)} bytes)")
    print(f"  Hex (first 64 bytes): {raw[:64].hex()}")
    print()

    if len(raw) < 12:
        print(f"  Too short for Photon eNet header")
        continue

    # Parse eNet header
    peer_id = struct.unpack_from(">H", raw, 0)[0]
    flag_byte = raw[2]
    cmd_count = raw[3]
    timestamp = struct.unpack_from(">I", raw, 4)[0]
    challenge = struct.unpack_from(">I", raw, 8)[0]

    print(f"  eNet Header:")
    print(f"    PeerID: {peer_id} (0x{peer_id:04x})")
    print(f"    Flag/CRC byte: {flag_byte} (0x{flag_byte:02x})")
    print(f"    Command count: {cmd_count}")
    print(f"    Timestamp: {timestamp}")
    print(f"    Challenge: {challenge}")

    # Parse commands
    offset = 12
    for cmd_idx in range(cmd_count):
        if offset + 12 > len(raw):
            print(f"    Command #{cmd_idx+1}: Not enough data at offset {offset}")
            break

        cmd_type = raw[offset]
        channel = raw[offset + 1]
        flags = raw[offset + 2]
        reserved = raw[offset + 3]
        cmd_length = struct.unpack_from(">I", raw, offset + 4)[0]
        reliable_seq = struct.unpack_from(">I", raw, offset + 8)[0]

        print(f"    Command #{cmd_idx+1}:")
        print(f"      Type: {cmd_type} ({'Reliable' if cmd_type == 6 else 'Unreliable' if cmd_type == 7 else 'Fragment' if cmd_type == 8 else 'Ack' if cmd_type == 1 else 'Other'})")
        print(f"      Channel: {channel}, Flags: {flags}")
        print(f"      Length: {cmd_length}, ReliableSeq: {reliable_seq}")

        # Show payload for reliable/unreliable commands
        if cmd_type in (6, 7) and cmd_length > 12:
            payload_start = offset + (12 if cmd_type == 6 else 16)
            payload = raw[payload_start:offset + cmd_length]
            if payload:
                msg_type = payload[0] if payload else 0
                msg_type_name = {2: "Request", 3: "Response", 4: "Event", 7: "OperationResponse"}.get(msg_type, f"Unknown({msg_type})")
                print(f"      Message type: {msg_type} ({msg_type_name})")
                if len(payload) > 1:
                    print(f"      Payload hex: {payload[:48].hex()}")

        if cmd_type == 8 and offset + 32 <= len(raw):
            start_seq = struct.unpack_from(">I", raw, offset + 12)[0]
            frag_count = struct.unpack_from(">I", raw, offset + 16)[0]
            total_len = struct.unpack_from(">I", raw, offset + 20)[0]
            frag_offset_val = struct.unpack_from(">I", raw, offset + 24)[0]
            frag_num = struct.unpack_from(">I", raw, offset + 28)[0]
            print(f"      Fragment: startSeq={start_seq}, count={frag_count}, totalLen={total_len}, offset={frag_offset_val}, num={frag_num}")

        offset += max(cmd_length, 12)

print()
print("Packet size distribution:")
sizes = {}
for raw, _, _ in packets_data:
    bucket = f"{(len(raw) // 100) * 100}-{(len(raw) // 100) * 100 + 99}"
    sizes[bucket] = sizes.get(bucket, 0) + 1
for bucket, count in sorted(sizes.items()):
    print(f"  {bucket} bytes: {count} packets")

# Count command types
cmd_types = {}
for raw, _, _ in packets_data:
    if len(raw) >= 12:
        offset = 12
        cmd_count = raw[3]
        for _ in range(cmd_count):
            if offset + 4 >= len(raw):
                break
            ct = raw[offset]
            cmd_types[ct] = cmd_types.get(ct, 0) + 1
            cmd_len = struct.unpack_from(">I", raw, offset + 4)[0] if offset + 8 <= len(raw) else 12
            offset += max(cmd_len, 12)

print()
print("Command type distribution:")
type_names = {1: "Ack", 2: "Connect", 3: "ConnectVerify", 4: "Disconnect",
              5: "Ping", 6: "Reliable", 7: "Unreliable", 8: "Fragment",
              12: "ReliableFragment"}
for ct, count in sorted(cmd_types.items()):
    name = type_names.get(ct, f"Unknown({ct})")
    print(f"  Type {ct} ({name}): {count}")
