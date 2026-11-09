"""Old service-carried Python SDK or new standalone SDK, imported from install."""
import json
import sys

if "--old" in sys.argv:
    from mesh_chat.core_api.client import CoreClient
    from mesh_chat.core_api import __version__
else:
    from mesh_chat_core_client import CoreClient, __version__


def write(frame):
    result = sys.stdout.buffer.write(frame)
    sys.stdout.buffer.flush()
    return result


client = CoreClient.open(sys.stdin.buffer.readline, write)
try:
    profile = client.capabilities["profiles"][0]
    peer = client.profile(profile)["peers"][0]
    accepted = client.enqueue(profile, peer, "Upgrade legacy enqueue", "upgrade-legacy-message-key-0001")
    report = {"accepted": accepted["accepted"], "sdk_version": __version__, "api_minor": client.capabilities["api_minor"]}
    if "--expect-no-composer" in sys.argv:
        try:
            client.composer_query(profile, peer)
            raise AssertionError("Unsupported composer unexpectedly accepted")
        except Exception as error:
            assert getattr(error, "code", None) == "unsupported_operation"
            report["composer_locally_refused"] = True
    print(json.dumps(report), file=sys.stderr)
finally:
    if hasattr(client, "close"):
        client.close()
