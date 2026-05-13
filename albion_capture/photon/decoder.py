"""Photon Protocol16 decoder for Albion Online.

Albion uses Protocol16 serialization with a 0xF3 header byte.
The eNet layer handles fragmentation and command types.
Market operation codes are in parameter 253, not in the Photon op code.

NOTA: En versiones recientes de Albion, los responses de mercado no usan
el formato Protocol16 clasico sino que embeben JSON crudo en el payload.
Hay un fallback que extrae JSONs directamente del payload cuando la
deserializacion Protocol16 falla.
"""
from __future__ import annotations

import io
import json
import re
import struct
from typing import Callable

from albion_capture.core.logging import get_logger

log = get_logger("photon_decoder")

# Photon eNet command types
COMMAND_ACK = 1
COMMAND_SEND_RELIABLE = 6
COMMAND_SEND_UNRELIABLE = 7
COMMAND_SEND_FRAGMENT = 8

# Photon message types
MSG_OPERATION_REQUEST = 2
MSG_OPERATION_RESPONSE = 3
MSG_EVENT = 4

ResponseCallback = Callable[[int, dict], None]
EventCallback = Callable[[int, dict], None]


class Protocol16Deserializer:
    """Deserialize Protocol16 typed values from a BytesIO stream."""

    # Type codes
    NONE = 42
    BYTE = 98
    SHORT = 107
    INT = 105
    LONG = 108
    FLOAT = 102
    DOUBLE = 100
    STRING = 115
    BOOL = 111
    BYTE_ARRAY = 120
    INT_ARRAY = 110
    STRING_ARRAY = 97
    ARRAY = 121
    DICT = 68
    HASHTABLE = 104
    OBJECT_ARRAY = 122

    @staticmethod
    def read_byte(stream: io.BytesIO) -> int:
        b = stream.read(1)
        if not b:
            raise EOFError()
        return b[0]

    @staticmethod
    def read_short(stream: io.BytesIO) -> int:
        b = stream.read(2)
        if len(b) < 2:
            raise EOFError()
        return struct.unpack(">h", b)[0]

    @staticmethod
    def read_int(stream: io.BytesIO) -> int:
        b = stream.read(4)
        if len(b) < 4:
            raise EOFError()
        return struct.unpack(">i", b)[0]

    @staticmethod
    def read_long(stream: io.BytesIO) -> int:
        b = stream.read(8)
        if len(b) < 8:
            raise EOFError()
        return struct.unpack(">q", b)[0]

    @staticmethod
    def read_float(stream: io.BytesIO) -> float:
        b = stream.read(4)
        if len(b) < 4:
            raise EOFError()
        return struct.unpack(">f", b)[0]

    @staticmethod
    def read_double(stream: io.BytesIO) -> float:
        b = stream.read(8)
        if len(b) < 8:
            raise EOFError()
        return struct.unpack(">d", b)[0]

    @staticmethod
    def read_string(stream: io.BytesIO) -> str:
        length = Protocol16Deserializer.read_short(stream)
        if length <= 0:
            return ""
        b = stream.read(length)
        return b.decode("utf-8", errors="replace")

    @staticmethod
    def read_byte_array(stream: io.BytesIO) -> bytes:
        length = Protocol16Deserializer.read_int(stream)
        if length <= 0:
            return b""
        return stream.read(length)

    @staticmethod
    def read_int_array(stream: io.BytesIO) -> list[int]:
        length = Protocol16Deserializer.read_int(stream)
        return [Protocol16Deserializer.read_int(stream) for _ in range(length)]

    @staticmethod
    def read_string_array(stream: io.BytesIO) -> list[str]:
        length = Protocol16Deserializer.read_short(stream)
        return [Protocol16Deserializer.read_string(stream) for _ in range(length)]

    @staticmethod
    def read_bool(stream: io.BytesIO) -> bool:
        return Protocol16Deserializer.read_byte(stream) != 0

    @classmethod
    def deserialize(cls, stream: io.BytesIO, type_code: int):
        """Deserialize a value of the given type code."""
        if type_code == cls.NONE or type_code == 0 or type_code == 42:
            return None
        elif type_code == cls.BYTE:
            return cls.read_byte(stream)
        elif type_code == cls.BOOL:
            return cls.read_bool(stream)
        elif type_code == cls.SHORT:
            return cls.read_short(stream)
        elif type_code == cls.INT:
            return cls.read_int(stream)
        elif type_code == cls.LONG:
            return cls.read_long(stream)
        elif type_code == cls.FLOAT:
            return cls.read_float(stream)
        elif type_code == cls.DOUBLE:
            return cls.read_double(stream)
        elif type_code == cls.STRING:
            return cls.read_string(stream)
        elif type_code == cls.BYTE_ARRAY:
            return cls.read_byte_array(stream)
        elif type_code == cls.INT_ARRAY:
            return cls.read_int_array(stream)
        elif type_code == cls.STRING_ARRAY:
            return cls.read_string_array(stream)
        elif type_code == cls.ARRAY:
            return cls.deserialize_array(stream)
        elif type_code == cls.OBJECT_ARRAY:
            return cls.deserialize_object_array(stream)
        elif type_code == cls.DICT:
            return cls.deserialize_dictionary(stream)
        elif type_code == cls.HASHTABLE:
            return cls.deserialize_hashtable(stream)
        else:
            log.debug("unknown_type_code", type_code=type_code, pos=stream.tell())
            return None

    @classmethod
    def deserialize_typed_value(cls, stream: io.BytesIO):
        """Read type code + value."""
        tc = cls.read_byte(stream)
        return cls.deserialize(stream, tc)

    @classmethod
    def deserialize_array(cls, stream: io.BytesIO) -> list:
        size = cls.read_short(stream)
        tc = cls.read_byte(stream)
        if tc == cls.ARRAY:
            return [cls.deserialize_array(stream) for _ in range(size)]
        elif tc == cls.BYTE_ARRAY:
            return [cls.read_byte_array(stream) for _ in range(size)]
        elif tc == cls.DICT:
            return cls.deserialize_dict_array(stream, size)
        else:
            return [cls.deserialize(stream, tc) for _ in range(size)]

    @classmethod
    def deserialize_object_array(cls, stream: io.BytesIO) -> list:
        size = cls.read_short(stream)
        return [cls.deserialize_typed_value(stream) for _ in range(size)]

    @classmethod
    def deserialize_dictionary(cls, stream: io.BytesIO) -> dict:
        key_tc = cls.read_byte(stream)
        val_tc = cls.read_byte(stream)
        size = cls.read_short(stream)
        return cls._read_dict_entries(stream, size, key_tc, val_tc)

    @classmethod
    def deserialize_dict_array(cls, stream: io.BytesIO, size: int) -> list:
        key_tc = cls.read_byte(stream)
        val_tc = cls.read_byte(stream)
        result = []
        for _ in range(size):
            dict_size = cls.read_short(stream)
            result.append(cls._read_dict_entries(stream, dict_size, key_tc, val_tc))
        return result

    @classmethod
    def deserialize_hashtable(cls, stream: io.BytesIO) -> dict:
        size = cls.read_short(stream)
        return cls._read_dict_entries(stream, size, 0, 0)

    @classmethod
    def _read_dict_entries(cls, stream: io.BytesIO, size: int, key_tc: int, val_tc: int) -> dict:
        result = {}
        for _ in range(size):
            if key_tc == 0 or key_tc == 42:
                k = cls.deserialize_typed_value(stream)
            else:
                k = cls.deserialize(stream, key_tc)
            if val_tc == 0 or val_tc == 42:
                v = cls.deserialize_typed_value(stream)
            else:
                v = cls.deserialize(stream, val_tc)
            result[k] = v
        return result

    @classmethod
    def deserialize_parameter_table(cls, stream: io.BytesIO) -> dict:
        """Read a parameter table: short count, then (byte key, byte type_code, value) entries."""
        count = cls.read_short(stream)
        params = {}
        for _ in range(count):
            key = cls.read_byte(stream)
            val = cls.deserialize_typed_value(stream)
            params[key] = val
        return params

    @classmethod
    def deserialize_operation_response(cls, stream: io.BytesIO) -> tuple[int, int, dict]:
        """Returns (op_code, return_code, params)."""
        op_code = cls.read_byte(stream)
        return_code = cls.read_short(stream)
        _debug_msg = cls.deserialize_typed_value(stream)
        params = cls.deserialize_parameter_table(stream)
        return op_code, return_code, params

    @classmethod
    def deserialize_event(cls, stream: io.BytesIO) -> tuple[int, dict]:
        """Returns (event_code, params)."""
        event_code = cls.read_byte(stream)
        params = cls.deserialize_parameter_table(stream)
        return event_code, params

    @classmethod
    def deserialize_operation_request(cls, stream: io.BytesIO) -> tuple[int, dict]:
        """Returns (op_code, params)."""
        op_code = cls.read_byte(stream)
        params = cls.deserialize_parameter_table(stream)
        return op_code, params


class PhotonDecoder:
    """Decodes Photon packets from raw UDP payloads."""

    def __init__(
        self,
        on_response: ResponseCallback | None = None,
        on_event: EventCallback | None = None,
    ):
        self.on_response = on_response
        self.on_event = on_event
        self._fragments: dict[int, dict] = {}
        self._stats = {
            "packets": 0, "commands": 0, "messages": 0,
            "responses": 0, "events": 0, "fragments_reassembled": 0,
            "encrypted": 0, "errors": 0,
        }
        # Debug: contar msg_types vistos
        self._msg_type_counts: dict[int, int] = {}

    @property
    def stats(self) -> dict:
        return self._stats.copy()

    def handle_payload(self, data: bytes) -> None:
        """Process a raw UDP payload containing Photon eNet commands."""
        if len(data) < 12:
            return

        self._stats["packets"] += 1

        try:
            command_count = data[3]
            offset = 12

            for _ in range(command_count):
                if offset >= len(data):
                    break
                offset = self._parse_command(data, offset)
                if offset < 0:
                    break
        except Exception as e:
            self._stats["errors"] += 1

    def _parse_command(self, data: bytes, offset: int) -> int:
        if offset + 12 > len(data):
            return -1

        cmd_type = data[offset]
        cmd_length = struct.unpack_from(">I", data, offset + 4)[0]

        if cmd_length < 12 or offset + cmd_length > len(data):
            return offset + max(cmd_length, 12)

        self._stats["commands"] += 1

        if cmd_type == COMMAND_SEND_RELIABLE:
            payload = data[offset + 12 : offset + cmd_length]
            if payload:
                self._handle_message(payload)

        elif cmd_type == COMMAND_SEND_UNRELIABLE:
            payload = data[offset + 16 : offset + cmd_length]
            if payload:
                self._handle_message(payload)

        elif cmd_type == COMMAND_SEND_FRAGMENT:
            self._handle_fragment(data, offset, cmd_length)

        return offset + cmd_length

    def _handle_fragment(self, data: bytes, offset: int, cmd_length: int) -> None:
        """Handle a fragmented message, reassembling when complete.

        Fragment header layout (after 12-byte command header):
          +12: start_sequence_number (4 bytes)
          +16: fragment_count (4 bytes)
          +20: fragment_number (4 bytes)
          +24: total_length (4 bytes)
          +28: fragment_offset (4 bytes)
          +32: payload data
        """
        if offset + 32 > len(data):
            return

        start_seq = struct.unpack_from(">I", data, offset + 12)[0]
        frag_count = struct.unpack_from(">I", data, offset + 16)[0]
        _frag_number = struct.unpack_from(">I", data, offset + 20)[0]
        total_length = struct.unpack_from(">I", data, offset + 24)[0]
        frag_offset = struct.unpack_from(">I", data, offset + 28)[0]

        frag_data = data[offset + 32 : offset + cmd_length]

        if start_seq not in self._fragments:
            self._fragments[start_seq] = {
                "total_length": total_length,
                "frag_count": frag_count,
                "parts": {},
            }

        entry = self._fragments[start_seq]
        entry["parts"][frag_offset] = frag_data

        if len(entry["parts"]) == frag_count:
            reassembled = bytearray(total_length)
            for off, part in sorted(entry["parts"].items()):
                end = min(off + len(part), total_length)
                reassembled[off:end] = part[: end - off]
            del self._fragments[start_seq]

            self._stats["fragments_reassembled"] += 1
            self._handle_message(bytes(reassembled))

        # Cleanup stale fragments
        if len(self._fragments) > 100:
            oldest = sorted(self._fragments.keys())[:50]
            for key in oldest:
                del self._fragments[key]

    def _handle_message(self, payload: bytes) -> None:
        """Parse a Photon message after stripping the protocol header byte."""
        if len(payload) < 2:
            return

        self._stats["messages"] += 1

        # Skip protocol magic byte (0xF3 or 0xF0)
        start = 0
        if payload[0] in (0xF3, 0xF0):
            start = 1

        if start >= len(payload):
            return

        msg_type = payload[start]
        self._msg_type_counts[msg_type] = self._msg_type_counts.get(msg_type, 0) + 1

        # DEBUG: dump completo de payloads grandes (potencial market response)
        # Solo guardamos los primeros de cada tamano para no llenar disco.
        if not hasattr(self, "_dump_path"):
            import os
            self._dump_path = os.environ.get("PHOTON_DUMP_PATH")
            self._dump_sizes: set[int] = set()
            self._dump_count = 0
        if self._dump_path and self._dump_count < 50 and len(payload) > 100:
            bucket = len(payload) // 200  # agrupar por tamano aprox
            key = (msg_type, bucket)
            if key not in self._dump_sizes:
                self._dump_sizes.add(key)
                self._dump_count += 1
                try:
                    with open(self._dump_path, "ab") as f:
                        f.write(f"\n=== msg_type={msg_type} len={len(payload)} ===\n".encode())
                        f.write(payload.hex().encode())
                        f.write(b"\n")
                except Exception:
                    pass

        # Check encrypted flag (0x80)
        if msg_type & 0x80:
            self._stats["encrypted"] += 1
            return

        # Create stream from remaining data
        stream = io.BytesIO(payload[start + 1:])

        # 1) Intentar parse Protocol16 clasico
        op_code = None
        params: dict | None = None
        event_code = None
        is_response = msg_type == MSG_OPERATION_RESPONSE
        is_event = msg_type == MSG_EVENT

        parse_ok = False
        if is_response:
            try:
                op_code, _ret, params = Protocol16Deserializer.deserialize_operation_response(stream)
                parse_ok = True
            except (EOFError, struct.error):
                parse_ok = False
            except Exception as e:
                log.debug("response_parse_error", error=str(e))
                parse_ok = False
        elif is_event:
            try:
                event_code, params = Protocol16Deserializer.deserialize_event(stream)
                parse_ok = True
            except (EOFError, struct.error):
                parse_ok = False
            except Exception as e:
                log.debug("event_parse_error", error=str(e))
                parse_ok = False
        else:
            return

        # 2) Si el parse clasico falla, caer al extractor JSON (Photon nuevo)
        if not parse_ok:
            if is_response and self._extract_json_response(payload):
                self._stats["responses"] += 1
            else:
                self._stats["errors"] += 1
                if not hasattr(self, "_first_errors"):
                    self._first_errors = {}
                if msg_type not in self._first_errors:
                    self._first_errors[msg_type] = ("ParseFail", "", payload[:40].hex())
            return

        # 3) Parse clasico OK: emitir callbacks
        try:
            if is_response and self.on_response:
                self._stats["responses"] += 1
                self.on_response(op_code, params)
            elif is_event and self.on_event:
                self._stats["events"] += 1
                self.on_event(event_code, params)
        except Exception as e:
            log.debug("callback_error", error=str(e))

    # Patron para localizar el inicio de un JSON object con campos conocidos.
    # Los responses de mercado comienzan con {"Id":, o {"ItemTypeId":, etc.
    _JSON_START_RE = re.compile(rb'\{"(?:Id|ItemTypeId|ItemGroupTypeId|Timestamp|Price|AveragePrice)"\s*:')

    # Ops sinteticas (del fichero operations.py): 74=OFFERS, 75=REQUESTS,
    # 88=HISTORY, 237=GOLD. Aqui solo importa para rutear a market_parser.
    _OP_OFFERS = 74
    _OP_HISTORY = 88
    _OP_GOLD = 237

    def _extract_json_response(self, payload: bytes) -> bool:
        """Extrae JSONs crudos embebidos en el payload y los rutea a on_response.

        Retorna True si se extrajo al menos un JSON valido.
        """
        objs: list[dict] = []
        pos = 0
        while pos < len(payload):
            m = self._JSON_START_RE.search(payload, pos)
            if not m:
                break
            start = m.start()
            end = self._find_json_end(payload, start)
            if end <= start:
                pos = start + 1
                continue
            try:
                text = payload[start:end].decode("utf-8", errors="replace")
                obj = json.loads(text)
                if isinstance(obj, dict):
                    objs.append(obj)
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
            pos = end

        if not objs:
            return False

        # Rutear por contenido. Todos los objs suelen ser del mismo tipo.
        sample = objs[0]
        if "AuctionType" in sample:
            op = self._OP_OFFERS
        elif "Timescale" in sample or "AveragePrice" in sample or "SilverAmount" in sample:
            op = self._OP_HISTORY
        elif "Price" in sample and len(sample) <= 3:
            op = self._OP_GOLD
        else:
            # Fallback: tratar como orders si tiene campos clave.
            if "ItemTypeId" in sample and "UnitPriceSilver" in sample:
                op = self._OP_OFFERS
            else:
                return False

        # Construir params sinteticos compatibles con market_parser.
        params = {0: objs, 253: op}
        if self.on_response:
            self.on_response(op, params)
        return True

    @staticmethod
    def _find_json_end(data: bytes, start: int) -> int:
        """Encuentra el indice (exclusivo) del '}' que cierra el JSON que inicia en start."""
        depth = 0
        in_string = False
        escape = False
        for j in range(start, len(data)):
            c = data[j]
            if escape:
                escape = False
                continue
            if in_string:
                if c == 0x5C:  # backslash
                    escape = True
                elif c == 0x22:  # "
                    in_string = False
                continue
            if c == 0x22:
                in_string = True
            elif c == 0x7B:  # {
                depth += 1
            elif c == 0x7D:  # }
                depth -= 1
                if depth == 0:
                    return j + 1
        return -1
