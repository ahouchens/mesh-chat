"""Translate domain-authorized profiles; never infer authority from a handle."""

from .model import Authority, ConnectionKey, Desired


def connection_key(profile: dict) -> ConnectionKey:
    required = ("id", "local_device_id")
    if any(not isinstance(profile.get(name), str) or not profile[name] for name in required):
        raise ValueError("Connection profile identity is incomplete")
    return ConnectionKey(profile.get("scope_kind", "contact"), profile["id"],
                         profile["local_device_id"], profile.get("remote_device_id") or None)


def authority_signature(profile: dict) -> tuple:
    # Availability and status do not change consent. Device changes change keys.
    reasons = (profile.get("effective") or {}).get("reasons") or ()
    return (
        profile.get("auto_reconnect"), profile.get("peer_auto_reconnect"),
        profile.get("allow_direct_ip_disclosure"), profile.get("relay_consent_scope"),
        profile.get("trust"),
        profile.get("manual_carrier_authorized", False),
        tuple(sorted(reason for reason in reasons if reason != "mailbox_not_configured")),
    )


def authority(profile: dict, revision: int) -> Authority:
    effective = profile.get("effective") or {}
    reasons = set(effective.get("reasons") or ())
    authorized = bool(profile.get("manual_carrier_authorized") or effective.get("ready")
                      or reasons == {"mailbox_not_configured"})
    return Authority(revision, authorized, bool(effective.get("ready")),
                     bool(effective.get("preferred")))


def desired(profile: dict) -> Desired:
    enabled = profile.get("active") or profile.get("manual_carrier_authorized")
    return (Desired.ENABLED if enabled and profile.get("state") != "stopped"
            else Desired.STOPPED)
