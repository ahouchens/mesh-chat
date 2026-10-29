"""Bounded 100-room qualification on an explicitly selected, owned Worker.

Uses synthetic encrypted maximum-size documents, no identities or chat data.
Schedules below the single-IP budgets so shared staging access needs no bypass.
Last ten minutes stop writes and verify expiration. No secrets enter reports.
"""
from __future__ import annotations

import argparse
import heapq
import json
from pathlib import Path
import secrets
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "service" / "src"))
from mesh_chat.signal_crypto import MAX_DOCUMENT_BYTES, new_secret, seal
from mesh_chat.signal_mailbox import _NoRedirect, _context, USER_AGENT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Owned staging Worker or localhost Wrangler")
    parser.add_argument("--minutes", type=float, default=30)
    parser.add_argument("--pairs", type=int, default=100)
    parser.add_argument("--report", default="dist/reports/signal-mailbox-load.json")
    args = parser.parse_args()
    url = args.url.rstrip("/")
    parsed = urlsplit(url)
    if not (parsed.scheme == "https" or (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"})):
        parser.error("Use HTTPS, or HTTP on localhost only")
    if not 1 <= args.pairs <= 100 or args.minutes < 12:
        parser.error("Use 1-100 pairs and at least 12 minutes to exercise TTL cleanup")
    if args.minutes * 60 - 605 <= args.pairs * 3 * 0.65 + 5:
        parser.error("Increase duration to allow initial publication plus ten-minute cleanup")
    opener = urllib.request.build_opener(_NoRedirect(), urllib.request.HTTPSHandler(context=_context()))
    rooms = [(secrets.token_urlsafe(24), secrets.token_urlsafe(32), new_secret()) for _ in range(args.pairs)]
    events = []
    serial = 0
    def schedule(at, pair, role, method):
        nonlocal serial
        serial += 1
        heapq.heappush(events, (at, serial, pair, role, method))
    start = time.monotonic()
    end = start + args.minutes * 60
    stop_writes = end - 605
    for pair in range(args.pairs):
        for index, role in enumerate(("request", "offer", "answer")):
            schedule(start + (pair * 3 + index) * 0.65, pair, role, "PUT")
        for index, role in enumerate(("offer", "answer")):
            schedule(start + (pair * 3 + 2) * 0.65 + 5 + index * 0.15, pair, role, "GET")
    expiry = {}
    latencies = []
    counts = {"put": 0, "get": 0, "expired": 0, "unexpected": 0, "bytes_uploaded": 0}
    failures = {}
    next_progress = start
    while events:
        due, _, pair, role, method = heapq.heappop(events)
        if due > end:
            continue
        time.sleep(max(0, due - time.monotonic()))
        now = time.monotonic()
        if method == "PUT" and now >= stop_writes:
            continue
        session, token, secret = rooms[pair]
        payload = seal("x" * MAX_DOCUMENT_BYTES, secret, session, role) if method == "PUT" else None
        request = urllib.request.Request(f"{url}/v2/signal/{session}/{role}", data=payload,
            method=method, headers={"X-Mesh-Token": token, "Content-Type": "application/json", "User-Agent": USER_AGENT})
        began = time.monotonic()
        try:
            with opener.open(request, timeout=10) as response:
                status = response.status
                response.read(70 * 1024)
        except urllib.error.HTTPError as exc:
            status = exc.code
        except Exception:
            status = 0
        latencies.append((time.monotonic() - began) * 1000)
        counts[method.lower()] += 1
        expected_expired = method == "GET" and now >= expiry.get((pair, role), float("inf"))
        if status == 201 and method == "PUT":
            expiry[pair, role] = time.monotonic() + 600
            counts["bytes_uploaded"] += len(payload)
        elif status == 404 and expected_expired:
            counts["expired"] += 1
        elif status != 200 or method != "GET" or expected_expired:
            counts["unexpected"] += 1
            failures[str(status)] = failures.get(str(status), 0) + 1
        schedule(due + (300 if method == "PUT" else 60), pair, role, method)
        if now >= next_progress:
            print(json.dumps({"elapsed_minutes": round((now - start) / 60, 1), **counts}), flush=True)
            next_progress = now + 60
    latencies.sort()
    report = {"target": url, "runtime": "local" if parsed.hostname in {"127.0.0.1", "localhost"} else "hosted",
              "pairs": args.pairs, "minutes": args.minutes, "max_document_bytes": MAX_DOCUMENT_BYTES,
              **counts, "unexpected_statuses": failures,
              "p95_http_ms": round(latencies[int((len(latencies)-1)*0.95)], 2),
              "qualification": "synthetic HTTP storage/expiry load; not physical device reconnect or provider billing proof"}
    target = Path(args.report)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report), flush=True)
    return 1 if counts["unexpected"] or not counts["expired"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
