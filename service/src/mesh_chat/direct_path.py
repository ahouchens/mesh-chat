"""Private activation parameters derived from both verified public controls."""
import ipaddress
import time

from .direct_binding import _parse
from .errors import ValidationError
from .workspace_protocol import _destination_for, _identity_from_public_key


def client_role(local, remote, local_candidates, remote_candidates):
    if local == remote:
        raise ValidationError("Direct peer is local")
    if bool(local_candidates) != bool(remote_candidates):
        return not bool(local_candidates)
    return local < remote


def native_parameters(local_identity, local_candidates, remote_binding, certificate, *, now=None):
    now = time.time() if now is None else now
    fields = _parse(remote_binding)
    local = _destination_for(local_identity)
    remote = _destination_for(_identity_from_public_key(bytes.fromhex(fields["issuer_public_identity"])))
    remote_candidates = [candidate for candidate in fields["candidates"] if candidate["expires_at"] > now]
    declared_local = local_candidates
    local_candidates = [candidate for candidate in local_candidates if candidate["expires_at"] > now]
    if declared_local and not local_candidates:
        raise ValidationError("Direct candidate expired")
    if fields["candidates"] and not remote_candidates:
        raise ValidationError("Direct candidate expired")
    if not local_candidates and not remote_candidates:
        raise ValidationError("No public candidate; use an existing TCP route or refresh connection details")
    families = {ipaddress.ip_address(candidate["host"]).version for candidate in local_candidates+remote_candidates}
    if len(families) > 1:
        raise ValidationError("Direct candidate address families differ; refresh connection details")
    remaining = min(60, fields["expires_at"]-now)
    if remaining <= 0:
        raise ValidationError("Direct candidate expired")
    return {"certificate":certificate.hex(), "local":local.hex(), "remote":remote.hex(),
            "client":client_role(local, remote, local_candidates, remote_candidates),
            "remaining_ms":int(remaining*1000),
            "candidates":[{"host":candidate["host"], "port":candidate["port"],
                           "remaining_ms":int(min(300,candidate["expires_at"]-now)*1000)}
                          for candidate in remote_candidates]}
