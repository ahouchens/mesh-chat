"""CLI argument-to-client mapping for workspace invitation creation."""

from mesh_chat.core_api import cli


class FakeClient:
    capabilities = {"profiles": ["profile-handle-0001"]}

    def __init__(self):
        self.calls = []

    def workspace_invitation_create(self, profile, workspace, key, **options):
        self.calls.append((profile, workspace, key, options))
        return {"profile": profile, "workspace": workspace}


def parse(*arguments):
    return cli.build_parser().parse_args(["--pipe", "pipe", *arguments])


def test_cli_maps_i2p_workspace_invitation_options():
    client = FakeClient()
    relay = "a" * 52 + ".b32.i2p"
    result = cli.execute(parse(
        "workspace-invitation-create", "--workspace", "w" * 64,
        "--mode", "i2p", "--i2p-access-point", relay,
        "--i2p-label", "Community relay", "--key", "k" * 32,
    ), client)
    assert result["workspace"] == "w" * 64
    assert client.calls == [("profile-handle-0001", "w" * 64, "k" * 32, {
        "connection_mode": "i2p", "i2p_access_point": relay,
        "i2p_label": "Community relay"})]


def test_cli_maps_default_mode_to_no_connection_mode():
    client = FakeClient()
    cli.execute(parse(
        "workspace-invitation-create", "--workspace", "w" * 64,
        "--key", "k" * 32,
    ), client)
    assert client.calls[0][3] == {
        "connection_mode": None, "i2p_access_point": None, "i2p_label": None}
