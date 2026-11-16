# Saved environment startup and ownership delivery

Verified on 16 November 2026. These are separate acceptance checks:

1. The intended GitHub connection can read the private repository and branch.
2. A fresh ordinary task from the existing saved configuration starts and
   checks out that repository.
3. Its managed VPN can reach the existing private source host over SSH.
4. Fresh observations from the actual viewer reach the authenticated receiver
   and fence the cooperating action.

The first two now pass. Two existing account connections initially had the same
display label. Their actual profile identities were checked, the misleading
label was corrected, and the intended existing connection was refreshed. Both
connections were retained; repository grants and saved environment settings
were unchanged. The setup editor and one fresh regular verification task both
opened the correct private repository on its intended branch and exact head.
Python 3.12.14 ran in the fresh task. The original failed task remains unusable.

The saved configuration catalog omits the repository's account-link field, and
the setup editor's offered update schema does not expose it. Successful fresh
checkout verifies restored operation, rather than proving which hidden field
caused the original failure. An "Unknown repository" label alone was not a
reliable startup verdict. The settings DOM also exposed an enabled Edit action
where the coarser accessibility snapshot had described it as disabled.

The third check currently fails: managed VPN status reports Running and routing
ready, but the existing primary SSH helper receives HTTP CONNECT 503 with an
upstream connection timeout. One separate banner-only check to the other
already configured private host gives the same timeout. No SSH authentication
or fallback was attempted after those transport failures. The source machine
is independently online with its existing Tailscale SSH setting enabled.
This does not establish whether the fault is routing, source authorization or
another upstream problem. No network policy, enrollment or credentials changed.

Use supported status and the actual client to resolve that transport gate.
Preserve the old runtime and unchanged setup draft. Do not disconnect the other
GitHub account, grant access to it, or broadly allow new network identities to
work around a failed lookup or connection. Keep runtime identifiers, account
aliases, raw status, routes and screenshots private.

The fourth check remains open. The coordination-only receiver reuses the
existing service boundary and can be prepared without a native emulator; a
local or synthetic callback is not proof of live cloud desktop input.
See the [sanitized verification receipt](evidence/ownership-coordinator-2026-11-16.json).
