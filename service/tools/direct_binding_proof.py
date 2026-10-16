"""CI-only native/public-certificate to protected-RNS binding proof.

This is not a shipped command or a runtime authority provider. Identities and
authorization are owned by this controlled harness, not read from a descriptor.
"""
import sys
import os
import time
import uuid

import RNS

from mesh_chat.direct_binding import BindingAuthority, create_binding, verify_binding
from mesh_chat.errors import IdentityMismatch
from mesh_chat.workspace_protocol import _destination_for


def authorize(certificates: list[bytes]) -> None:
    identities = [RNS.Identity(), RNS.Identity()]
    now = int(time.time())
    scope = {"kind": "invitation", "digest": "ab" * 32, "expires_at": now + 300}
    challenge = os.urandom(32)
    for index, identity in enumerate(identities):
        authority = BindingAuthority(identity.get_public_key(),
                                     _destination_for(identities[1 - index]), scope, now + 300, challenge)
        raw = create_binding(identity, authority, certificates[index],
                             session_id=str(uuid.uuid4()), challenge=challenge,
                             generation=1, candidates=[{
                                 # Declarative candidate only: the proof never
                                 # connects to this address or uses discovery.
                                 "host": "8.8.8.8", "port": 12345, "expires_at": now + 300,
                             }], issued_at=now, expires_at=now + 300)
        verify_binding(raw, authority, certificates[index], now=now)
        try:
            verify_binding(raw, authority, certificates[1 - index], now=now)
        except IdentityMismatch:
            pass
        else:
            raise AssertionError("Substituted native certificate was accepted")
    for certificate in certificates:
        print(certificate.hex())


if __name__ == "__main__":
    if len(sys.argv) != 3 or any(not 2 <= len(value) <= 32768 for value in sys.argv[1:]):
        raise SystemExit("Expected two bounded public native certificates")
    authorize([bytes.fromhex(value) for value in sys.argv[1:]])
