# Ownership status connector

This optional MCP adapter exposes one zero-argument tool,
`dotbox_ownership_status`, around the existing ownership coordinator. It reads
sampled viewer state. A response is neither an input grant nor a turn lease.
Dot's existing desktop tools remain responsible for keyboard and mouse actions.

## Local use

From the source checkout, install the optional test and connector dependencies:

```sh
python -m pip install '.[test,connector]'
dotbox-ownership-connector --session '<private-directory>/session.json' \
  --viewer-id '<lowercase-viewer-sha256>' --port 8787 --local-test
```

Use a current coordinator descriptor with `kind="ownership-coordinator"`.
An older unmarked coordinator needs a deliberate stop/restart through its normal
controls. Never manually add this marker to an old or game session. The reader
pins the descriptor's receiver instance and the supplied viewer binding; it
refuses game/publisher descriptors and does not follow a replacement receiver.
See [the ownership bridge](OWNERSHIP_BRIDGE.md) for coordinator preparation.

The launcher binds only `127.0.0.1` and serves `/mcp`. It generates a separate
local Bearer credential with a 600-second lifetime. Startup prints its private
token-file path, resource URL, scope and expiry, never the token. The token file
is removed when the credential context closes; stop the launcher when finished.
Its required scope is `dotbox.ownership.read`. This fixture has no functioning
OAuth authorization server and cannot provide ChatGPT login.

For an authenticated local SDK call, read the token privately from the printed
file and pass it as an HTTP header:

```python
from pathlib import Path
import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

token = Path("<printed-token-file>").read_text().strip()
async with httpx2.AsyncClient(
    headers={"Authorization": f"Bearer {token}"},
    trust_env=False, timeout=5.0,
) as http:
    transport = streamable_http_client("http://127.0.0.1:8787/mcp", http_client=http)
    async with Client(transport, cache=None) as client:
        result = await client.call_tool("dotbox_ownership_status", {})
        assert not result.is_error
        print(result.structured_content)
```

Run this inside an async function. Do not print or share the credential.

## Data and limits

The response contains exactly nine fields: `available`, `owner`, `source`,
`viewer_mode`, `connection`, `fresh`, `expires_in_ms`, `epoch` and `sequence`.
This reveals coarse human/Dot presence and the sampled state of one selected
viewer. It excludes credentials, identifiers, file paths, frames and raw errors.
Every call reads the local coordinator again without retaining a last-good
snapshot. Remaining freshness subtracts the coordinator round trip; it does not
include later MCP network delay. Check the result's freshness and unknown states;
even a fresh Dot observation does not authorize input.

The remote surface offers no turn operations, shutdown, publishing, input,
frames, file access, shell or SSH. The connector process holds the normal local
coordinator credential, which also permits turn operations and coordinator
shutdown. The fixed tool prevents remote operation selection; it does not
protect that credential from a compromised connector process.

## Connection review

[The permissions proposal](../connectors/ownership/permissions.review.json)
is prepared for review, not activation. No public endpoint, domain, DNS change,
OAuth registration, cloud access or ChatGPT connection is enabled.
`create_server` accepts an external token verifier and issuer/resource URLs for
later integration; it neither selects nor implements an authorization provider.
Activation still requires final endpoint and owner/client bindings, HTTPS,
OAuth 2.1 authorization code with PKCE, resource/audience validation,
issuer/signature/expiry/scope checks and DNS-rebinding protection.
[ChatGPT's authentication requirements](https://developers.openai.com/plugins/build/auth)
do not support a custom static Bearer API key as a substitute for this flow.

Local qualification uses real authenticated MCP HTTP and a synthetic ownership
publisher. It does not establish a live viewer connection, original-Dot access,
desktop input, handoff or interruption recovery. Sound and gameplay remain
deferred.
