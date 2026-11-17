# DotBox ownership connector

Approved scope: user request of 16 November 2026. Build the smallest connector
around the existing coordinator, verify read-only ownership locally, prepare
connection permissions for review and update draft PR #2. Deployment and the
actual ChatGPT connection require a later reviewed decision.

## Purpose and interaction

Dot needs fresh ownership information in her original chat without switching
computers. The existing coordinator and viewer observer already provide those
facts. One zero-argument MCP tool, `dotbox_ownership_status`, reads the explicitly
bound coordinator and returns a filtered snapshot. No new view is needed.
Dot's existing keyboard/mouse harness remains authoritative.

The response is observational only. It is not an input grant or a turn lease;
freshness describes the coordinator snapshot and is not renewed by the connector.
Every invocation reads again. Unknown, expired and unavailable states must stay
visible. No last-good result is retained after a failure.

## Implementation boundaries

- Reuse `CoordinationService`, `Client` and their authenticated loopback transport.
- Add a coordinator descriptor kind marker and refuse ordinary game/publisher
  descriptors before making a backend request. Verify the response kind and
  instance as well. Old unmarked coordinators need a deliberate restart.
- Expose only owner, source, viewer mode, connection, freshness, remaining time,
  epoch and sequence. Do not disclose session/stream/viewer IDs, paths, tokens,
  frames, game state or raw backend errors.
- The local MCP prototype uses the pinned official Python SDK (`mcp==2.3.0`)
  as an optional extra. The existing Python engine keeps its normal dependencies.
- Authenticate real Streamable HTTP requests, enforce the read scope and exact
  resource audience, and bind the local test launcher to IPv4 loopback only.
- Keep the local MCP bearer token separate from coordinator and publisher
  credentials. It is a local test fixture, not a ChatGPT login solution.
- Provide a resource-server factory accepting an operator-supplied token verifier
  and issuer/resource configuration for later OAuth integration. No issuer,
  public hostname, callback, deployment or account connection is activated here.

## Permissions for review

Exactly one read-only tool and one scope: `dotbox.ownership.read`. No turn
claim/check/release, publishing, shutdown, shell, file selection, keyboard/mouse,
native operations, sound or gameplay. The server's coordinator credential stays
local to its process; the remote caller receives no coordinator capability.
That local credential currently also authorizes coordinator turn/shutdown calls;
the adapter's fixed operation prevents callers selecting them, but does not
isolate a compromised server process from its local credential.

The later public connection needs HTTPS, an approved OAuth 2.1 authorization
server, authorization code + PKCE, resource-bound access tokens, expiry/scope
verification and an explicitly reviewed user/session binding. Static bearer/API
keys alone are not a supported ChatGPT authorization flow. These are activation
prerequisites, not delivered authentication-provider functionality.

## Acceptance evidence

Use a real no-backend coordinator, its actual publisher and authenticated MCP
HTTP requests through the SDK client. Demonstrate Dot, human, expiry,
invalidation, receiver failure/replacement, no cached fallback, exact tool/data
surface and rejected unauthenticated/wrong-scope/wrong-resource/extra-argument
requests. Refuse game and publisher descriptors before sending a request.
Keep native/backend operations untouched. Run source regression and isolated
installed-package checks; preserve a sanitized local receipt.

The local HTTP proof does not establish a connected ChatGPT app, original-Dot
network access, desktop input, automatic handoff or interruption recovery with
actual keyboard/mouse. Sound and gameplay remain deferred.
