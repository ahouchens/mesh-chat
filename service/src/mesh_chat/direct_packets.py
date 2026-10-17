"""Private service-owned packet pumps; no listeners or renderer commands.

The native boundary must supply bounded packet channels and authenticate before
interface activation. A pump never authorizes or activates an interface itself.
"""
import queue
import threading
import time

from .errors import ValidationError


class PacketPump:
    AUTHORITY_INTERVAL = 0.25
    OUTGOING_BATCH = 32

    def __init__(self, registry, interface, session, incoming, outgoing,
                 carrier_lost, cancel_carrier, check_authority):
        self._registry = registry
        self._interface, self._session = interface, session
        self._incoming, self._outgoing = incoming, outgoing
        self._carrier_lost, self._cancel_carrier = carrier_lost, cancel_carrier
        self._check_authority = check_authority
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="mesh-direct-packets")

    def stop(self):
        # Never wait for a packet consumer or authority callback during teardown.
        self._stop.set()
        self._cancel_carrier.set()

    def join(self, timeout=None):
        self._thread.join(timeout)

    def is_alive(self):
        return self._thread.is_alive()

    def _run(self):
        next_check = 0
        try:
            while not self._stop.is_set() and not self._carrier_lost.is_set():
                if self._interface.detached:
                    return
                if self._interface.online:
                    if not self._interface.check_health():
                        return
                    if time.monotonic() >= next_check:
                        if not self._check_authority():
                            return
                        next_check = time.monotonic() + self.AUTHORITY_INTERVAL
                try:
                    packet = self._incoming.get(timeout=0.01)
                except queue.Empty:
                    packet = False
                if self._stop.is_set() or self._carrier_lost.is_set():
                    return
                if packet is None:
                    return
                if packet is not False:
                    self._interface.receive(self._session, packet)
                # A busy producer cannot starve cancellation/authority checks.
                for _ in range(self.OUTGOING_BATCH):
                    if self._stop.is_set() or self._carrier_lost.is_set():
                        return
                    packet = self._interface.take_outgoing(self._session)
                    if packet is None:
                        break
                    try:
                        self._outgoing.put_nowait(packet)
                    except queue.Full:
                        break  # Unreliable DATAGRAMs; RNS owns retry semantics.
        except Exception:
            # Channel, RNS and authority failures all retire the path. No private
            # exception details are sent to the renderer or packet channel.
            pass
        finally:
            try:
                self._interface.engine_lost(self._session)
            finally:
                self._cancel_carrier.set()
                self._registry._release(self)


class PacketRuntime:
    MAX_PUMPS = 8

    def __init__(self):
        self._lock = threading.Lock()
        self._pumps = set()
        self._closed = False

    def open(self, interface, session, incoming, outgoing, carrier_lost,
             cancel_carrier, check_authority):
        with self._lock:
            if self._closed or len(self._pumps) >= self.MAX_PUMPS:
                raise ValidationError("Direct packet runtime unavailable or full")
            if any(pump._interface is interface for pump in self._pumps):
                raise ValidationError("Direct interface already has a packet owner")
            pump = PacketPump(self, interface, session, incoming, outgoing,
                              carrier_lost, cancel_carrier, check_authority)
            self._pumps.add(pump)
            try:
                pump._thread.start()
            except Exception:
                self._pumps.discard(pump)
                raise
            return pump

    def _release(self, pump):
        with self._lock:
            self._pumps.discard(pump)

    def retire_all(self, *, close=False):
        with self._lock:
            self._closed = self._closed or close
            for pump in self._pumps:
                pump.stop()
            # Retain capacity until each old thread actually exits. Replacement
            # cannot accumulate unbounded blocked pumps after repeated resumes.

    def wait(self, timeout=None):
        """Wait outside service/registry locks before closing the vault."""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._lock:
            pumps = tuple(self._pumps)
        for pump in pumps:
            if pump._thread is threading.current_thread():
                return False
            remaining = None if deadline is None else max(0, deadline - time.monotonic())
            pump.join(remaining)
        return all(not pump.is_alive() for pump in pumps)
