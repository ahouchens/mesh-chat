"""Distinguish an ADB cleanup error from an earlier failed stop action."""
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
import native_interop_android_observation as observation
import native_interop_controller as controller
import native_interop_peers as peers


@pytest.mark.parametrize('stderr,category', [
    (b"adb: error: listener 'tcp:12345' not found\n", 'listener_not_found'),
    (b"adb: error: listener 'tcp:54321' not found\n", 'other'),
    (b'adb: error: device offline\n', 'device_offline'),
    (b'adb: error: no devices/emulators found\n', 'no_device'),
    (b'adb: error: more than one device/emulator\n', 'multiple_devices'),
    (b'adb: error: closed\n', 'transport_closed'),
    (b'PRIVATE_ERROR', 'other'),
    (b'x' * 4097, 'unavailable'),
    (None, 'unavailable'),
], ids=['exact_listener', 'wrong_listener', 'offline', 'no_device', 'multiple', 'closed', 'private', 'oversize', 'missing'])
def test_failed_forward_retains_only_exact_fixed_stderr_category(monkeypatch, stderr, category):
    peer = peers.AndroidPeer(b'k' * 32)
    error = subprocess.CalledProcessError(1, ['PRIVATE_COMMAND'], stderr=stderr)
    calls = []
    def execute(argv, **kwargs):
        calls.append((argv, kwargs))
        raise error
    monkeypatch.setattr(peers.subprocess, 'check_output', execute)
    with pytest.raises(subprocess.CalledProcessError) as caught:
        peer._adb('forward', '--remove', 'tcp:12345')
    assert caught.value is error
    assert calls == [([peer.adb, 'forward', '--remove', 'tcp:12345'],
                     {'stderr': subprocess.PIPE, 'timeout': 30})]
    detail = peer.failure_lifecycle_observation(error)
    assert detail['stderr_category'] == category
    rendered = json.dumps(controller.android_lifecycle_failure(peer, None, error))
    assert category in rendered
    assert '12345' not in rendered and '54321' not in rendered and 'PRIVATE' not in rendered


@pytest.mark.parametrize('stage', ['force_stop', 'process_wait', 'reader_join'])
def test_cleanup_error_retains_prior_stop_stage_without_replacing_escaped_error(monkeypatch, stage):
    peer = peers.AndroidPeer(b'k' * 32)
    peer.forward = '12345'
    first = subprocess.TimeoutExpired('PRIVATE', 30)
    final = subprocess.CalledProcessError(1, ['PRIVATE'], stderr=b'adb: error: closed\n')
    def fail():
        raise first
    peer.process = SimpleNamespace(poll=lambda: 255,
        wait=lambda timeout: fail() if stage == 'process_wait' else 255)
    peer._reader = SimpleNamespace(join=lambda timeout: fail() if stage == 'reader_join' else None)
    def execute(argv, **kwargs):
        if argv[1] == 'forward':
            raise final
        if stage == 'force_stop':
            raise first
        return b''
    monkeypatch.setattr(peers.subprocess, 'check_output', execute)
    with pytest.raises(subprocess.CalledProcessError) as caught:
        peer.stop(crash=True, _origin='old_stop')
    assert caught.value is final
    detail = peer.failure_lifecycle_observation(final)
    assert detail['prior_failure'] == {'stage': stage, 'exception_kind': 'timeout_expired'}
    assert detail['stderr_category'] == 'transport_closed'
    assert detail['stop_origin'] == 'old_stop'
    assert detail['prior_failure'] == controller.android_lifecycle_failure(peer, None, final)['android_lifecycle_failure']['prior_failure']
    assert 'PRIVATE' not in json.dumps(detail)


def test_prior_failure_is_not_reused_by_next_independent_stop(monkeypatch):
    peer = peers.AndroidPeer(b'k' * 32)
    peer.forward = '12345'
    prior = subprocess.TimeoutExpired('PRIVATE', 30)
    cleanup = subprocess.CalledProcessError(1, ['PRIVATE'])
    fail_wait = [True]
    def wait(timeout):
        if fail_wait[0]: raise prior
        return 255
    peer.process = SimpleNamespace(poll=lambda: 255, wait=wait)
    peer._reader = SimpleNamespace(join=lambda _: None)
    def execute(argv, **kwargs):
        if argv[1] == 'forward': raise cleanup
        return b''
    monkeypatch.setattr(peers.subprocess, 'check_output', execute)
    with pytest.raises(subprocess.CalledProcessError): peer.stop(crash=True)
    assert peer.failure_lifecycle_observation(cleanup)['prior_failure']['stage'] == 'process_wait'
    fail_wait[0] = False
    with pytest.raises(subprocess.CalledProcessError): peer.stop(crash=True)
    assert 'prior_failure' not in peer.failure_lifecycle_observation(cleanup)


@pytest.mark.parametrize('field,value', [
    ('stderr_category', 'PRIVATE'),
    ('prior_failure', {'stage': 'PRIVATE', 'exception_kind': 'timeout_expired'}),
    ('prior_failure', {'stage': 'process_wait', 'exception_kind': 'PRIVATE'}),
    ('prior_failure', {'stage': 'process_wait', 'exception_kind': 'timeout_expired', 'raw': 'PRIVATE'}),
    ('stop_origin', 'PRIVATE'),
    ('masked_start_kind', 'os_error'),
])
def test_malformed_optional_details_are_rejected(field, value):
    row = {'v': 1, 'site': 'forward_remove', 'exit_status': 1,
           'instrumentation_process': {'state': 'absent', 'exit_status': None}, 'instrumentation': None,
           field: value}
    assert observation.android_lifecycle_snapshot(row) is None


def test_legacy_lifecycle_row_still_valid():
    row = {'v': 1, 'site': 'forward_remove', 'exit_status': 1,
           'instrumentation_process': {'state': 'absent', 'exit_status': None}, 'instrumentation': None}
    assert observation.android_lifecycle_snapshot(row) == row


def test_throwing_stop_observer_keeps_exact_cleanup_exception(monkeypatch):
    peer = peers.AndroidPeer(b'k' * 32)
    peer.forward = '12345'
    peer.process = SimpleNamespace(poll=lambda: 255, wait=lambda timeout: 255)
    peer._reader = SimpleNamespace(join=lambda _: None)
    error = subprocess.CalledProcessError(1, ['PRIVATE'])
    def execute(argv, **kwargs):
        if argv[1] == 'forward': raise error
        return b''
    def fail(*_): raise RuntimeError('PRIVATE')
    monkeypatch.setattr(peers.subprocess, 'check_output', execute)
    monkeypatch.setattr(peer, '_observe_stop_failure', fail)
    with pytest.raises(subprocess.CalledProcessError) as caught:
        peer.stop(crash=True)
    assert caught.value is error


def test_non_lifecycle_adb_call_keeps_stderr_discarded(monkeypatch):
    peer = peers.AndroidPeer(b'k' * 32)
    calls = []
    def execute(argv, **kwargs):
        calls.append((argv, kwargs))
        return b'device\n'
    monkeypatch.setattr(peers.subprocess, 'check_output', execute)
    assert peer._adb('get-state') == 'device'
    assert calls == [([peer.adb, 'get-state'], {'stderr': subprocess.DEVNULL, 'timeout': 30})]
