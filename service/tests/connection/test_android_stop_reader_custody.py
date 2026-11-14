"""An Android testhost keeps its stdout owner until the reader has retired."""
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from native_interop_peers import AndroidPeer, PeerFailure


class Reader:
    def __init__(self, active=False):
        self.active = active
        self.joins = []

    def join(self, timeout):
        self.joins.append(timeout)

    def is_alive(self):
        return self.active


class Output:
    def __init__(self, reader):
        self.reader = reader
        self.closed = False

    def close(self):
        assert not self.reader.active, "buffered stdout closed under its live reader"
        self.closed = True


class Process:
    def __init__(self, reader, code):
        self.stdout = Output(reader)
        self.code = code
        self.waits = []

    def wait(self, timeout):
        self.waits.append(timeout)
        return self.code

    def poll(self):
        return self.code


def owned_peer(*, code, reader_active=False):
    peer = AndroidPeer(b"k" * 32)
    reader = Reader(reader_active)
    process = Process(reader, code)
    peer.process = process
    peer._reader = reader
    peer.forward = "12345"
    commands = []
    peer._adb = lambda *args: commands.append(args)
    return peer, process, reader, commands


def test_clean_stop_retires_reader_and_exact_stdout_before_releasing_owner():
    peer, process, reader, commands = owned_peer(code=0)
    peer._request = lambda action, payload: {
        "closed": True, "resources_retired": True, "store_retired": True}

    peer.stop()

    assert reader.joins == [5]
    assert process.waits == [30]
    assert process.stdout.closed and peer.process is None and peer.forward is None
    assert peer.clean_exits == 1 and peer.forced_exits == 0
    assert commands == [("forward", "--remove", "tcp:12345")]


def test_intentional_crash_allows_255_after_reader_and_forward_retire():
    peer, process, reader, commands = owned_peer(code=255)

    peer.stop(crash=True, _origin="old_stop")

    assert reader.joins == [5]
    assert process.waits == [30]
    assert process.stdout.closed and peer.process is None and peer.forward is None
    assert peer.forced_exits == 1
    assert commands == [("shell", "am", "force-stop", peer.APP),
                        ("forward", "--remove", "tcp:12345")]


def test_stop_uses_the_reader_captured_with_its_process():
    peer, process, reader, _ = owned_peer(code=255)
    replacement = Reader(active=True)

    def adb(*args):
        if args[:3] == ("shell", "am", "force-stop"):
            peer._reader = replacement

    peer._adb = adb
    peer.stop(crash=True)

    assert reader.joins == [5] and replacement.joins == []
    assert process.stdout.closed and peer.process is None


@pytest.mark.parametrize("origin", ["old_stop", "start_rollback"])
def test_stalled_reader_retains_owner_until_later_explicit_stop(origin):
    peer, process, reader, commands = owned_peer(code=255, reader_active=True)

    with pytest.raises(PeerFailure, match="android_reader_retirement_unverified"):
        peer.stop(crash=True, _origin=origin)

    assert reader.joins == [5]
    assert peer.process is process and not process.stdout.closed
    assert peer.forward is None and peer.forced_exits == 1
    assert commands == [("shell", "am", "force-stop", peer.APP),
                        ("forward", "--remove", "tcp:12345")]
    with pytest.raises(PeerFailure, match="peer_already_started"):
        peer.start()

    reader.active = False
    peer.stop(crash=True, _origin=origin)
    assert process.stdout.closed and peer.process is None
    assert reader.joins == [5, 5]


def test_prior_force_stop_error_survives_stalled_reader_and_keeps_custody():
    peer, process, reader, commands = owned_peer(code=255, reader_active=True)
    original = subprocess.CalledProcessError(1, ["PRIVATE_COMMAND"])

    def adb(*args):
        commands.append(args)
        if args[:3] == ("shell", "am", "force-stop"):
            raise original

    peer._adb = adb
    with pytest.raises(subprocess.CalledProcessError) as caught:
        peer.stop(crash=True, _origin="old_stop")

    assert caught.value is original
    assert reader.joins == [5]
    assert peer.process is process and not process.stdout.closed
    assert peer.forward is None and peer.forced_exits == 0
    reader.active = False
    peer._adb = lambda *args: commands.append(args)
    peer.stop(crash=True, _origin="old_stop")
    assert process.stdout.closed and peer.process is None


def test_clean_stop_reader_failure_keeps_original_error_and_custody():
    peer, process, reader, _ = owned_peer(code=0, reader_active=True)
    peer._request = lambda action, payload: {
        "closed": True, "resources_retired": True, "store_retired": True}

    with pytest.raises(PeerFailure, match="unclean_android_exit"):
        peer.stop()

    assert reader.joins == [5]
    assert peer.process is process and not process.stdout.closed
    assert peer.clean_exits == 0
