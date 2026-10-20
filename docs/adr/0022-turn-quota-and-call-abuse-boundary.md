# 0022: TURN quota and call-abuse boundary

Status: accepted for the WebRTC call surface. Mesh Chat does not operate a TURN
service.

## Context

A TURN server relays media when direct ICE fails. Relay bandwidth is the
operator's cost, and an unauthenticated or unbounded relay is an abuse target.
Mesh Chat accepts user-supplied STUN/TURN endpoints and short-lived credentials
but does not ship or operate a TURN service.

The client can reduce accidental and malicious call spam, but it cannot enforce
a server operator's bandwidth quota.

## Decision

1. TURN quota enforcement is the TURN operator's responsibility. Mesh Chat does
   not promise a global relay quota.
2. Mesh Chat stores TURN credentials in the encrypted service record and hands
   them only to an active call. It never puts them in snapshots or diagnostics.
3. Mesh Chat rate-limits outbound call attempts per contact: three per minute
   and twenty per hour. The limit is enforced before signing or sending an
   invitation.
4. Completed call records are retained for at most 24 hours to bound the local
   call table.
5. Operators should issue short-lived TURN credentials, scope them to one
   session, and enforce their own bandwidth/concurrency limits.
6. A TURN failure is a call failure, never a fallback to a different contact,
   relay, or consent state.

## Consequences

- Mesh Chat cannot guarantee TURN availability or cost.
- Relay credentials remain a deployment responsibility.
- Local call spam is bounded without a central service.
- A future Mesh Chat-operated TURN service would need a separate quota,
  abuse, and privacy review.
