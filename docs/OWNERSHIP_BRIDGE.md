# Viewer ownership bridge

The bridge coordinates cooperating desktop callers from sampled observations of
the existing viewer UI. It is a decision fence around an action, not an atomic
tool-capture lock or a server ownership lease. A takeover and return occurring
entirely between samples can be missed. The outer harness continues to own input
capture and any input already in flight.

The bridge is **off by default**. Without `--ownership-viewer`, session status
retains exactly `{"owner":"unknown","source":"unavailable"}` for
`platform_takeover`. Enabling it preserves session `owner="harness"`,
`native_owner="host"` and the desktop input path. Direct native agent input stays
disabled; `--manual-control` cannot be combined with the bridge.

## Enable and bind one viewer

Add `--ownership-viewer <viewer-sha256>` to the existing verified `dotbox serve`
invocation. The binding is lowercase SHA-256 of the **complete URL string** in
the selected browser tab's fresh CUA snapshot header. The observer also requires
the header URL and root AX web-area URL to agree. A Dot name or hostname alone
does not bind a viewer. Keep the URL and all connection/chat identifiers private.

The service creates two private descriptors in its existing session directory:

| Descriptor | Capability |
| --- | --- |
| `session.json` | Normal session client and cooperating turn operations. |
| `ownership-publisher.json` | Publish ownership evidence only. Its separate credential cannot inspect frames, claim turns, inject input, pause or close the game. |

Descriptors refer to private credential files; they contain no inline token.
Do not copy provider credentials or put credentials in command arguments. Session
directories require mode 0700; descriptor, credential and mailbox files remain
private regular files. Stopping the service removes its published descriptors.

Inspect the actual interfaces before configuring a route:

```sh
dotbox serve --help
dotbox turn-claim --help
dotbox turn-check --help
dotbox turn-release --help
python -m dotbox.ownership_publisher --help
python -m dotbox.ownership_source --help
```

## Publish fresh evidence

The data-only `OwnershipState(viewer_id, ttl=3.0)` exposes `open`, `challenge`,
`observe`, `invalidate`, `status`, `claim`, `check` and `release`. It performs no
authentication or native input. `PlayService` supplies the authenticated,
serialized interface and session binding.

The receiver uses its own monotonic clock. The default observation TTL is three
seconds, beginning when it issues a challenge, **not** when an event arrives.
No remote wall clock can extend it.

1. An authenticated `bridge-open` binds `viewer_id`, creates a random stream ID
   and invalidates earlier leases.
2. `bridge-challenge` issues a one-use random challenge and next sequence.
3. The source observes the selected UI after receiving that probe and returns
   exactly `stream_id`, `challenge`, `sequence`, `owner`, `viewer_mode` and
   `connection`.
4. `bridge-observe` consumes the challenge. Dot eligibility requires `owner=dot`,
   `viewer_mode=observe` and `connection=live`. Human, partial, contradictory,
   unknown or expired evidence cannot authorize an agent turn.

Old streams and reordered/replayed probes are rejected. Publisher replacement,
invalidation and expired evidence invalidate turn leases; current-stream
malformed observations also revoke the grant. Changes to the native
run/session/control identity invalidate
coordination. A fresh heartbeat never extends an already issued lease's original
deadline or revives its token after invalidation.

The finite publisher accepts a private JSON **argument-list** file for an
already authorized transport, such as an existing SSH route. It invokes that
command without a local shell, sends one JSON probe on stdin, and accepts one
bounded JSON event on stdout. It adds no network listener, tunnel or account.
Timeout/error cleanup terminates the invocation's owned process group; publisher
exit explicitly invalidates its stream, with receiver expiry as fallback.

```sh
python -m dotbox.ownership_publisher \
  --publisher '<session-directory>/ownership-publisher.json' \
  --viewer-id '<viewer-sha256>' \
  --source-command '<private-command-arguments.json>' \
  --duration 30 --interval 0.1
```

Replace the placeholders with private operator-selected values. The configured
source command can run `python -m dotbox.ownership_source` using its documented
`--directory`, `--viewer-id` and `--timeout` arguments. It forwards the probe into
an existing private source-host mailbox, correlates the response with another
random request nonce, and returns the event on stdout. An old response cannot
satisfy a new request. The source exchange opens no listener.

## Run the bounded viewer observer

[The authored observer](../scripts/observe_ownership.mjs) exports
`pumpMailbox(tab, dotName, options)` for the supported CUA browser context:

```js
await pumpMailbox(tab, dotName, {
  directory: mailboxDirectory,
  viewerId,
  ownerUid,
  durationMs: 30000,
  onObservation: recordSample,
});
```

Use the already selected browser `tab`, the expected Dot name and the same full
URL hash as the receiver. Supply `ownerUid` from trusted host configuration;
CUA forbids `node:process`, so the observer deliberately does not discover it
through that module or trust a mailbox's claimed owner. The mailbox must already
exist with mode 0700 and that UID. The pump validates small 0600 regular files,
directory identity and unchanged probes before atomically writing responses.

Each new probe requests a full AX snapshot through `tab.getAXState`. The parser
requires the selected computer panel, matching owner text and checkbox, and the
expected live-viewer structure. Here `connection=live` describes that UI, not
an independent server liveness check. A stalled UI may retain labels. Missing,
ambiguous, disconnected, mismatched or
failed observations yield unknown. Raw AX text and URLs are not returned by the
pump. Its optional callback receives a compact sample and hashes before response
delivery; that callback and the pump's processed count are not receiver
acknowledgements. Runs are finite, with a maximum pump duration of 60 seconds.

## Gate cooperating actions

The ordinary client supports:

```python
lease = client.wait_for_turn(controller_id, timeout=10, interval=0.1)
result = client.run_turn_step(lease, action)
```

`action` is one already authorized, zero-argument desktop callback.
`wait_for_turn` waits locally while the service continues accepting source
updates; fresh Dot evidence after human return can admit the next turn.
`run_turn_step` checks the lease before and after the callback. It refuses to
start on stale evidence and raises `TurnInterrupted` if the action fails, the
post-check fails or ownership changes. Its `result`, when present, preserves the
completed callback outcome. Inspect the current desktop before deciding what to
do next; no game effect is automatically replayed or rolled back.

Only one cooperating controller holds a turn lease. Treat its JSON receipt as
opaque and unchanged: it binds viewer, stream, epoch, sequence, controller and a
random lease ID. Its expiry value describes issuance, not a renewal. Release a
completed turn with `client.request("turn-release", {"lease": lease})`.
CLI `turn-claim`, `turn-check` and `turn-release` expose the same operations; keep
saved claim receipts private. These turn leases are separate from the existing
native generation leases. Arbitrary desktop tools that bypass this wrapper are
not fenced by it.

## Verification boundary — 16 November 2026

Local state, authenticated socket, transport and callback checks exercise this
contract. The full source suite passes 333 checks with no skips. A fresh ordinary
wheel installation passes 76 focused checks, including ten existing native/input
checks, and matches all 20 runtime module identities. The Node observer passes
35 cases. Native/input tests remain separate from the bridge's live qualification.

The existing Dot viewer supplied 93 compact observations accepted by a **local,
data-only `OwnershipState` receiver**: 89 Dot-eligible and four human-blocked.
Eight failed source exchanges stayed blocked. Reconnection produced 24 fresh Dot
observations while the earlier lease stayed invalid, and the final viewer UI
showed Dot control. These results do not place the receiver on Dot's computer
or demonstrate a live desktop action through `run_turn_step`.

Hosted verification remains blocked by the managed runtime's repository-account
startup failure. There is no qualified Dot cloud receiver/deployment, atomic
capture lock, server lease or guarantee against missed between-poll transitions.
Keep raw observations, screenshots, routes, credentials and environment/chat IDs
outside Git. Audio and gameplay work remain deferred.

The [sanitized verification report](evidence/ownership-bridge-2026-11-16.json)
records the package identities, checks, bounded live witness and remaining gate.
