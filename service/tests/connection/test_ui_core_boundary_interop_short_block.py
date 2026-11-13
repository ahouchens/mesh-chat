"""A short path proof must not include slow artifact coordination."""

from types import SimpleNamespace
import sys

import pytest

from test_ui_core_boundary_interop_recovery_observation import blocked_controller
import native_interop_controller as controller


def short_control(monkeypatch, *, control_delay=0, artifact_delay=20, unblock_delay=0):
    instance, clock, calls = blocked_controller(monkeypatch, ['delivered'], role='android')
    events = []
    active = [False]
    def artifact(*args):
        assert not active[0], 'Artifact coordination is inside the kernel outage'
        clock.now += artifact_delay
        events.append('artifact')
        return {'approved': True}
    instance.publish = instance.receive = artifact
    def send(stage):
        assert active[0]
        events.append(stage)
    def receive(stage, **kwargs):
        assert active[0]
        events.append(stage)
        clock.now += control_delay
        return True
    control = SimpleNamespace(send=send, receive=receive)
    def prepare(scenario):
        assert scenario == 'impaired' and not active[0]
        artifact()
        return control
    instance._prepare_negative_control = prepare
    def block():
        active[0] = True
        events.append('block')
    def unblock():
        clock.now += unblock_delay
        active[0] = False
        events.append('unblock')
        return 3
    fault = SimpleNamespace(block=block, unblock=unblock, protocol='udp',
        target_kind='uid_udp_all_destinations', target_material='PRIVATE_TARGET', rule_count=2)
    return instance, clock, calls, events, fault


def test_slow_artifact_work_finishes_before_block_without_extending_recovery(monkeypatch):
    instance, clock, calls, events, fault = short_control(monkeypatch)
    result, deadline = instance.negative(fault, 'impaired')
    assert events == ['artifact', 'block', 'ready', 'checked', 'unblock']
    assert 2000 <= result['block_operation_ms'] <= 2001
    assert deadline == pytest.approx(clock.now + 90)
    assert result['blocked_packets'] == 3 and result['delivered_after_restore']
    assert sum(operation == 'message.enqueue' for operation, _ in calls) == 1


@pytest.mark.parametrize('control_delay,unblock_delay', [(7, 0), (0, 7)])
def test_over_budget_control_or_exact_cleanup_cannot_pass_short_proof(
        monkeypatch, control_delay, unblock_delay):
    instance, _, calls, events, fault = short_control(monkeypatch,
        control_delay=control_delay, unblock_delay=unblock_delay)
    with pytest.raises(ValueError, match='block.*budget') as caught:
        instance.negative(fault, 'impaired')
    assert events[-1] == 'unblock'
    assert instance.failure_negative_control(caught.value) == {
        'negative_control': {'scenario': 'impaired', 'stage': 'block_duration', 'reason': 'over_budget'}}
    assert instance._recovery_diagnostics._phase == 'blocked_receipt'


@pytest.mark.parametrize('invalid', [1, float('nan'), float('inf')])
def test_nonfinite_or_reversed_block_clock_cannot_qualify(monkeypatch, invalid):
    instance, clock, _, events, fault = short_control(monkeypatch)
    normal = fault.unblock
    def backwards():
        result = normal()
        clock.now = invalid
        return result
    fault.unblock = backwards
    with pytest.raises(ValueError, match='block.*clock'):
        instance.negative(fault, 'impaired')
    assert events[-1] == 'unblock'


@pytest.mark.parametrize('duration', [None, False, 1999, 8001, 8000.0, float('nan'), '3000'])
def test_combined_native_evidence_rejects_missing_or_invalid_android_block_bound(duration):
    import native_interop_evidence as evidence
    from test_ui_core_boundary_interop_controller import interop_reports
    windows, android = interop_reports()
    case = next(value for value in android['execution']['scenarios'] if value['scenario'] == 'impaired')
    case['negative']['block_operation_ms'] = duration
    with pytest.raises(ValueError, match='block duration'):
        evidence.verify_pair(windows, android, 'a' * 40, 'b' * 40)


def test_windows_cannot_claim_its_own_android_block_duration():
    import native_interop_evidence as evidence
    from test_ui_core_boundary_interop_controller import interop_reports
    windows, android = interop_reports()
    case = next(value for value in windows['execution']['scenarios'] if value['scenario'] == 'impaired')
    case['negative']['block_operation_ms'] = 3000
    with pytest.raises(ValueError, match='Windows role'):
        evidence.verify_pair(windows, android, 'a' * 40, 'b' * 40)


@pytest.mark.parametrize('role', ['android', 'windows'])
def test_capability_exchange_and_remote_arm_finish_before_block(monkeypatch, role):
    instance, _, _ = blocked_controller(monkeypatch, ['delivered'], role=role)
    events = []
    def create(base):
        assert base == controller.DEFAULT_SIGNAL_MAILBOX_URL
        events.append('create')
        return 'PRIVATE_CODE'
    class Control:
        def __init__(self, context, selected_role, scenario, capability, **kwargs):
            assert (context, selected_role, scenario, capability) == (
                instance.context, role, 'impaired', 'PRIVATE_CODE')
            assert kwargs['base'] == controller.DEFAULT_SIGNAL_MAILBOX_URL
            events.append('bind')
        def send(self, stage): events.append('send_' + stage)
        def receive(self, stage, *, deadline):
            assert deadline <= instance.deadline
            events.append('receive_' + stage)
            return True
    monkeypatch.setitem(sys.modules, 'native_interop_negative_control', SimpleNamespace(
        new_capability=create, NegativeControlMailbox=Control))
    def publish(phase, payload):
        assert phase == 'negative_control_impaired' and payload == {'capability': 'PRIVATE_CODE'}
        events.append('artifact_publish')
    def receive(phase, *, timeout):
        assert phase == 'negative_control_impaired' and timeout <= 180
        events.append('artifact_receive')
        return {'capability': 'PRIVATE_CODE'}
    instance.publish, instance.receive = publish, receive
    controller.Controller._prepare_negative_control(instance, 'impaired')
    assert events == (['create', 'artifact_publish', 'bind', 'receive_armed'] if role == 'android'
                      else ['artifact_receive', 'bind', 'send_armed'])


def test_expired_global_budget_never_prepares_new_control_room(monkeypatch):
    instance, clock, _ = blocked_controller(monkeypatch, ['delivered'])
    monkeypatch.setitem(sys.modules, 'native_interop_negative_control', SimpleNamespace(
        new_capability=lambda _: pytest.fail('room created after deadline'), NegativeControlMailbox=object))
    instance.deadline = clock.now
    with pytest.raises(controller.PeerFailure, match='scenario_deadline'):
        controller.Controller._prepare_negative_control(instance, 'impaired')
