"""Compatibility-command restrictions for the service-owned composition."""

OWNER_OPERATIONS = frozenset({
    "reconnect_request_create", "reconnect_offer_create", "reconnect_answer_create",
    "verify_reconnect_request", "verify_reconnect_offer", "verify_reconnect_answer",
    "reconnect_publish", "reconnect_fetch", "reconnect_replay_check",
    "webrtc_attach", "webrtc_packet",
})

# A previous process's success cannot establish a current live native resource.
# Persistent user intent and durable message operations retain their own cache.
TRANSIENT_OPERATIONS = frozenset({
    "native_webrtc_offer", "native_webrtc_accept", "native_webrtc_apply_answer",
    "native_webrtc_control", "native_webrtc_close", "native_webrtc_stats",
    "native_webrtc_bind_onboarding", "webrtc_detach", "reconnect_status",
    "webrtc_onboarding_offer", "webrtc_onboarding_answer",
    "verify_webrtc_onboarding_offer", "verify_webrtc_onboarding_answer",
})


def owner_only(command, payload):
    return command in OWNER_OPERATIONS or (command == "reconnect_status" and bool(payload))
