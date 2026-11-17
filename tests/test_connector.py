"""Local authenticated connector checks; no native backend or live desktop input."""

import asyncio
from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import socket
import signal
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from dotbox.client import Client
import dotbox.connector as connector
from dotbox.connector import (
    LocalTestVerifier, OwnershipReader, READ_SCOPE, TOOL_NAME, create_server,
    local_transport_security, unavailable,
)
from dotbox.coordination import CoordinationService
from dotbox.local_auth import LocalCredential
from dotbox.ownership import OwnershipState


VIEWER = "a" * 64
FIELDS = {"available", "owner", "source", "viewer_mode", "connection", "fresh",
          "expires_in_ms", "epoch", "sequence"}


class Receiver:
    """An actual serialized receiver/socket with a deterministic evidence clock."""

    def __init__(self, directory):
        self.directory = directory
        self.now = [100.0]
        self.service = CoordinationService(directory, VIEWER)
        self.service.ownership = OwnershipState(VIEWER, clock=lambda: self.now[0])
        ready = threading.Event()
        self.errors = []

        def run():
            try:
                self.service.run(on_ready=lambda _: ready.set())
            except BaseException as error:
                self.errors.append(error)
                ready.set()

        self.worker = threading.Thread(target=run)
        self.worker.start()
        assert ready.wait(3) and not self.errors
        self.descriptor = directory / "session.json"
        self.client = Client(self.descriptor, timeout=1)
        self.publisher = Client(directory / "ownership-publisher.json", timeout=1)
        self.stream = self.open()

    def open(self):
        reply = self.publisher.request("bridge-open", {"viewer_id": VIEWER})
        assert reply["ok"], reply
        self.stream = reply["result"]["stream_id"]
        return self.stream

    def publish(self, owner="dot", mode="observe", connection="live"):
        reply = self.publisher.request("bridge-challenge", {"stream_id": self.stream})
        assert reply["ok"], reply
        event = {k: reply["result"][k] for k in ("stream_id", "challenge", "sequence")}
        event.update(owner=owner, viewer_mode=mode, connection=connection)
        reply = self.publisher.request("bridge-observe", event)
        assert reply["ok"], reply
        return reply["result"]

    def stop(self):
        self.service.request_stop()
        self.worker.join(3)
        assert not self.worker.is_alive() and not self.errors
        assert self.service.backend is None


@pytest.fixture
def receiver(tmp_path):
    running = Receiver(tmp_path / "coordinator")
    try:
        yield running
    finally:
        running.stop()


class ClaimVariants:
    """Exercise resource middleware independently of a verifier's claim policy."""

    def __init__(self, normal, resource):
        self.normal, self.resource = normal, resource

    async def verify_token(self, token):
        from mcp.server.auth.provider import AccessToken
        if token in ("without-scope", "wrong-audience", "expired"):
            return AccessToken(token=token, client_id="negative-test",
                               scopes=[] if token == "without-scope" else [READ_SCOPE],
                               resource=(self.resource + "/other" if token == "wrong-audience"
                                         else self.resource),
                               expires_at=int(time.time()) + (-10 if token == "expired" else 60))
        return await self.normal.verify_token(token)


@contextmanager
def running_http(reader):
    pytest.importorskip("mcp")
    uvicorn = pytest.importorskip("uvicorn")
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(16)
    resource = f"http://127.0.0.1:{listener.getsockname()[1]}/mcp"
    with LocalCredential("dotbox-connector-test-") as credential:
        token = credential.path.read_text().strip()
        normal = LocalTestVerifier(credential, resource, expires_at=time.time() + 60)
        server = create_server(reader, token_verifier=ClaimVariants(normal, resource),
                               issuer_url=resource.removesuffix("/mcp") + "/issuer",
                               resource_url=resource)
        app = server.streamable_http_app(json_response=True, stateless_http=True,
                                        max_request_body_size=8192,
                                        transport_security=local_transport_security())
        runner = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", loop="asyncio",
                                             lifespan="on", log_config=None,
                                             log_level="critical", access_log=False,
                                             timeout_graceful_shutdown=2))
        errors = []

        def run():
            try:
                runner.run(sockets=[listener])
            except BaseException as error:
                errors.append(error)

        worker = threading.Thread(target=run)
        worker.start()
        try:
            deadline = time.monotonic() + 3
            while not runner.started:
                assert worker.is_alive() and not errors and time.monotonic() < deadline
                time.sleep(0.01)
            yield SimpleNamespace(url=resource, token=token, verifier=normal)
        finally:
            runner.should_exit = True
            worker.join(4)
            listener.close()
            assert not worker.is_alive() and not errors


@pytest.mark.parametrize("mode", ["auto", "legacy"])
def test_real_mcp_client_lists_one_read_tool_projects_only_status_and_rejects_arguments(receiver, mode):
    mcp = pytest.importorskip("mcp")
    httpx2 = pytest.importorskip("httpx2")
    from mcp.client.streamable_http import streamable_http_client

    receiver.publish()
    lease = receiver.client.wait_for_turn("existing-controller", timeout=0)
    reader = OwnershipReader(receiver.descriptor, VIEWER)
    with running_http(reader) as http:
        async def exercise():
            async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {http.token}"},
                                          trust_env=False) as transport:
                async with mcp.Client(streamable_http_client(http.url, http_client=transport),
                                      mode=mode, cache=None) as client:
                    tools = (await client.list_tools()).tools
                    assert [tool.name for tool in tools] == [TOOL_NAME]
                    tool = tools[0]
                    assert tool.input_schema.get("properties", {}) == {}
                    assert tool.input_schema.get("additionalProperties") is False
                    assert tool.annotations.read_only_hint is True
                    assert tool.annotations.destructive_hint is False
                    assert tool.annotations.idempotent_hint is True
                    assert tool.annotations.open_world_hint is False
                    assert tool.meta["securitySchemes"] == [{"type": "oauth2", "scopes": [READ_SCOPE]}]
                    first = await client.call_tool(TOOL_NAME)
                    assert first.is_error is False
                    state = first.structured_content
                    assert set(state) == FIELDS
                    assert state["available"] and state["fresh"] and state["owner"] == "dot"
                    serialized = json.dumps(first.model_dump(mode="json"))
                    for secret in (receiver.client.token, receiver.publisher.token, http.token,
                                   VIEWER, receiver.stream, receiver.service.instance_id,
                                   str(receiver.directory), "127.0.0.1", "password_file"):
                        assert secret not in serialized
                    rejected = await client.call_tool(TOOL_NAME, {"op": "coordinator-close"})
                    assert rejected.is_error is True
                    for name in ("turn-claim", "bridge-observe", "key", "coordinator-close"):
                        assert (await client.call_tool(name, {})).is_error
                    assert not receiver.service.stop_requested.is_set()
                    assert receiver.client.request("turn-check", {"lease": lease})["ok"]
                    receiver.publish("human", "control")
                    assert not receiver.client.request("turn-check", {"lease": lease})["ok"]
                    second = await client.call_tool(TOOL_NAME)
                    assert second.structured_content["owner"] == "human"
                    assert second.structured_content["epoch"] > state["epoch"]
                    receiver.now[0] += 4
                    expired = (await client.call_tool(TOOL_NAME)).structured_content
                    assert expired["available"] and not expired["fresh"]
                    assert expired["owner"] == "unknown" and expired["expires_in_ms"] == 0
                    receiver.stop()
                    failed = await client.call_tool(TOOL_NAME)
                    assert not failed.is_error and failed.structured_content == unavailable()

        asyncio.run(exercise())
    assert receiver.service.backend is None
    assert not receiver.worker.is_alive()


def test_in_memory_transport_does_not_bypass_ownership_tool_authentication(receiver, monkeypatch):
    mcp = pytest.importorskip("mcp")
    reader = OwnershipReader(receiver.descriptor, VIEWER)
    calls = []
    actual_read = reader.read

    def read():
        calls.append("status")
        return actual_read()

    monkeypatch.setattr(reader, "read", read)
    with LocalCredential("dotbox-connector-memory-test-") as credential:
        resource = "http://127.0.0.1:8787/mcp"
        server = create_server(reader, token_verifier=LocalTestVerifier(
            credential, resource, expires_at=int(time.time()) + 60),
            issuer_url="http://127.0.0.1:8787/local-test-issuer", resource_url=resource)

        async def exercise():
            async with mcp.Client(server, cache=None) as client:
                result = await client.call_tool(TOOL_NAME)
                assert result.is_error and not result.structured_content

        asyncio.run(exercise())
    assert calls == []


def test_reader_does_not_claim_release_renew_or_cache_and_expiry_stays_visible(receiver):
    initial = OwnershipReader(receiver.descriptor, VIEWER).read()
    assert initial["available"] and not initial["fresh"] and initial["owner"] == "unknown"
    receiver.publish()
    lease = receiver.client.wait_for_turn("existing-controller", timeout=0)
    reader = OwnershipReader(receiver.descriptor, VIEWER)
    first = reader.read()
    assert first["fresh"] and first["owner"] == "dot"
    receiver.now[0] += 1
    second = reader.read()
    assert 0 < second["expires_in_ms"] <= 2000 < first["expires_in_ms"] <= 3000
    assert receiver.client.request("turn-check", {"lease": lease})["ok"]
    assert (second["epoch"], second["sequence"]) == (first["epoch"], first["sequence"])
    receiver.now[0] += 2
    expired = reader.read()
    assert expired["available"] and expired["owner"] == "unknown" and not expired["fresh"]
    assert expired["expires_in_ms"] == 0 and expired["epoch"] > first["epoch"]


def test_disconnection_invalidation_and_stopped_receiver_never_return_last_dot(receiver):
    reader = OwnershipReader(receiver.descriptor, VIEWER)
    receiver.publish()
    assert reader.read()["owner"] == "dot"
    receiver.publish("unknown", "unknown", "disconnected")
    disconnected = reader.read()
    assert disconnected["available"] and disconnected["owner"] == "unknown"
    receiver.publish()
    assert reader.read()["fresh"]
    assert receiver.publisher.request("bridge-invalidate", {"stream_id": receiver.stream})["ok"]
    invalidated = reader.read()
    assert invalidated["available"] and not invalidated["fresh"]
    receiver.stop()
    assert reader.read() == unavailable()


def test_reader_does_not_rebind_to_replacement_receiver_at_same_descriptor(receiver):
    reader = OwnershipReader(receiver.descriptor, VIEWER, timeout=0.1)
    receiver.publish()
    assert reader.read()["owner"] == "dot"
    old_instance = receiver.service.instance_id
    receiver.stop()
    replacement = Receiver(receiver.directory)
    try:
        replacement.publish()
        assert replacement.service.instance_id != old_instance
        assert reader.read() == unavailable()
        assert OwnershipReader(replacement.descriptor, VIEWER).read()["owner"] == "dot"
    finally:
        replacement.stop()


@pytest.mark.parametrize("kind", ["unmarked-native", "wrong-kind", "publisher"])
def test_wrong_descriptor_identity_is_rejected_before_socket_transport(receiver, tmp_path, monkeypatch, kind):
    if kind == "publisher":
        descriptor = receiver.directory / "ownership-publisher.json"
    else:
        data = dict(receiver.client.descriptor)
        if kind == "unmarked-native":
            data.pop("kind")  # The format emitted by ordinary PlayService.
        else:
            data["kind"] = "game-service"
        descriptor = tmp_path / "wrong-session.json"
        descriptor.write_text(json.dumps(data))
        descriptor.chmod(0o600)

    def must_not_connect(*args, **kwargs):
        pytest.fail("A non-coordinator descriptor reached socket transport")

    monkeypatch.setattr(socket, "create_connection", must_not_connect)
    with pytest.raises(ValueError, match="coordinator session descriptor"):
        OwnershipReader(descriptor, VIEWER)


def test_wrong_viewer_binding_fails_closed_without_exposing_identity(receiver):
    receiver.publish()
    assert OwnershipReader(receiver.descriptor, "b" * 64).read() == unavailable()


@pytest.mark.parametrize("damage", ["wrong-instance", "wrong-kind", "boolean-epoch", "contradictory-dot",
                                  "fresh-unavailable-source"])
def test_malformed_authenticated_response_is_not_reported_as_dot(receiver, monkeypatch, damage):
    receiver.publish()
    reader = OwnershipReader(receiver.descriptor, VIEWER)
    actual_request = reader._client.request

    def altered(*args, **kwargs):
        reply = deepcopy(actual_request(*args, **kwargs))
        if damage == "wrong-instance":
            reply["result"]["instance_id"] = "f" * 32
        elif damage == "wrong-kind":
            reply["result"]["kind"] = "game-service"
        elif damage == "boolean-epoch":
            reply["result"]["platform_takeover"]["epoch"] = True
        elif damage == "fresh-unavailable-source":
            reply["result"]["platform_takeover"]["source"] = "unavailable"
        else:
            reply["result"]["platform_takeover"]["viewer_mode"] = "control"
        return reply

    monkeypatch.setattr(reader._client, "request", altered)
    assert reader.read() == unavailable()


def test_full_round_trip_is_deducted_even_when_receiver_reply_says_fresh(receiver, monkeypatch):
    receiver.publish()
    reader = OwnershipReader(receiver.descriptor, VIEWER)
    # Keep real authentication/socket/state, deterministically model a delayed delivery.
    ticks = iter((10_000_000, 3_011_000_000))
    monkeypatch.setattr(connector, "time", SimpleNamespace(monotonic_ns=lambda: next(ticks)))
    result = reader.read()
    assert result["available"] and result["source"] == "codex-viewer-ui"
    assert not result["fresh"] and result["owner"] == "unknown" and result["expires_in_ms"] == 0


def test_real_http_denies_missing_bad_expired_scope_and_audience_credentials(receiver):
    httpx2 = pytest.importorskip("httpx2")
    reader = OwnershipReader(receiver.descriptor, VIEWER)
    with running_http(reader) as http:
        async def exercise():
            async with httpx2.AsyncClient(trust_env=False) as client:
                for token, expected in ((None, 401), ("invalid", 401), ("expired", 401),
                                        ("without-scope", 403), ("wrong-audience", 401)):
                    headers = {"Accept": "application/json, text/event-stream"}
                    if token is not None:
                        headers["Authorization"] = f"Bearer {token}"
                    reply = await client.post(http.url, headers=headers,
                                              json={"jsonrpc": "2.0", "id": 1,
                                                    "method": "tools/list", "params": {}})
                    assert reply.status_code == expected, (token, reply.status_code, reply.text)
                    assert receiver.client.token not in reply.text
                    assert receiver.publisher.token not in reply.text
            assert http.token not in (receiver.client.token, receiver.publisher.token)
            http.verifier._expires_at = time.time() - 1
            assert await http.verifier.verify_token(http.token) is None

        asyncio.run(exercise())


def test_real_http_rejects_untrusted_host_and_origin_before_tool_call(receiver, monkeypatch):
    httpx2 = pytest.importorskip("httpx2")
    reader = OwnershipReader(receiver.descriptor, VIEWER)
    calls = []
    actual_read = reader.read

    def read():
        calls.append("status")
        return actual_read()

    monkeypatch.setattr(reader, "read", read)
    with running_http(reader) as http:
        async def exercise():
            async with httpx2.AsyncClient(trust_env=False) as client:
                for override in ({"Host": "untrusted.invalid"}, {"Origin": "https://untrusted.invalid"}):
                    headers = {"Authorization": f"Bearer {http.token}",
                               "Accept": "application/json, text/event-stream", **override}
                    reply = await client.post(http.url, headers=headers,
                                              json={"jsonrpc": "2.0", "id": 1,
                                                    "method": "tools/call",
                                                    "params": {"name": TOOL_NAME, "arguments": {}}})
                    assert reply.status_code in (400, 403, 421), reply.text

        asyncio.run(exercise())
    assert calls == []


def test_local_launcher_serves_authenticated_status_and_cleans_generated_credential(receiver, tmp_path):
    mcp = pytest.importorskip("mcp")
    httpx2 = pytest.importorskip("httpx2")
    from mcp.client.streamable_http import streamable_http_client

    receiver.publish()
    with socket.socket() as selection:
        selection.bind(("127.0.0.1", 0))
        port = selection.getsockname()[1]
    output = tmp_path / "launcher.out"
    errors = tmp_path / "launcher.err"
    task_env = os.environ.copy()
    task_env["TMPDIR"] = str(tmp_path)
    with output.open("w") as stdout, errors.open("w") as stderr:
        process = subprocess.Popen(
            [sys.executable, "-m", "dotbox.connector", "--session", str(receiver.descriptor),
             "--viewer-id", VIEWER, "--port", str(port), "--local-test"],
            cwd=tmp_path, env=task_env, stdout=stdout, stderr=stderr)
        try:
            deadline = time.monotonic() + 5
            configuration = None
            while configuration is None:
                assert process.poll() is None, "Connector exited before its launch configuration"
                lines = output.read_text().splitlines()
                if lines:
                    configuration = json.loads(lines[0])
                else:
                    assert time.monotonic() < deadline, "Connector did not print launch configuration"
                    time.sleep(0.02)
            token_path = Path(configuration["token_file"])
            token = token_path.read_text().strip()
            assert token not in (receiver.client.token, receiver.publisher.token)
            assert token_path.stat().st_mode & 0o777 == 0o600
            assert configuration["local_test_only"] is True
            assert configuration["scope"] == READ_SCOPE
            assert 590 < configuration["expires_at"] - time.time() <= 600

            async def exercise():
                async with httpx2.AsyncClient(
                    headers={"Authorization": f"Bearer {token}"}, trust_env=False,
                    timeout=1.0,
                ) as http:
                    # Launch output is configuration, not readiness. Observe actual HTTP.
                    while True:
                        try:
                            metadata = configuration["resource"].removesuffix("/mcp")
                            reply = await http.get(metadata + "/.well-known/oauth-protected-resource/mcp")
                            if reply.status_code == 200:
                                assert reply.json()["resource"] == configuration["resource"]
                                break
                        except httpx2.TransportError:
                            pass
                        assert process.poll() is None and time.monotonic() < deadline
                        await asyncio.sleep(0.02)
                    async with mcp.Client(streamable_http_client(
                        configuration["resource"], http_client=http), cache=None) as client:
                        result = await client.call_tool(TOOL_NAME, {})
                        assert not result.is_error and result.structured_content["owner"] == "dot"
                        assert result.structured_content["fresh"]

            asyncio.run(exercise())
        finally:
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
                pytest.fail("Connector launcher did not stop on interruption")
    assert not token_path.exists() and not token_path.parent.exists()
    assert process.returncode == 130
    assert token not in output.read_text() and token not in errors.read_text()
    assert not receiver.service.stop_requested.is_set() and receiver.service.backend is None
