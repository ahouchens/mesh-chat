"""Inherited IPC must stop without waiting for the parent to close its writer."""
import os
from pathlib import Path
import subprocess
import sys
from time import monotonic, sleep

import pytest

from mesh_chat.direct_native import NativeChannel, NativeFrameReader
from mesh_chat.ipc import encode_frame


@pytest.mark.parametrize("partial", [b"", b"\x00\x00", b"\x00\x00\x00\x10{\"id\":"])
def test_close_interrupts_empty_and_partial_frames_without_owning_the_pipe(partial):
    incoming, outgoing = os.pipe()
    with os.fdopen(incoming, "rb", buffering=0) as source, os.fdopen(outgoing, "wb", buffering=0) as writer:
        reader = NativeFrameReader(source, NativeChannel())
        try:
            if partial:
                writer.write(partial)
            sleep(.03)
            started = monotonic()
            reader.close()
            assert monotonic() - started < 1
            assert not reader._thread.is_alive()
            assert not source.closed and not writer.closed
            with pytest.raises(EOFError): reader.read()
        finally:
            writer.close()
            reader._thread.join(timeout=1)


def test_process_exits_cleanly_with_parent_pipe_still_open():
    script = """
import sys
from mesh_chat.direct_native import NativeChannel, NativeFrameReader
reader = NativeFrameReader(sys.stdin.buffer, NativeChannel())
assert reader.read() == {"command": "stop"}
reader.close()
"""
    environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")}
    child = subprocess.Popen([sys.executable, "-c", script], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment)
    try:
        child.stdin.write(encode_frame({"command": "stop"}))
        child.stdin.flush()
        assert child.wait(timeout=5) == 0
        assert b"Fatal Python error" not in child.stderr.read()
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        for stream in (child.stdin, child.stdout, child.stderr): stream.close()


def test_initial_and_queued_frames_share_one_unbuffered_input_without_losing_read_ahead():
    from mesh_chat.inherited_input import interruptible_input
    from mesh_chat.ipc import read_frame
    incoming, outgoing = os.pipe()
    with os.fdopen(incoming, "rb") as source, os.fdopen(outgoing, "wb", buffering=0) as writer:
        stream = interruptible_input(source)
        writer.write(encode_frame({"command": "initialize"}) + encode_frame({"command": "snapshot"}))
        assert read_frame(stream) == {"command": "initialize"}
        reader = NativeFrameReader(stream, NativeChannel())
        try:
            assert reader.read() == {"command": "snapshot"}
        finally:
            reader.close()
        assert not reader._thread.is_alive()


def test_pipe_eof_drains_complete_frames_and_reports_a_truncated_frame():
    incoming, outgoing = os.pipe()
    with os.fdopen(incoming, "rb", buffering=0) as source, os.fdopen(outgoing, "wb", buffering=0) as writer:
        reader = NativeFrameReader(source, NativeChannel())
        writer.write(encode_frame({"command": "snapshot"}) + b"\x00\x00")
        writer.close()
        try:
            assert reader.read() == {"command": "snapshot"}
            with pytest.raises(EOFError): reader.read()
        finally:
            reader.close()
