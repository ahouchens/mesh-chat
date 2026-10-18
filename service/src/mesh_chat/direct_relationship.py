"""Encrypted admitted relationship evidence, independent of native ownership.

Stored candidates are hints, never permission to resurrect a socket or attach
an adapter. Current membership is reloaded inside each acceptance transaction.
Invitation authorities cannot create these records.
"""
from .direct_binding import AcceptedBinding, _parse, verify_binding
from .errors import IdentityMismatch, ValidationError
from .invitations import canonical_bytes


def relationship_material(authority):
    return canonical_bytes({"issuer": authority.issuer_public_identity.hex(),
                            "audience": authority.audience_destination.hex(),
                            "scope": authority.scope}).decode("utf-8")


def relationship_id(store, authority):
    return store.opaque_id("direct-relationship", relationship_material(authority))


def accept_relationship(store, raw, expected, certificate, *, load_authority, clock):
    """Commit recovery evidence and the existing replay floor together.

    Reuses Phase 1/2 replay keys, including when upgrading an existing profile.
    Old records therefore cannot be replayed to initialize a new relationship.
    The record deliberately contains no native handles, local ports or keys.
    """
    if expected.scope.get("kind") != "workspace":
        raise ValidationError("Durable direct relationships require membership")
    material = relationship_material(expected)
    replay_key = ("direct_binding", store.opaque_id("direct-binding", material))
    key = ("direct_relationship", relationship_id(store, expected))

    def update(records):
        current = load_authority()
        if relationship_material(current) != material:
            raise IdentityMismatch("Direct relationship authorization changed")
        accepted = verify_binding(raw, current, certificate, now=clock(),
                                  previous=AcceptedBinding(**records[replay_key])
                                  if records[replay_key] is not None else None)
        previous = records[key]
        if previous is not None and previous.get("version") != 1:
            raise ValidationError("Unsupported direct relationship version")
        if previous is not None and previous["accepted"]["generation"] > accepted.generation:
            raise ValidationError("Direct relationship generation is stale")
        evidence = {"generation": accepted.generation, "digest": accepted.digest}
        value = _parse(raw)
        record = dict(previous) if previous is not None else {
            "version": 1, "scope": dict(current.scope),
            "issuer": current.issuer_public_identity.hex(),
            "audience": current.audience_destination.hex(),
            "last_success": None,
        }
        record.update(accepted=evidence, binding=raw, certificate=certificate.hex(),
                      candidates=value["candidates"], expires_at=value["expires_at"])
        return {replay_key: evidence, key: record}

    values = store.update_records((replay_key, key), update)
    return AcceptedBinding(**values[replay_key])


def record_success(store, expected, accepted, *, load_authority, clock):
    """Record authenticated route evidence only for the still-current winner.

    Caller must observe native authentication and the signed peer RNS announce.
    Late callbacks cannot overwrite a newer candidate generation. This evidence
    is historical: it does not report live peer or application receipt state.
    """
    material = relationship_material(expected)
    def update(previous):
        if relationship_material(load_authority()) != material:
            raise IdentityMismatch("Direct relationship authorization changed")
        evidence = {"generation": accepted.generation, "digest": accepted.digest}
        floor = store.get("direct_binding", store.opaque_id("direct-binding", material))
        now = clock()
        if (previous is None or previous.get("version") != 1
                or previous["accepted"] != evidence or floor != evidence
                or now >= min(previous["expires_at"], expected.expires_at)):
            raise ValidationError("Direct route evidence belongs to a retired generation")
        if previous["last_success"] is not None and previous["last_success"]["digest"] == accepted.digest:
            return previous
        previous["last_success"] = {"generation": accepted.generation,
                                    "digest": accepted.digest, "at": now}
        return previous
    return store.update_record("direct_relationship", relationship_id(store, expected), update)
