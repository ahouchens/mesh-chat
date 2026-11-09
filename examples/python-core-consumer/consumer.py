"""Distribution-only client; the host owns streams, authentication and storage."""
import json
from pathlib import Path
import sys

from mesh_chat_core_client import CoreClient, CoreClientError


def main():
    if "--pipe" in sys.argv:
        from mesh_chat_core_client.windows import connect
        pipe = connect(sys.argv[sys.argv.index("--pipe") + 1])
        client = CoreClient.open(pipe.readline, pipe.write, pipe.close)
    else:
        def write(frame):
            count = sys.stdout.buffer.write(frame)
            sys.stdout.buffer.flush()
            return count
        client = CoreClient.open(sys.stdin.buffer.readline, write)
    try:
        report = {"api_major": client.capabilities["api_major"], "api_minor": client.capabilities["api_minor"],
                  "sdk_only": not any(name == "mesh_chat" or name.startswith("mesh_chat.") for name in sys.modules)}
        if "--create-profile" in sys.argv:
            report["created"] = client.create_profile("SDK qualification", "sdk-create-profile-key-0001")["display_name"] == "SDK qualification"
            print(json.dumps(report), file=sys.stderr)
            return 0
        profile = client.capabilities["profiles"][0]
        if "--keyed-owner" in sys.argv:
            client.create_workspace(profile, "SDK qualification", "", "sdk-workspace-create-key-0001")
            workspace = client.workspace_list(profile)["workspaces"][0]["workspace"]
            result = client.workspace_admission_grant_list(profile, workspace, "sdk-admission-list-key-0001")
            report["listed"] = isinstance(result, dict)
        elif "--keyed-join" in sys.argv:
            document = Path(sys.argv[sys.argv.index("--document-file") + 1]).read_text()
            result = client.workspace_join(profile, document, "sdk-workspace-join-key-0001")
            report["joined"] = result["state"] in {"joining", "active", "pending"}
        elif "--exercise-composer" in sys.argv:
            peer = client.profile(profile)["peers"][0]
            current = client.composer_query(profile, peer)
            saved = client.composer_update(profile, peer, current["revision"], "SDK qualification composer", current["update_key"])
            accepted = client.enqueue_draft(profile, peer, saved["applied_revision"])
            report.update(accepted=accepted["accepted"], draft_empty=accepted["composer"]["text"] == "",
                replay_same_message=client.enqueue_draft(profile, peer, saved["applied_revision"])["message"] == accepted["message"])
        elif "--recover-composer" in sys.argv:
            peer = client.profile(profile)["peers"][0]
            current = client.composer_query(profile, peer)
            last = current["last_send"]
            assert last["status"] == "accepted"
            accepted = client.enqueue_draft(profile, peer, last["revision"])
            report.update(recovered_acceptance=accepted["message"] == last["acceptance"]["message"],
                          draft_empty=accepted["composer"]["text"] == "")
        elif "--legacy" in sys.argv:
            peer = client.profile(profile)["peers"][0]
            report["accepted"] = client.enqueue(profile, peer, "SDK qualification legacy", "sdk-legacy-caller-key-0001")["accepted"]
        print(json.dumps(report), file=sys.stderr)
    except CoreClientError as error:
        print(json.dumps({"failure": error.code, "uncertain": True}), file=sys.stderr)
        return 2
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
