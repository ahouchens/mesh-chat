"""Commands the trusted application host may dispatch through the facade.

Generated from the desktop renderer allowlist. Only a private host-bound port may
invoke these commands; public owner/approve grants never attach that port.
"""

from uuid import uuid4

from .errors import ApiFailure


NATIVE_COMMANDS = frozenset({
    "workspace_snapshot",
    "i2p_status",
    "connect_using_reply",
    "check_direct_connection",
    "prepare_manual_participant_host",
    "configure_participant_firewall",
    "stop_participant_host",
    "call_media",
    "reconnect_profiles",
    "reconnect_consent_set",
    "reconnect_capabilities_store",
    "reconnect_capabilities_get",
    "reconnect_status",
    "reconnect_start",
    "reconnect_stop",
    "reconnect_request_create",
    "reconnect_offer_create",
    "reconnect_answer_create",
    "reconnect_publish",
    "reconnect_fetch",
    "reconnect_path_status",
    "verify_reconnect_request",
    "verify_reconnect_offer",
    "verify_reconnect_answer",
    "webrtc_attach",
    "webrtc_packet",
    "webrtc_detach",
    "native_webrtc_offer",
    "native_webrtc_accept",
    "native_webrtc_apply_answer",
    "native_webrtc_control",
    "native_webrtc_close",
    "native_webrtc_stats",
    "native_webrtc_bind_onboarding",
    "webrtc_onboarding_offer",
    "webrtc_onboarding_answer",
    "verify_webrtc_onboarding_offer",
    "verify_webrtc_onboarding_answer",
    "prepare_direct_offer",
    "prepare_direct_answer",
    "prepare_direct_ready",
    "accept_direct_ready",
    "connect_direct_setup",
    "configure_direct_firewall",
    "direct_recovery_status",
    "pause_direct_recovery",
    "resume_direct_recovery",
    "direct_setup_status",
    "resume_direct_setup",
    "check_direct_setup",
    "retry_direct_setup",
    "cancel_direct_setup",
    "workspace_connectivity",
    "workspace_helper_status",
    "workspace_helper_consent_set",
    "relay_workspace_connection_update",
    "workspace_request_paths",
    "reconcile_mobile_lifecycle",
})


class ServiceNativeCommands:
    """Private adapter bound only by authenticated application bootstrap."""

    def __init__(self, service):
        self._service = service

    def command(self, command, payload):
        if command not in NATIVE_COMMANDS:
            raise ApiFailure("forbidden")
        if not isinstance(payload, dict):
            raise ApiFailure("invalid_request")
        response, should_stop = self._service.dispatch({
            "v": 1,
            "id": uuid4().hex,
            "command": command,
            "payload": payload,
        })
        if should_stop:
            raise ApiFailure("forbidden")
        if response.get("ok") is not True:
            code = response.get("error", {}).get("code", "internal")
            raise ApiFailure(code if code in {
                "invalid_request", "forbidden", "unavailable", "conflict",
                "resource_exhausted", "internal",
            } else "internal")
        return response.get("result")
