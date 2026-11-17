"""One read-only MCP projection of an explicitly bound ownership coordinator.

The optional SDK is imported only when building/launching the MCP server. The
local launcher is a bearer-authenticated test fixture, not a ChatGPT OAuth login.
"""

import argparse
import json
import math
import re
import sys
import time
from typing import Literal, TypedDict
from urllib.parse import urlsplit

from .client import Client
from .local_auth import LocalCredential


READ_SCOPE = "dotbox.ownership.read"
TOOL_NAME = "dotbox_ownership_status"
MAX_MCP_REQUEST = 8192


class OwnershipSnapshot(TypedDict):
    available: bool
    owner: Literal["dot", "human", "unknown"]
    source: Literal["codex-viewer-ui", "unavailable"]
    viewer_mode: Literal["observe", "control", "unknown"]
    connection: Literal["live", "disconnected", "unknown"]
    fresh: bool
    expires_in_ms: int
    epoch: int | None
    sequence: int | None


def unavailable() -> OwnershipSnapshot:
    return {"available": False, "owner": "unknown", "source": "unavailable",
            "viewer_mode": "unknown", "connection": "unknown", "fresh": False,
            "expires_in_ms": 0, "epoch": None, "sequence": None}


class OwnershipReader:
    """Pin one coordinator instance/viewer; never rebind or cache last success."""

    def __init__(self, descriptor, viewer_id, *, timeout=1.0):
        if not isinstance(viewer_id, str) or re.fullmatch(r"[0-9a-f]{64}", viewer_id) is None:
            raise ValueError("A lowercase viewer SHA-256 binding is required")
        if type(timeout) not in (int, float) or not 0.05 <= timeout <= 2:
            raise ValueError("Choose a bounded coordinator timeout")
        client = Client(descriptor, timeout=timeout)
        if (client.descriptor.get("kind") != "ownership-coordinator"
                or "role" in client.descriptor):
            raise ValueError("Use a current coordinator session descriptor, not a game or publisher")
        self._client = client
        self._instance_id = client.descriptor["instance_id"]
        self._viewer_id = viewer_id

    def read(self) -> OwnershipSnapshot:
        started = time.monotonic_ns()
        try:
            reply = self._client.request("status")
            elapsed = max(0, math.ceil((time.monotonic_ns() - started) / 1_000_000))
            if reply.get("ok") is not True:
                return unavailable()
            current = reply["result"]
            if (current["kind"] != "ownership-coordinator"
                    or current["instance_id"] != self._instance_id):
                return unavailable()
            raw = current["platform_takeover"]
            if (raw["viewer_id"] != self._viewer_id
                    or raw["owner"] not in ("dot", "human", "unknown")
                    or raw["source"] not in ("codex-viewer-ui", "unavailable")
                    or raw["viewer_mode"] not in ("observe", "control", "unknown")
                    or raw["connection"] not in ("live", "disconnected", "unknown")
                    or type(raw["fresh"]) is not bool
                    or (raw["fresh"] and raw["source"] != "codex-viewer-ui")
                    or any(type(raw[k]) is not int or raw[k] < 0
                           for k in ("epoch", "sequence", "expires_in_ms"))
                    or raw["expires_in_ms"] > 3000
                    or (raw["owner"] == "dot" and
                        (raw["viewer_mode"] != "observe" or raw["connection"] != "live"))):
                return unavailable()
            remaining = max(0, raw["expires_in_ms"] - elapsed)
            fresh = raw["fresh"] and remaining > 0
            return {"available": True,
                    "owner": raw["owner"] if fresh else "unknown",
                    "source": raw["source"],
                    "viewer_mode": raw["viewer_mode"] if fresh else "unknown",
                    "connection": raw["connection"] if fresh else "unknown",
                    "fresh": fresh, "expires_in_ms": remaining if fresh else 0,
                    "epoch": raw["epoch"], "sequence": raw["sequence"]}
        except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError):
            # Descriptors, tokens, IDs, raw replies and exception text stay local.
            # A response failure never returns the previous successful snapshot.
            return unavailable()


def _http_url(value):
    parsed = urlsplit(value)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment
            or (parsed.scheme == "http" and parsed.hostname not in
                ("127.0.0.1", "localhost", "::1"))):
        raise ValueError("Use HTTPS URLs, or HTTP loopback for local testing")
    _ = parsed.port  # Reject malformed/out-of-range ports before SDK construction.
    return parsed


def create_server(reader, *, token_verifier, issuer_url, resource_url):
    """Build a protected MCP resource server; the approved issuer is external.

    A production verifier must validate issuer/signature/audience/expiry/scope.
    This factory neither issues tokens nor configures an authorization server.
    """
    from mcp.server import MCPServer
    from mcp.server.auth.middleware.auth_context import get_access_token
    from mcp.server.auth.settings import AuthSettings
    from mcp.server.mcpserver.exceptions import ToolError
    from mcp_types import ToolAnnotations
    from pydantic import AnyHttpUrl

    if not isinstance(reader, OwnershipReader) or token_verifier is None:
        raise ValueError("A bound ownership reader and token verifier are required")
    _http_url(issuer_url)
    if _http_url(resource_url).path != "/mcp":
        raise ValueError("The resource URL must identify the exact /mcp endpoint")
    class ReadOnlyServer(MCPServer):
        # The pinned SDK normally ignores extra function arguments. Enforce the
        # closed public schema before its argument conversion drops those keys.
        async def list_tools(self):
            tools = await super().list_tools()
            return [tool.model_copy(update={"input_schema": {
                "type": "object", "properties": {}, "additionalProperties": False}})
                    for tool in tools if tool.name == TOOL_NAME]

        async def call_tool(self, name, arguments, context=None):
            if name != TOOL_NAME or arguments != {}:
                raise ToolError("This connector exposes only dotbox_ownership_status with no arguments")
            return await super().call_tool(name, arguments, context)

    server = ReadOnlyServer(
        "DotBox ownership", version="0.1.0.dev1", log_level="WARNING",
        instructions=("Read-only sampled viewer ownership. Every result is a snapshot, "
                      "not permission to inject input and not a turn lease. "
                      "It may be stale when received. Existing desktop tools own input."),
        token_verifier=token_verifier,
        auth=AuthSettings(issuer_url=AnyHttpUrl(issuer_url),
                          resource_server_url=AnyHttpUrl(resource_url),
                          required_scopes=[READ_SCOPE], validate_token_resource=True),
        subscriptions=False,
    )

    @server.tool(name=TOOL_NAME,
                 description="Read the bound coordinator's ownership snapshot; never authorizes input.",
                 annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False,
                                             idempotent_hint=True, open_world_hint=False),
                 meta={"securitySchemes": [{"type": "oauth2", "scopes": [READ_SCOPE]}]})
    def ownership_status() -> OwnershipSnapshot:
        # The SDK's in-memory and stdio transports bypass HTTP authentication.
        # Refuse ownership data there as well as after a token expires in queue.
        token = get_access_token()
        if (token is None or READ_SCOPE not in token.scopes or token.resource != resource_url
                or token.expires_at is None or time.time() >= token.expires_at):
            raise ToolError("An authenticated, unexpired ownership-read HTTP token is required")
        return reader.read()

    return server


class LocalTestVerifier:
    """A separate short-lived credential for loopback HTTP tests, not OAuth."""

    def __init__(self, credential, resource_url, *, expires_at):
        self._credential = credential
        self._resource = resource_url
        self._expires_at = expires_at

    async def verify_token(self, token):
        from mcp.server.auth.provider import AccessToken
        if time.time() >= self._expires_at or not self._credential.check(token):
            return None
        return AccessToken(token=token, client_id="dotbox-local-test", scopes=[READ_SCOPE],
                           expires_at=int(self._expires_at), resource=self._resource)


def local_transport_security():
    from mcp.server.transport_security import TransportSecuritySettings
    return TransportSecuritySettings(enable_dns_rebinding_protection=True,
                                     allowed_hosts=["127.0.0.1:*"], allowed_origins=[])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True, help="Private coordinator session.json")
    parser.add_argument("--viewer-id", required=True, help="Expected lowercase viewer SHA-256")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--local-test", action="store_true",
                        help="Required: short-lived loopback bearer fixture, not ChatGPT OAuth")
    args = parser.parse_args(argv)
    if not args.local_test or not 1024 <= args.port <= 65535:
        parser.error("Use --local-test and an unprivileged port (1024..65535)")
    try:
        reader = OwnershipReader(args.session, args.viewer_id)
        resource = f"http://127.0.0.1:{args.port}/mcp"
        with LocalCredential("dotbox-mcp-local-") as credential:
            expires_at = int(time.time()) + 600
            verifier = LocalTestVerifier(credential, resource, expires_at=expires_at)
            server = create_server(reader, token_verifier=verifier,
                                   issuer_url=f"http://127.0.0.1:{args.port}/local-test-issuer",
                                   resource_url=resource)
            print(json.dumps({"local_test_only": True, "resource": resource,
                              "token_file": str(credential.path), "scope": READ_SCOPE,
                              "expires_at": expires_at}), flush=True)
            server.run(transport="streamable-http", host="127.0.0.1", port=args.port,
                       json_response=True, stateless_http=True,
                       max_request_body_size=MAX_MCP_REQUEST,
                       transport_security=local_transport_security())
        return 0
    except KeyboardInterrupt:
        return 130
    except ImportError:
        print("Install the optional dotbox[connector] dependency for this command.", file=sys.stderr)
        return 2
    except (OSError, ValueError):
        print("Connector configuration or local transport failed; inspect private operator state.",
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
