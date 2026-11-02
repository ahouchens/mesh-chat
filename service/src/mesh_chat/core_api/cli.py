"""Command-line client for the private core API over a host-owned pipe.

The CLI is a consumer, not a runtime: it never starts, stops or owns a service,
and it cannot widen the caller, permissions or profile scope the host binding
already fixed. Windows is the supported host target today; Android has no
binding yet.
"""

import argparse
import json

from .client import CoreClient, CoreClientError


def read_document(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read(65537)
    except OSError as error:
        raise CoreClientError("invalid_document") from error


def build_parser():
    parser = argparse.ArgumentParser(prog="mesh-chat-core",
                                     description="Query the private Mesh Chat Core API")
    parser.add_argument("--pipe", required=True,
                        help=r"host pipe name, for example \\.\pipe\mesh-chat-desktop")
    parser.add_argument("--profile", help="profile handle from capabilities")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("capabilities", help="negotiated operations and limits")
    commands.add_parser("profile", help="selected profile fields")
    received = commands.add_parser("received", help="page received messages")
    received.add_argument("--cursor")
    received.add_argument("--limit", type=int, default=128)
    events = commands.add_parser("events", help="poll the change stream")
    events.add_argument("--cursor")
    events.add_argument("--limit", type=int, default=128)
    enqueue = commands.add_parser("enqueue", help="durably enqueue text")
    enqueue.add_argument("--recipient", required=True)
    enqueue.add_argument("--text", required=True)
    enqueue.add_argument("--key", required=True)
    ack = commands.add_parser("ack", help="confirm a replay position")
    ack.add_argument("--cursor", required=True)
    ack.add_argument("--key", required=True)
    diagnostics = commands.add_parser("diagnostics", help="selected runtime diagnostics")
    diagnostics.add_argument("--limit", type=int, default=256)
    approve = commands.add_parser("approve", help="approve one pending peer")
    approve.add_argument("--peer", required=True)
    revoke = commands.add_parser("revoke", help="revoke one peer")
    revoke.add_argument("--peer", required=True)
    commands.add_parser("pairing-create", help="signed invitation material for this profile")
    pairing_accept = commands.add_parser("pairing-accept", help="accept a signed invitation file")
    pairing_accept.add_argument("--document-file", required=True)
    commands.add_parser("stop", help="ask the owning host to stop and close the stream")
    message = commands.add_parser("message", help="query one message")
    message.add_argument("--message", required=True)
    messages = commands.add_parser("messages", help="list the message snapshot")
    messages.add_argument("--cursor", default=None)
    messages.add_argument("--limit", type=int, default=128)
    connect = commands.add_parser("connect", help="enable a contact connection")
    connect.add_argument("--peer", required=True)
    disconnect = commands.add_parser("disconnect", help="stop a contact connection")
    disconnect.add_argument("--peer", required=True)
    pairing_request = commands.add_parser("pairing-request", help="send or resend a signed request")
    pairing_request.add_argument("--peer", required=True)
    commands.add_parser("workspace-list", help="list caller-scoped workspaces")
    queries = (
        ("workspace-requests", "list pending join requests", ("--workspace",)),
        ("workspace-members", "list workspace members", ("--workspace",)),
        ("workspace-channels", "list workspace channels", ("--workspace",)),
    )
    for name, help_text, options in queries:
        command = commands.add_parser(name, help=help_text)
        for option in options:
            command.add_argument(option, required=True)
    approve = commands.add_parser("workspace-approve", help="approve a join request")
    decline = commands.add_parser("workspace-decline", help="decline a join request")
    for command in (approve, decline):
        command.add_argument("--workspace", required=True)
        command.add_argument("--request", required=True)
        command.add_argument("--key", required=True)
    role = commands.add_parser("workspace-role", help="change a member role")
    role.add_argument("--workspace", required=True)
    role.add_argument("--member", required=True)
    role.add_argument("--role", required=True, choices=("admin", "member"))
    role.add_argument("--key", required=True)
    channel_create = commands.add_parser("workspace-channel-create", help="create a channel")
    channel_create.add_argument("--workspace", required=True)
    channel_create.add_argument("--name", required=True)
    channel_create.add_argument("--visibility", choices=("public", "private"), default="public")
    channel_create.add_argument("--member", action="append", dest="members", default=[])
    channel_create.add_argument("--key", required=True)
    channel_update = commands.add_parser("workspace-channel-update", help="edit a channel")
    channel_update.add_argument("--workspace", required=True)
    channel_update.add_argument("--channel", required=True)
    channel_update.add_argument("--name", required=True)
    channel_update.add_argument("--topic", default="")
    channel_update.add_argument("--key", required=True)
    channel_archive = commands.add_parser("workspace-channel-archive", help="archive a channel")
    channel_archive.add_argument("--workspace", required=True)
    channel_archive.add_argument("--channel", required=True)
    channel_archive.add_argument("--key", required=True)
    device_create = commands.add_parser("workspace-device-link-create", help="create a device link")
    device_create.add_argument("--workspace", required=True)
    device_create.add_argument("--key", required=True)
    device_preview = commands.add_parser("workspace-device-link-preview", help="preview a device link")
    device_preview.add_argument("--document-file", required=True)
    workspace_join = commands.add_parser("workspace-join", help="join from a signed invitation")
    workspace_join.add_argument("--document-file", required=True)
    invitation_preview = commands.add_parser("workspace-invitation-preview",
                                             help="preview a signed workspace invitation")
    invitation_preview.add_argument("--document-file", required=True)
    channel_members = commands.add_parser("workspace-channel-members",
                                          help="list a private channel roster")
    channel_members.add_argument("--workspace", required=True)
    channel_members.add_argument("--channel", required=True)
    channel_members_update = commands.add_parser("workspace-channel-members-update",
                                                 help="replace a private channel roster")
    channel_members_update.add_argument("--workspace", required=True)
    channel_members_update.add_argument("--channel", required=True)
    channel_members_update.add_argument("--member", action="append", dest="members",
                                        required=True)
    channel_members_update.add_argument("--key", required=True)
    transfer_offer = commands.add_parser("workspace-channel-transfer-offer",
                                         help="offer a channel to a member")
    transfer_offer.add_argument("--workspace", required=True)
    transfer_offer.add_argument("--channel", required=True)
    transfer_offer.add_argument("--member", required=True)
    transfer_offer.add_argument("--key", required=True)
    transfer_accept = commands.add_parser("workspace-channel-transfer-accept",
                                          help="accept an offered channel")
    transfer_accept.add_argument("--workspace", required=True)
    transfer_accept.add_argument("--channel", required=True)
    transfer_accept.add_argument("--key", required=True)
    policy_update = commands.add_parser("workspace-policy-update",
                                        help="set workspace policies")
    policy_update.add_argument("--workspace", required=True)
    policy_update.add_argument("--channel-creation", required=True,
                               choices=("all_members", "owner_and_admins"))
    policy_update.add_argument("--posting", required=True,
                               choices=("all_members", "owner_and_admins"))
    policy_update.add_argument("--invitation-requests", required=True,
                               choices=("owner_only", "owner_and_admins",
                                        "all_members_request"))
    policy_update.add_argument("--key", required=True)
    submit = commands.add_parser("workspace-device-link-submit",
                                 help="submit a device link on this device")
    submit.add_argument("--document-file", required=True)
    submit.add_argument("--key", required=True)
    links = commands.add_parser("workspace-device-links",
                                help="list pending device-link approvals")
    links.add_argument("--workspace", required=True)
    for name, help_text in (("workspace-device-link-approve", "approve a device link"),
                            ("workspace-device-link-decline", "decline a device link")):
        decision = commands.add_parser(name, help=help_text)
        decision.add_argument("--workspace", required=True)
        decision.add_argument("--request", required=True)
        decision.add_argument("--key", required=True)
    devices = commands.add_parser("workspace-devices", help="list workspace devices")
    devices.add_argument("--workspace", required=True)
    device_remove = commands.add_parser("workspace-device-remove",
                                        help="remove a linked device")
    device_remove.add_argument("--workspace", required=True)
    device_remove.add_argument("--device", required=True)
    device_remove.add_argument("--key", required=True)
    return parser


def execute(args, client):
    profile = args.profile or client.capabilities["profiles"][0]
    if args.command == "capabilities":
        return client.capabilities
    if args.command == "profile":
        return client.profile(profile)
    if args.command == "received":
        return client.received(profile, args.cursor, args.limit)
    if args.command == "events":
        return client.poll(profile, args.cursor, args.limit)
    if args.command == "enqueue":
        return client.enqueue(profile, args.recipient, args.text, args.key)
    if args.command == "ack":
        return client.acknowledge(profile, args.cursor, args.key)
    if args.command == "diagnostics":
        return client.diagnostics(profile, args.limit)
    if args.command == "approve":
        return client.approve(profile, args.peer)
    if args.command == "revoke":
        return client.revoke(profile, args.peer)
    if args.command == "pairing-create":
        return client.pairing_create(profile)
    if args.command == "pairing-accept":
        try:
            with open(args.document_file, encoding="utf-8") as handle:
                document = handle.read(1048577)
        except OSError as error:
            raise CoreClientError("invalid_document") from error
        return client.pairing_accept(profile, document)
    if args.command == "stop":
        return client.stop()
    if args.command == "message":
        return client.message_query(profile, args.message)
    if args.command == "messages":
        return client.message_list(profile, args.cursor, args.limit)
    if args.command == "connect":
        return client.connection_start(profile, args.peer)
    if args.command == "disconnect":
        return client.connection_stop(profile, args.peer)
    if args.command == "pairing-request":
        return client.pairing_request(profile, args.peer)
    if args.command == "workspace-list":
        return client.workspace_list(profile)
    if args.command == "workspace-requests":
        return client.workspace_join_requests(profile, args.workspace)
    if args.command == "workspace-members":
        return client.workspace_members(profile, args.workspace)
    if args.command == "workspace-channels":
        return client.workspace_channels(profile, args.workspace)
    if args.command == "workspace-approve":
        return client.workspace_join_approve(profile, args.workspace, args.request, args.key)
    if args.command == "workspace-decline":
        return client.workspace_join_decline(profile, args.workspace, args.request, args.key)
    if args.command == "workspace-role":
        return client.workspace_member_role(profile, args.workspace, args.member,
                                            args.role, args.key)
    if args.command == "workspace-channel-create":
        return client.workspace_channel_create(
            profile, args.workspace, args.name, args.key,
            visibility=args.visibility, members=args.members)
    if args.command == "workspace-channel-update":
        return client.workspace_channel_update(profile, args.workspace, args.channel,
                                               args.name, args.topic, args.key)
    if args.command == "workspace-channel-archive":
        return client.workspace_channel_archive(profile, args.workspace, args.channel,
                                                args.key)
    if args.command == "workspace-device-link-create":
        return client.workspace_device_link_create(profile, args.workspace, args.key)
    if args.command == "workspace-device-link-preview":
        return client.workspace_device_link_preview(
            profile, read_document(args.document_file))
    if args.command == "workspace-join":
        return client.request("workspace.join",
                              {"profile": profile, "document": read_document(args.document_file)})
    if args.command == "workspace-invitation-preview":
        return client.workspace_preview(profile, read_document(args.document_file))
    if args.command == "workspace-channel-members":
        return client.workspace_channel_members(profile, args.workspace, args.channel)
    if args.command == "workspace-channel-members-update":
        return client.workspace_channel_members_update(
            profile, args.workspace, args.channel, args.members, args.key)
    if args.command == "workspace-channel-transfer-offer":
        return client.workspace_channel_transfer_offer(
            profile, args.workspace, args.channel, args.member, args.key)
    if args.command == "workspace-channel-transfer-accept":
        return client.workspace_channel_transfer_accept(
            profile, args.workspace, args.channel, args.key)
    if args.command == "workspace-policy-update":
        return client.workspace_policy_update(
            profile, args.workspace, args.channel_creation, args.posting,
            args.invitation_requests, args.key)
    if args.command == "workspace-device-link-submit":
        return client.workspace_device_link_submit(
            profile, read_document(args.document_file), args.key)
    if args.command == "workspace-device-links":
        return client.workspace_device_links(profile, args.workspace)
    if args.command == "workspace-device-link-approve":
        return client.workspace_device_link_approve(
            profile, args.workspace, args.request, args.key)
    if args.command == "workspace-device-link-decline":
        return client.workspace_device_link_decline(
            profile, args.workspace, args.request, args.key)
    if args.command == "workspace-devices":
        return client.workspace_devices(profile, args.workspace)
    if args.command == "workspace-device-remove":
        return client.workspace_device_remove(
            profile, args.workspace, args.device, args.key)
    raise CoreClientError("unsupported_operation")


def run(argv, transport, out, err):
    """Run one command over an already-connected transport; returns an exit code."""
    args = build_parser().parse_args(argv)
    try:
        client = CoreClient.open(transport.readline, transport.write)
        result = execute(args, client)
    except CoreClientError as error:
        err.write(json.dumps({"error": error.code, "request_id": error.request_id}) + "\n")
        return 2
    except ValueError as error:
        err.write(json.dumps({"error": "protocol", "detail": str(error)[:120]}) + "\n")
        return 2
    out.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return 0


def main(argv=None):
    import sys
    from . import __version__

    args = sys.argv[1:] if argv is None else argv
    if args == ["--version"]:
        sys.stdout.write(__version__ + "\n")
        return 0
    parsed = build_parser().parse_args(args)
    try:
        from .pipe_client import connect
        transport = connect(parsed.pipe)
    except RuntimeError:
        sys.stderr.write(json.dumps({"error": "unsupported_platform"}) + "\n")
        return 2
    except OSError:
        sys.stderr.write(json.dumps({"error": "transport_unavailable"}) + "\n")
        return 2
    try:
        return run(args, transport, sys.stdout, sys.stderr)
    finally:
        transport.close()
