"""Bounded terminal observations after failed receipt recovery, before cleanup."""

import math

from native_interop_carrier_observation import (
    SCENARIOS, carrier_target, checked_inventory_fact, inventory_fact,
)

TIME_CAP_MS = 120000
PACKET_CAP = 1000000
# Existing peer exchanges take at most 60s, with bounded Windows disposal after
# a timeout. Do not start the optional read near the global qualification limit.
READ_BUDGET_SECONDS = 120


def block_window_snapshot(value):
    fields = {"fully_installed_ms", "operation_window_ms", "fully_installed_capped",
              "operation_window_capped", "dropped_packets", "packets_capped"}
    if type(value) is not dict or set(value) != fields: return None
    for count, capped, limit in (("fully_installed_ms", "fully_installed_capped", TIME_CAP_MS),
                                ("operation_window_ms", "operation_window_capped", TIME_CAP_MS),
                                ("dropped_packets", "packets_capped", PACKET_CAP)):
        if (type(value[count]) is not int or not 0 <= value[count] <= limit
                or type(value[capped]) is not bool or (value[capped] and value[count] != limit)):
            return None
    if (value["dropped_packets"] == 0 or value["fully_installed_ms"] > value["operation_window_ms"]
            or (value["fully_installed_capped"] and not value["operation_window_capped"])):
        return None
    return dict(value)


class KernelBlockWindow:
    """Bounds around existing commands, not claimed exact kernel rule timestamps."""

    def __init__(self):
        self.times = []
        self.packets = None

    def mark(self, stage, now, packets=None):
        stages = ("block_call", "block_return", "unblock_call", "unblock_return")
        if (len(self.times) >= len(stages) or stage != stages[len(self.times)]
                or type(now) not in (int, float) or not math.isfinite(now)
                or (self.times and now < self.times[-1])):
            raise ValueError("Invalid optional block clock")
        if stage == "unblock_return":
            if type(packets) is not int or packets <= 0:
                raise ValueError("Invalid optional dropped count")
            self.packets = packets
        self.times.append(now)

    def snapshot(self):
        if len(self.times) != 4: return None
        lower = int((self.times[2] - self.times[1]) * 1000)
        upper = int((self.times[3] - self.times[0]) * 1000)
        return block_window_snapshot({"fully_installed_ms": min(lower, TIME_CAP_MS),
            "operation_window_ms": min(upper, TIME_CAP_MS),
            "fully_installed_capped": lower > TIME_CAP_MS,
            "operation_window_capped": upper > TIME_CAP_MS,
            "dropped_packets": min(self.packets, PACKET_CAP), "packets_capped": self.packets > PACKET_CAP})


def mark_window(window, stage, clock, packets=None):
    try:
        if type(window) is KernelBlockWindow:
            window.mark(stage, clock(), packets)
            return window
    except Exception:
        pass
    return None


def recovery_context_snapshot(value):
    if (type(value) is not dict or set(value) != {"scenario", "kernel_block_window", "carrier_read", "carrier"}
            or type(value["scenario"]) is not str or value["scenario"] not in SCENARIOS
            or type(value["carrier_read"]) is not str
            or value["carrier_read"] not in {"observed", "unavailable", "skipped_deadline"}):
        return None
    window = value["kernel_block_window"]
    if window is not None and block_window_snapshot(window) is None: return None
    carrier = value["carrier"]
    if value["carrier_read"] == "observed":
        carrier = checked_inventory_fact(carrier)
        if carrier is None: return None
    elif carrier is not None:
        return None
    return {**value, "kernel_block_window": dict(window) if window is not None else None, "carrier": carrier}


def capture_recovery_context(peer, target, scenario, window, remaining):
    """One existing private inventory read; never retries or controls delivery."""
    if (carrier_target(target) is None or type(scenario) is not str or scenario not in SCENARIOS
            or type(remaining) not in (int, float) or not math.isfinite(remaining)):
        return None
    result = {"scenario": scenario, "kernel_block_window": None, "carrier_read": "unavailable", "carrier": None}
    try:
        if type(window) is KernelBlockWindow: result["kernel_block_window"] = window.snapshot()
    except Exception:
        pass
    if remaining < READ_BUDGET_SECONDS:
        result["carrier_read"] = "skipped_deadline"
    else:
        try:
            sample = peer.inventory(carrier_observation=target)
            rows = sample.get("resources") if type(sample) is dict else None
            if type(rows) is list and len(rows) <= 256 and all(type(row) is dict for row in rows):
                selected = checked_inventory_fact(inventory_fact(sample, target))
                if selected is not None:
                    result.update(carrier_read="observed", carrier=selected)
        except Exception:
            pass
    return recovery_context_snapshot(result)
