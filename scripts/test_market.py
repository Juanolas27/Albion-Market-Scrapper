"""Test: capture, reassemble fragments, decode market data with Protocol16."""
import sys
import json
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).parent.parent))

from scapy.all import sniff, UDP, IP, Raw, conf

from albion_capture.photon.decoder import PhotonDecoder
from albion_capture.photon.operations import OperationCodes

# Find Realtek
iface = None
for iface_name, iface_obj in conf.ifaces.items():
    desc = getattr(iface_obj, "description", "").lower()
    if "realtek" in desc:
        iface = iface_name
        print(f"Interface: {desc}")
        break

market_found = 0
all_ops = Counter()

# Albion uses parameter 253 for the actual operation code
ALBION_OP_KEY = 253

MARKET_OPS = {
    OperationCodes.AUCTION_GET_OFFERS: "SELL_OFFERS",
    OperationCodes.AUCTION_GET_REQUESTS: "BUY_ORDERS",
    OperationCodes.AUCTION_GET_ITEM_AVERAGE_STATS: "HISTORY",
    OperationCodes.GOLD_MARKET_GET_INFOS: "GOLD_MARKET",
}


def on_response(op_code, params):
    global market_found

    # Get the real Albion operation code from param 253
    albion_op = params.get(ALBION_OP_KEY, op_code)
    if isinstance(albion_op, int):
        all_ops[albion_op] += 1
    else:
        all_ops[op_code] += 1
        albion_op = op_code

    if albion_op in MARKET_OPS:
        market_found += 1
        print(f"\n{'='*60}")
        print(f"  MARKET DATA: {MARKET_OPS[albion_op]} (albion_op={albion_op})")
        print(f"  Photon op={op_code}, {len(params)} params")
        print(f"  Parameter keys: {sorted(params.keys())}")

        for key, value in sorted(params.items()):
            if key == ALBION_OP_KEY:
                continue
            val_str = str(value)
            type_name = type(value).__name__

            # Try to parse JSON strings
            if isinstance(value, str) and value.startswith("{"):
                try:
                    parsed = json.loads(value)
                    val_str = json.dumps(parsed, indent=2)[:300]
                    type_name = "json"
                except json.JSONDecodeError:
                    pass
            elif isinstance(value, list) and value and isinstance(value[0], str):
                # List of JSON strings (market orders)
                try:
                    first = json.loads(value[0])
                    val_str = f"[{len(value)} items] First: {json.dumps(first, indent=2)[:300]}"
                    type_name = "json[]"
                except (json.JSONDecodeError, IndexError):
                    if len(val_str) > 200:
                        val_str = val_str[:200] + "..."

            if len(val_str) > 300:
                val_str = val_str[:300] + "..."
            print(f"    [{key}] ({type_name}) = {val_str}")
        print(f"{'='*60}")
    else:
        param_count = len(params)
        print(f"  Response albion_op={albion_op}, photon_op={op_code}, {param_count} params")


def on_event(event_code, params):
    pass


decoder = PhotonDecoder(on_response=on_response, on_event=on_event)
packet_count = 0


def process_packet(pkt):
    global packet_count
    if pkt.haslayer(UDP) and pkt.haslayer(Raw):
        packet_count += 1
        decoder.handle_payload(bytes(pkt[Raw].load))


print()
print("=" * 60)
print("  Albion Market Data Test (Protocol16 + param 253)")
print("=" * 60)
print()
print("Capturing for 30 seconds...")
print(">>> OPEN THE MARKET AND SEARCH FOR ANY ITEM! <<<")
print()

try:
    sniff(filter="udp port 5056", prn=process_packet, store=False, timeout=30, iface=iface)
except KeyboardInterrupt:
    pass

print()
print("=" * 60)
print("RESULTS:")
print(f"  Packets: {packet_count}")
print(f"  Decoder: {decoder.stats}")
print(f"  Market data found: {market_found}")
if all_ops:
    print(f"  Albion op codes: {dict(all_ops.most_common(20))}")

if market_found > 0:
    print("\n  *** SUCCESS! Market data captured! ***")
elif decoder.stats.get("responses", 0) > 0:
    print("\n  Responses found but no market ops. Try searching in the auction house.")
elif decoder.stats.get("encrypted", 0) > 0:
    print(f"\n  {decoder.stats['encrypted']} encrypted messages detected.")
else:
    print("\n  No responses decoded. Check if you searched in the market.")
