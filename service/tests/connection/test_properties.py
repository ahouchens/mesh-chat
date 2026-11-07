from hypothesis import settings, strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from tools.connection_harness.simulation import Simulation, scenario


class ConnectionMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.sim = Simulation()
        self.sim.advance(0)

    @rule(seconds=st.integers(min_value=0, max_value=90))
    def advance(self, seconds):
        self.sim.advance(seconds)

    @rule(enabled=st.booleans())
    def intent(self, enabled):
        self.sim.intent(enabled)

    @rule(available=st.booleans())
    def network(self, available):
        self.sim.network(available)

    @rule(index=st.integers(min_value=0, max_value=2), fail=st.booleans(),
          duplicate=st.booleans(), adopt=st.booleans())
    def completion(self, index, fail, duplicate, adopt):
        self.sim.complete(index, fail, duplicate, adopt)

    @invariant()
    def ownership_is_consistent(self):
        self.sim.assert_safe()

    def teardown(self):
        self.sim.recover()
        self.sim.close()


TestConnectionMachine = ConnectionMachine.TestCase
TestConnectionMachine.settings = settings(max_examples=1000, stateful_step_count=100, deadline=None,
                                           derandomize=True)


def test_seeded_trace_is_reproducible():
    assert scenario("fault_sequence", 42) == scenario("fault_sequence", 42)
