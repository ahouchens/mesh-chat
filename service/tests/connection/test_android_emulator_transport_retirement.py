"""The packaged emulator owner must retire its ADB transport before reuse."""
import os

import pytest

from test_ui_core_boundary_interop_peers import scripted_android
import native_interop_peers as peers


def test_close_waits_for_owned_transport_before_releasing_avd(monkeypatch, tmp_path):
    script = scripted_android(monkeypatch, tmp_path)
    emulator = script.emulator
    emulator.start(script.apks)
    original = peers.subprocess.check_output
    listings = iter(["emulator-5554\toffline\n", "emulator-5554\toffline\n", ""])
    polls = []

    def output(command, **options):
        if command[-1] != "devices":
            return original(command, **options)
        assert emulator.process is None
        assert emulator.root.exists()
        assert os.environ["ANDROID_SERIAL"] == emulator.serial
        assert 0 < options["timeout"] <= 5
        polls.append(command)
        return "List of devices attached\n" + next(listings)

    monkeypatch.setattr(peers.subprocess, "check_output", output)
    monkeypatch.setattr(peers.time, "sleep", lambda seconds: setattr(script, "now", script.now + seconds))
    emulator.close()
    assert len(polls) == 3
    assert not emulator.root.exists()
    assert os.environ["ANDROID_SERIAL"] == "PRIVATE_PREVIOUS_SERIAL"
    emulator.close()
    assert len(polls) == 3  # Released custody must not inspect a later owner's device.


@pytest.mark.parametrize("failure", ["timeout", "foreign", "adb_error", "empty_output", "malformed_header"])
def test_unresolved_transport_retains_custody_and_later_close_can_finish(monkeypatch, tmp_path, failure):
    script = scripted_android(monkeypatch, tmp_path)
    emulator = script.emulator
    emulator.start(script.apks)
    original = peers.subprocess.check_output
    unresolved = [True]

    def output(command, **options):
        if command[-1] != "devices":
            return original(command, **options)
        if not unresolved[0]:
            return "List of devices attached\n"
        if failure == "adb_error":
            raise OSError("PRIVATE_ADB_FAILURE")
        if failure == "empty_output":
            return ""
        if failure == "malformed_header":
            return "PRIVATE_UNEXPECTED_HEADER\n"
        serial = "foreign-device" if failure == "foreign" else emulator.serial
        return "List of devices attached\n" + serial + "\toffline\n"

    monkeypatch.setattr(peers.subprocess, "check_output", output)
    monkeypatch.setattr(peers.time, "sleep", lambda seconds: setattr(script, "now", script.now + seconds))
    code = "unowned_android_device_present" if failure == "foreign" else "emulator_transport_retirement_failed"
    with pytest.raises(peers.PeerFailure, match=code) as error:
        emulator.close()
    assert "PRIVATE" not in str(error.value)
    assert emulator.process is None and emulator.root.exists()
    assert os.environ["ANDROID_SERIAL"] == emulator.serial
    assert script.now <= 30
    unresolved[0] = False
    emulator.close()
    assert not emulator.root.exists()
    assert os.environ["ANDROID_SERIAL"] == "PRIVATE_PREVIOUS_SERIAL"
