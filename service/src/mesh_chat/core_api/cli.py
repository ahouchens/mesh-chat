"""Command-line client for the private core API over a host-owned pipe.

The CLI is a consumer, not a runtime: it never starts, stops or owns a service,
and it cannot widen the caller, permissions or profile scope the host binding
already fixed. Windows is the supported host target today; Android has no
binding yet.
"""

import argparse
import json

from .client import CoreClient, CoreClientError


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
    args = sys.argv[1:] if argv is None else argv
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
