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
from coda_review_hub.core import Hub
import test_core


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
            test_core.seed_models(Hub(self.root / name))

    async def test_list_tools_and_read_routes(self) -> None:
        async with Client(self.params, read_timeout_seconds=15) as client:
            listed = await client.list_tools()
            tools = {tool.name: tool for tool in listed.tools}
            self.assertEqual(set(tools), {
                "routes", "observe_usage", "submit", "jobs", "result", "cancel", "handoff",
                "record_handoff_result", "attachment_files", "identity_status", "configure_identity",
                "model_status", "refresh_models", "record_models", "select_model",
                'capabilities', 'record_review', 'review', 'record_lineage', 'comparison_report',
            })
            self.assertIn("attestation", tools["observe_usage"].description)
            response = await client.call_tool("routes")
            self.assertFalse(response.is_error)
            serialized = json.dumps(response.structured_content)
            self.assertIn("claude-code", serialized)
            self.assertIn("claude-desktop", serialized)
            self.assertIn("grok", serialized)

    async def test_structured_review_and_static_report_real_mcp(self) -> None:
        hub = Hub(self.root / "state")
        source = self.project / "synthetic.py"
        source.write_bytes(b"answer = 42\n")
        job = hub.handoff(str(self.project), "chatgpt", "Synthetic only", "synthetic-mcp-conversation", [str(source)])["job"]
        aid = job["attachments"][0]
        hub.record_handoff_result(str(self.project), job["id"], "Synthetic returned advice", "Observed fixture response only.", "synthetic-mcp-conversation", observed_attachment_ids=[aid["attachment_id"]], attachment_evidence="Observed synthetic chip only.", completion_observation={"status": "completed"})
        async with Client(self.params, read_timeout_seconds=15) as client:
            capability = await client.call_tool("capabilities", {"provider": "chatgpt"})
            self.assertFalse(capability.is_error)
            self.assertIsNone(capability.structured_content["image_visual_input"])
            result = await client.call_tool("record_review", {
                "project": str(self.project), "job_id": job["id"], "evidence": "Normalized synthetic fixture.",
                "review": {"schema_version": 1, "summary": "Fixture summary", "findings": [{
                    "id": "f1", "severity": "info", "claim": "The assignment is present.",
                    "anchors": [{"attachment_id": aid["attachment_id"], "sha256": aid["sha256"], "start_line": 1, "end_line": 1, "quote": "answer = 42"}]}]}})
            self.assertFalse(result.is_error)
            self.assertEqual(result.structured_content["findings"][0]["anchors"][0]["check"]["status"], "matched")
            result = await client.call_tool("review", {"project": str(self.project), "job_id": job["id"]})
            self.assertFalse(result.is_error)
            self.assertEqual(result.structured_content["source_answer_integrity"], "matched")
            result = await client.call_tool("comparison_report", {"project": str(self.project), "job_ids": [job["id"]]})
            self.assertFalse(result.is_error)
            self.assertIn("Fixture summary", result.structured_content["content"])
            self.assertFalse(result.structured_content["published"])
            denied = await client.call_tool("record_lineage", {"project": str(self.project), "job_id": job["id"], "parent_job_id": job["id"], "kind": "native_resume", "evidence": "Not supported"})
            self.assertTrue(denied.is_error)

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
                "completion_observation": {"status": "completed"},
            })
            self.assertFalse(observed.is_error)
            self.assertEqual(observed.structured_content["job"]["submission"], "coordinator_observed_response")
            self.assertIn("did not send", observed.structured_content["delivery_basis"])

    async def test_interrupted_app_review_continues_through_real_mcp(self) -> None:
        async with Client(self.params, read_timeout_seconds=15) as client:
            prepared = await client.call_tool("handoff", {
                "project": str(self.project), "provider": "chatgpt",
                "prompt": "Synthetic continuation contract only.", "conversation_ref": "fixture-saved-turns"})
            self.assertFalse(prepared.is_error)
            job_id = prepared.structured_content["job"]["id"]
            base = {"project": str(self.project), "job_id": job_id,
                    "conversation_ref": "fixture-saved-turns",
                    "evidence": "Synthetic UI observation; no external app contacted."}
            for observation in ({"status": "invented"}, {"continue_available": "true"},
                                {"outstanding_checks": [42]}, {"verified": True}):
                rejected = await client.call_tool("record_handoff_result", dict(base,
                    response="Synthetic answer", completion_observation=observation))
                self.assertTrue(rejected.is_error)
            original = "Synthetic provisional verdict.\r\nI ran out of tool budget.\r\n"
            partial = await client.call_tool("record_handoff_result", dict(base, response=original,
                completion_observation={"status": "completed", "provider_stop_reason": "tool_use_limit",
                                        "continue_available": True, "outstanding_checks": ["check source"]}))
            self.assertFalse(partial.is_error)
            first = partial.structured_content["job"]
            self.assertEqual(first["state"], "needs_continuation")
            turn_id = first["handoff_turns"][0]["turn_id"]
            report = await client.call_tool("comparison_report", {
                "project": str(self.project), "job_ids": [job_id]})
            self.assertTrue(report.is_error)
            completed = await client.call_tool("record_handoff_result", dict(base,
                response="Synthetic source checked. Repairs still required.", previous_turn_id=turn_id,
                completion_observation={"status": "completed", "resolved_checks": ["check source"]}))
            self.assertFalse(completed.is_error)
            self.assertEqual(completed.structured_content["job"]["state"], "returned_via_handoff")
            earlier = await client.call_tool("result", {
                "project": str(self.project), "job_id": job_id, "turn_id": turn_id})
            self.assertFalse(earlier.is_error)
            self.assertEqual(earlier.structured_content["answer"], original)
            report = await client.call_tool("comparison_report", {
                "project": str(self.project), "job_ids": [job_id]})
            self.assertFalse(report.is_error)
            self.assertIn(turn_id, report.structured_content["content"])

    async def test_model_picker_requires_choice_and_changed_catalog_reconfirmation(self) -> None:
        state = self.root / "first-model-state"
        IdentityStore(state).configure(evidence="Anonymous identity for a synthetic model-picker test.")
        params = self.params.model_copy(update={"args": ["-c", GUARDED_SERVER, str(state)]})
        provider = "claude-desktop"
        async with Client(params, read_timeout_seconds=15) as client:
            initial = await client.call_tool("model_status", {"provider": provider})
            self.assertFalse(initial.is_error)
            self.assertTrue(initial.structured_content["selection_required"])
            refresh = await client.call_tool("refresh_models", {"provider": provider})
            self.assertFalse(refresh.is_error)
            self.assertFalse(refresh.structured_content["sent"])
            model = {"id": "fixture-desktop", "label": "Synthetic Desktop model", "efforts": ["default"]}
            recorded = await client.call_tool("record_models", {
                "provider": provider, "models": [model],
                "observed_at": datetime.now(timezone.utc).isoformat(),
                "evidence": "Synthetic signed-in app picker observation; no real app was inspected.",
            })
            self.assertFalse(recorded.is_error)
            status = recorded.structured_content
            self.assertEqual(status["catalog"]["source"], "observed_app")
            self.assertTrue(status["selection_required"])
            selected = await client.call_tool("select_model", {
                "provider": provider, "model": model["id"], "effort": "default",
                "catalog_fingerprint": status["catalog"]["fingerprint"],
                "evidence": "Explicit synthetic user selected this model and default effort.",
            })
            self.assertFalse(selected.is_error)
            self.assertFalse(selected.structured_content["selection_required"])
            prepared = await client.call_tool("handoff", {
                "project": str(self.project), "provider": provider, "prompt": "Synthetic handoff only.",
            })
            self.assertFalse(prepared.is_error)
            self.assertEqual(prepared.structured_content["job"]["model"], model["id"])
            changed = await client.call_tool("record_models", {
                "provider": provider, "models": [{**model, "efforts": ["default", "extended"]}],
                "observed_at": datetime.now(timezone.utc).isoformat(),
                "evidence": "Synthetic app picker now exposes another thinking choice.",
            })
            self.assertFalse(changed.is_error)
            self.assertEqual(changed.structured_content["reason"], "catalog_changed")
            self.assertTrue(changed.structured_content["selection_required"])
            blocked = await client.call_tool("handoff", {
                "project": str(self.project), "provider": provider, "prompt": "Must wait for a new choice.",
            })
            self.assertTrue(blocked.is_error)

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
        for name in ("__init__.py", "attachments.py", "completion.py", "identity.py", "models.py", "core.py", "worker.py", "mcp_server.py", 'reviews.py', 'capabilities.py', 'reporting.py'):
            shutil.copy2(PACKAGE_ROOT / "src" / "coda_review_hub" / name, source / name)
        helper = package / "offline_helper.py"
        shutil.copy2(Path(__file__).with_name("mcp_disconnect_helper.py"), helper)
        with helper.open("a", encoding="utf-8") as fixture:
            fixture.write('''

def discover_models():
    return {"source": "official_cli", "runtime_version": "offline-fixture",
            "evidence": "Synthetic offline metadata only; no provider is contacted.", "models": [
                {"id": "fixture-opus", "efforts": ["max", "low"]},
                {"id": "fixture-grok", "efforts": ["xhigh"]},
                {"id": "fixture-antigravity", "efforts": ["xhigh", "fixture-high"]}]}
''')
        sha = hashlib.sha256(helper.read_bytes()).hexdigest()
        pins = {
            provider: {"path": str(helper), "sha256": sha, "model": "offline-fixture", "effort": "max"}
            for provider in ("claude-code", "grok")
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
