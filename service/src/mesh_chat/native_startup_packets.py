"""Bound early encrypted packets to an exact native allocation, without policy."""

import base64
import binascii
from threading import Lock


class NativeStartupPackets:
    MAX_RESOURCES = 16
    MAX_PACKETS = 16
    MAX_BYTES = 16 * 1024
    MAX_PACKET = 1064

    def __init__(self):
        self._packets: dict[str, list[bytes]] = {}
        self._lock = Lock()
        self._dropped = 0

    @property
    def dropped(self):
        with self._lock:
            return self._dropped

    def retain(self, physical: str, encoded: str) -> bool:
        with self._lock:
            packet = self._decode(encoded)
            pending = self._packets.get(physical, [])
            if (packet is None or len(pending) >= self.MAX_PACKETS
                    or sum(map(len, pending)) + len(packet) > self.MAX_BYTES
                    or (physical not in self._packets and len(self._packets) >= self.MAX_RESOURCES)):
                self._dropped += 1
                return False
            self._packets.setdefault(physical, []).append(packet)
            return True

    def _decode(self, encoded: str) -> bytes | None:
        if not encoded or len(encoded) > 4 * ((self.MAX_PACKET + 2) // 3):
            return None
        try:
            packet = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            return None
        return packet if 1 <= len(packet) <= self.MAX_PACKET else None

    def take(self, physical: str) -> tuple[bytes, ...]:
        with self._lock:
            return tuple(self._packets.pop(physical, ()))

    def discard(self, physical: str | None) -> None:
        with self._lock:
            self._packets.pop(physical, None)
