"""Failure-only, per-run attribution for checked Android preflight commands."""

from contextlib import contextmanager


PREFLIGHT_FAILURE_SITES = frozenset({
    "android_devices", "android_avd_create", "android_root", "android_wait_for_device",
    "android_root_identity", "android_host_apk_install", "android_test_apk_install",
    "android_notification_grant", "android_device_state", "android_emulator_property", "android_abi",
})


class PreflightDiagnostics:
    def __init__(self):
        self._failure = None

    @contextmanager
    def scope(self, site):
        if site is not None and (type(site) is not str or site not in PREFLIGHT_FAILURE_SITES):
            raise ValueError("Unknown preflight diagnostic site")
        self._failure = None
        try:
            yield
        except Exception as error:
            # Retain identity in RAM only; never copy command data or error text.
            if site is not None:
                self._failure = error, site
            raise
        else:
            self._failure = None

    def failure_site(self, error):
        observed = self._failure
        return observed[1] if observed is not None and observed[0] is error and observed[1] in PREFLIGHT_FAILURE_SITES else None
