from __future__ import annotations

import time
from typing import Callable

import RNS
from RNS.Interfaces.Interface import Interface
from RNS.Transport import IDX_PT_RVCD_IF


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
        # Interface.__init__ sets an instance HW_MTU to None, shadowing the
        # class limit. Restore it before any transport can use this interface.
        self.HW_MTU = type(self).HW_MTU
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
        self._send_packet = lambda _data: None
        try:
            RNS.Transport.remove_interface(self)
        except Exception:
            pass
        # LXMF caches live links. Removing an interface alone leaves those
        # links ACTIVE and sends into the retired DataChannel after reconnect.
        # Snapshot pending first so a concurrent activation is seen in at least
        # one list; never hold transport locks while teardown invokes callbacks.
        with RNS.Transport.pending_links_lock:
            links = list(RNS.Transport.pending_links)
        with RNS.Transport.active_links_lock:
            links.extend(RNS.Transport.active_links)
        seen: set[int] = set()
        for link in links:
            if id(link) in seen or getattr(link, "attached_interface", None) is not self:
                continue
            seen.add(id(link))
            try:
                link.teardown()
            except Exception:
                pass
        # A closed pending link's normal maintenance would expire its
        # destination again, possibly after a replacement route was learned.
        # Retire its registry entries now, after teardown callbacks have run.
        for lock, registered, by_id in (
            (RNS.Transport.pending_links_lock, RNS.Transport.pending_links, RNS.Transport.pending_links_map),
            (RNS.Transport.active_links_lock, RNS.Transport.active_links, RNS.Transport.active_links_map),
        ):
            with lock:
                for link in list(registered):
                    if getattr(link, "attached_interface", None) is self and link.status == RNS.Link.CLOSED:
                        registered.remove(link)
                        if by_id.get(link.link_id) is link:
                            by_id.pop(link.link_id)
        # expire_path() defers removal to transport maintenance. Remove only
        # this interface's entries now, checking under the table lock so a route
        # already learned on a replacement interface is never invalidated.
        with RNS.Transport.path_table_lock:
            for destination, entry in list(RNS.Transport.path_table.items()):
                if entry[IDX_PT_RVCD_IF] is self:
                    RNS.Transport.path_table.pop(destination)
