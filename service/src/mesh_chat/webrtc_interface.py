from __future__ import annotations

import time
from typing import Callable

import RNS
from RNS.Interfaces.Interface import Interface


class WebRTCInterface(Interface):
    """Reticulum interface backed by one WebRTC DataChannel.

    The interface is created only after a DataChannel is verified and open. It
    carries raw Reticulum packets; the WebView/Tauri layer is responsible for
    moving the corresponding binary messages.
    """

    IN = True
    OUT = True
    FWD = False
    RPT = False
    HW_MTU = 1064
    BITRATE = 1_000_000

    def __init__(
        self,
        owner: object,
        send_packet: Callable[[bytes], None],
        *,
        name: str = "Mesh Chat WebRTC",
    ) -> None:
        super().__init__()
        self.owner = owner
        self._send_packet = send_packet
        self.name = name
        self.online = True
        self.receives = True
        self.bitrate = self.BITRATE
        self.mode = Interface.MODE_POINT_TO_POINT
        self.shared_medium = False
        self.created_at = time.time()

    def process_incoming(self, data: bytes) -> None:
        if not self.online or not data:
            return
        data = bytes(data)
        if len(data) > self.HW_MTU:
            return
        self.rxb += len(data)
        self.owner.inbound(data, self)

    def process_outgoing(self, data: bytes) -> None:
        if not self.online or not data:
            return
        data = bytes(data)
        if len(data) > self.HW_MTU:
            return
        self.txb += len(data)
        try:
            self._send_packet(data)
        except Exception:
            self.detach()

    def detach(self) -> None:
        self.online = False
        self.receives = False
        self.detached = True
        try:
            RNS.Transport.remove_interface(self)
        except Exception:
            pass
        self._send_packet = lambda _data: None
