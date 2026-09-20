"""Real stdio protocol checks against isolated state; no credentials or model calls."""

from __future__ import annotations

import json
import os
import asyncio
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from pathlib import Path

from mcp import Client
from mcp.client.stdio import StdioServerParameters
from coda_review_hub.identity import IdentityStore


PACKAGE_ROOT = Path(__file__).resolve().parents[1]

# The real server runs in a child interpreter. Its audit hook forbids process
# execution and network connections, so a failed preflight cannot launch a model.
GUARDED_SERVER = """
import sys, anyio
from coda_review_hub.mcp_server import create_server
def deny_external(event, args):
    if event in {'subprocess.Popen', 'os.system', 'os.posix_spawn', 'socket.connect'}:
        raise RuntimeError('The MCP smoke test forbids external execution and network access')
server = create_server(sys.argv[1])
async def serve():
    # Windows creates an internal socketpair when constructing its event loop.
    # Install the guard after that setup, before accepting any MCP request.
    sys.addaudithook(deny_external)
    await server.run_stdio_async()
anyio.run(serve)
"""


def windows_process_alive(pid: int) -> bool:
    import win32api
    import win32con
    import win32process
    import pywintypes

    try:
        handle = win32api.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    except pywintypes.error:
        return False
    try:
        return win32process.GetExitCodeProcess(handle) == 259
    finally:
        win32api.CloseHandle(handle)


class MCPStdioTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory(prefix="coda-mcp-test-")
        self.addCleanup(directory.cleanup)
        temporary = directory.name
        self.root = Path(temporary)
        self.project = self.root / "project"
        self.project.mkdir()
        home = self.root / "home"
        home.mkdir()
        env = {
            name: value for name, value in os.environ.items()
            if name.upper() in {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP"}
        }
        env.update({
            "PYTHONPATH": str(PACKAGE_ROOT / "src"),
            "PYTHONUTF8": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "HOME": str(home),
            "USERPROFILE": str(home),
            "APPDATA": str(home / "AppData" / "Roaming"),
            "LOCALAPPDATA": str(home / "AppData" / "Local"),
            "PATH": str(Path(sys.executable).parent),
        })
        self.params = StdioServerParameters(
            command=sys.executable,
            args=["-c", GUARDED_SERVER, str(self.root / "state")],
            env=env,
            cwd=self.project,
        )
        # Existing fixture tests exercise later policy gates using an explicitly
        # anonymous synthetic choice. Identity-specific tests use another state.
        for name in ("state", "cli-state", "disconnect-state"):
            IdentityStore(self.root / name).configure(evidence="Anonymous identity chosen for this offline test fixture.")

    async def test_list_tools_and_read_routes(self) -> None:
        async with Client(self.params, read_timeout_seconds=15) as client:
            listed = await client.list_tools()
            tools = {tool.name: tool for tool in listed.tools}
            self.assertEqual(set(tools), {
                "routes", "observe_usage", "submit", "jobs", "result", "cancel", "handoff",
                "record_handoff_result", "attachment_files", "identity_status", "configure_identity",
            })
            self.assertIn("attestation", tools["observe_usage"].description)
            response = await client.call_tool("routes")
            self.assertFalse(response.is_error)
            serialized = json.dumps(response.structured_content)
            self.assertIn("claude", serialized)
            self.assertIn("grok", serialized)

    async def test_missing_usage_blocks_dispatch_without_creating_jobs(self) -> None:
        # Reach the quota gate using only a local inert helper fixture. A public
        # checkout intentionally contains no configured provider helper.
        fixture = self.root / "quota-fixture"
        fixture.mkdir()
        helper = fixture / "inert_helper.py"
        helper.write_text("raise RuntimeError('Offline quota fixture must never execute')\n", encoding="utf-8")
        (fixture / "helpers.json").write_text(json.dumps({
            "claude": {"path": str(helper), "sha256": hashlib.sha256(helper.read_bytes()).hexdigest(),
                       "model": "offline-fixture", "effort": "max"},
        }), encoding="utf-8")
        guarded = GUARDED_SERVER.replace("server = create_server(sys.argv[1])", (
            "from pathlib import Path\nimport coda_review_hub.core as core\n"
            "core.BASE = Path(sys.argv[2])\nserver = create_server(sys.argv[1])"
        ))
        params = self.params.model_copy(update={
            "args": ["-c", guarded, str(self.root / "state"), str(fixture)],
        })
        async with Client(params, read_timeout_seconds=15) as client:
            project = str(self.project)
            response = await client.call_tool("submit", {
                "project": project,
                "requests": [{"provider": "claude", "prompt": "FixtureAgent: Synthetic test; do not dispatch."}],
                "idempotency_key": "smoke-no-observation",
            })
            self.assertTrue(response.is_error)
            error = " ".join(getattr(item, "text", "") for item in response.content)
            self.assertIn("observation", error)
            self.assertNotIn("smoke test forbids", error)
            jobs = await client.call_tool("jobs", {"project": project})
            self.assertFalse(jobs.is_error)
            self.assertIn(jobs.structured_content, ({"result": []}, []))

    async def test_arbitrary_provider_and_options_rejected(self) -> None:
        async with Client(self.params, read_timeout_seconds=15) as client:
            for request in (
                {"provider": "arbitrary", "prompt": "Synthetic test"},
                {"provider": "grok", "prompt": "Synthetic test", "command": "not-permitted"},
                {"provider": "grok", "prompt": "Synthetic test", "timeout": 3601},
            ):
                with self.subTest(request=request):
                    result = await client.call_tool("submit", {
                        "project": str(self.project), "requests": [request], "idempotency_key": "invalid",
                    })
                    self.assertTrue(result.is_error)

    async def test_handoff_records_coordinator_observation_only(self) -> None:
        async with Client(self.params, read_timeout_seconds=15) as client:
            routes = (await client.call_tool("routes")).structured_content["routes"]
            provider = next(route["provider"] for route in routes if route["transport"] == "coordinator_handoff")
            prepared = await client.call_tool("handoff", {
                "project": str(self.project), "provider": provider,
                "prompt": "FixtureAgent: Synthetic local test, no provider dispatch.",
                "conversation_ref": "synthetic-test-conversation",
            })
            self.assertFalse(prepared.is_error)
            record = prepared.structured_content
            self.assertFalse(record["sent"])
            observed = await client.call_tool("record_handoff_result", {
                "project": str(self.project), "job_id": record["job"]["id"],
                "response": "Synthetic fixture response; no provider was contacted.",
                "evidence": "Local test fixture only, not a real provider observation.",
                "conversation_ref": "synthetic-test-conversation", "acknowledgment": "not_possible",
            })
            self.assertFalse(observed.is_error)
            self.assertEqual(observed.structured_content["job"]["submission"], "coordinator_observed_response")
            self.assertIn("did not send", observed.structured_content["delivery_basis"])

    def test_cli_routes_and_invalid_payload(self) -> None:
        def invoke(*args):
            return subprocess.run(
                [sys.executable, "-B", "-m", "coda_review_hub.cli", "--state-dir", str(self.root / "cli-state"), *args],
                env=self.params.env, cwd=self.project, capture_output=True, text=True, encoding="utf-8", timeout=15,
            )

        routes = invoke("routes")
        self.assertEqual(routes.returncode, 0, routes.stderr)
        self.assertIn("routes", json.loads(routes.stdout))
        payload = self.root / "invalid.json"
        payload.write_text(json.dumps({
            "project": str(self.project), "requests": [], "idempotency_key": "test", "command": "not-permitted",
        }), encoding="utf-8")
        rejected = invoke("submit", str(payload))
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("Unknown payload fields", json.loads(rejected.stderr)["error"])

    @unittest.skipUnless(os.name == "nt", "Windows SDK kills descendants at disconnect")
    async def test_disconnect_interrupts_worker_without_retry(self) -> None:
        # Deterministically model the SDK's documented startup assignment race:
        # no client-owned job catches this server. The production server must
        # establish its own containment before accepting the submit request.
        client_job = patch("mcp.os.win32.utilities._create_job_object", return_value=None)
        client_job.start()
        self.addCleanup(client_job.stop)
        # Copy only this package's source into an isolated temporary package.
        # The production helper pins are never copied or modified.
        package = self.root / "fixture-package"
        source = package / "src" / "coda_review_hub"
        source.mkdir(parents=True)
        for name in ("__init__.py", "attachments.py", "identity.py", "core.py", "worker.py", "mcp_server.py"):
            shutil.copy2(PACKAGE_ROOT / "src" / "coda_review_hub" / name, source / name)
        helper = package / "offline_helper.py"
        shutil.copy2(Path(__file__).with_name("mcp_disconnect_helper.py"), helper)
        sha = hashlib.sha256(helper.read_bytes()).hexdigest()
        pins = {
            provider: {"path": str(helper), "sha256": sha, "model": "offline-fixture", "effort": "max"}
            for provider in ("claude", "grok")
        }
        (package / "helpers.json").write_text(json.dumps(pins), encoding="utf-8")
        state = self.root / "disconnect-state"
        env = dict(self.params.env, PYTHONPATH=str(package / "src"))
        params = self.params.model_copy(update={
            "args": ["-B", "-m", "coda_review_hub.mcp_server", "--state-dir", str(state)],
            "env": env,
        })
        request = {
            "project": str(self.project),
            "requests": [{"provider": "claude", "prompt": "FixtureAgent: Offline disconnect fixture.", "timeout": 20}],
            "idempotency_key": "one-disconnect-attempt",
        }
        async with Client(params, read_timeout_seconds=15) as client:
            observation = await client.call_tool("observe_usage", {
                "project": str(self.project), "provider": "claude",
                "observed_at": datetime.now(timezone.utc).isoformat(),
                "evidence": "Synthetic offline capacity fixture; no actual account observation.",
                "included_available": True, "paid_usage_disabled": True,
            })
            self.assertFalse(observation.is_error)
            submitted = await client.call_tool("submit", request)
            self.assertFalse(submitted.is_error)
            batch = submitted.structured_content
            job = batch["jobs"][0]
            directory = Path(job["evidence_directory"])
            marker = directory / "fixture-started.json"
            deadline = time.monotonic() + 8
            while not marker.exists() and time.monotonic() < deadline:
                await asyncio.sleep(0.05)
            self.assertTrue(marker.exists(), "The offline helper did not start while the Client was open")
            helper_pid = json.loads(marker.read_text(encoding="utf-8"))["pid"]
            current = await client.call_tool("jobs", {"project": str(self.project)})
            worker_pid = current.structured_content["result"][0]["worker_pid"]
            self.assertTrue(windows_process_alive(helper_pid))
            self.assertTrue(windows_process_alive(worker_pid))
        # Closing stdin ends the server and transport cleanup; its retained job
        # reaps descendants on process exit despite having no client-owned job.
        deadline = time.monotonic() + 5
        while any(windows_process_alive(pid) for pid in (worker_pid, helper_pid)) and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        self.assertFalse(windows_process_alive(worker_pid))
        self.assertFalse(windows_process_alive(helper_pid))
        self.assertFalse((directory / "provider" / "metadata.json").exists())
        self.assertEqual(len((directory / "launches.txt").read_text().splitlines()), 1)
        # Advance only this synthetic job's heartbeat to test reconciliation
        # without sleeping through the production 90-second loss threshold.
        with closing(sqlite3.connect(state / "jobs.sqlite3")) as connection:
            connection.execute("UPDATE jobs SET heartbeat=? WHERE id=?", (time.time() - 120, job["id"]))
            connection.commit()
        async with Client(params, read_timeout_seconds=15) as client:
            reconciled = await client.call_tool("jobs", {"project": str(self.project)})
            record = reconciled.structured_content["result"][0]
            self.assertEqual(record["state"], "delivery_unknown")
            replayed = await client.call_tool("submit", request)
            self.assertFalse(replayed.is_error)
            self.assertTrue(replayed.structured_content["reused"])
            self.assertEqual(replayed.structured_content["batch_id"], batch["batch_id"])
            self.assertEqual(replayed.structured_content["jobs"][0]["id"], job["id"])
        self.assertEqual(len((directory / "launches.txt").read_text().splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
