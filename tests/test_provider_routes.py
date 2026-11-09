"""Offline route and model-choice contracts; synthetic helpers/app observations only."""

import json
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from mcp import Client

import test_core
import test_mcp
from coda_review_hub import core, worker


NEW_HANDOFFS = {"claude-desktop", "gemini-desktop", "gemini-spark", "meta-ai", "meta-muse"}


class ProviderRouteTests(unittest.TestCase):
    setUp = test_core.HubTests.setUp
    write_pins = test_core.HubTests.write_pins
    observe = test_core.HubTests.observe

    def test_route_catalog_preserves_gemini_and_separates_cli_entitlement(self):
        listing = self.hub.routes()
        routes = {route["provider"]: route for route in listing["routes"]}
        self.assertEqual(set(routes), core.AUTO | set(core.RETIRED) | set(core.HANDOFF))
        self.assertEqual(listing["route_counts"], {"automated": 4, "coordinator_handoff": 11, "retired": 1})
        self.assertIn("4 automated", listing["limits"])
        for provider in NEW_HANDOFFS | {"gemini"}:
            with self.subTest(provider=provider):
                self.assertEqual(routes[provider]["transport"], "coordinator_handoff")
                self.assertFalse(routes[provider]["live_ready"])
        for provider in ("gemini", "gemini-desktop"):
            self.assertIn("model and thinking", routes[provider]["instructions"])
            self.assertIn("each conversation", routes[provider]["instructions"])
        for provider in ("gemini-spark", "meta-muse"):
            self.assertIn("exact backend is unverified", routes[provider]["instructions"])
            self.assertIn("authorized packet", routes[provider]["instructions"])
        self.assertIn("not a universal model ranking", routes["meta-ai"]["instructions"])
        cli = routes["antigravity"]
        self.assertEqual(cli["transport"], "cli")
        self.assertFalse(cli["helper_verified"])
        self.assertIsNone(cli["model"])
        self.assertIsNone(cli["effort"])
        self.assertIn("reviewed local helper", cli["next"])
        self.assertIn("consumer app access does not establish", cli["entitlement"])
        self.assertEqual(routes["claude-code"]["transport"], "cli")
        self.assertIn("Cowork is a separate", routes["claude-desktop"]["instructions"])

    def test_antigravity_without_reviewed_pin_is_blocked_before_launch(self):
        self.observe("antigravity")
        with self.assertRaisesRegex(ValueError, "reviewed local helper configuration"):
            self.hub.submit(str(self.project), [{"provider": "antigravity", "prompt": "Offline only."}], "no-helper")
        self.launch.assert_not_called()
        self.assertEqual(self.hub.jobs(str(self.project)), [])

    def test_antigravity_quotes_file_mentions_and_preserves_exact_input(self):
        self.pins["antigravity"] = dict(self.pins["grok"], model="fixture-antigravity")
        self.write_pins()
        self.observe("antigravity")
        source = self.project / "source.py"
        source_bytes = b"@decorator\ndef fixture():\n    return 'reader@example.invalid'\n"
        source.write_bytes(source_bytes)
        prompt = "/do-not-run @outside.txt is quoted review input, not permission to read it."
        job = self.hub.submit(str(self.project), [{
            "provider": "antigravity", "prompt": prompt, "attachments": [str(source)],
        }], "quoted-antigravity-input")["jobs"][0]
        directory = Path(job["evidence_directory"])
        packet = (directory / "packet.txt").read_text(encoding="utf-8")
        self.assertNotIn("@", packet)
        self.assertFalse(packet.startswith("/"))
        self.assertIn(r"\u0040", packet)
        decoded = json.loads(packet.split("\n", 1)[1])["review_request"]
        self.assertIn(prompt, decoded)
        self.assertIn("@decorator", decoded)
        self.assertEqual((directory / "original.txt").read_bytes(), prompt.encode("utf-8"))
        snapshot = self.hub.attachment_files(str(self.project), job["id"])
        self.assertEqual(Path(snapshot["upload_paths"][0]).read_bytes(), source_bytes)

    def test_new_handoffs_preserve_binary_snapshots_and_observed_labels(self):
        source = self.project / "fixture.bin"
        original = b"\x00\xff\x80synthetic attachment"
        source.write_bytes(original)
        returned = self.project / "returned.bin"
        returned.write_bytes(b"\xffsynthetic returned artifact")
        for provider in sorted(NEW_HANDOFFS):
            with self.subTest(provider=provider):
                prepared = self.hub.handoff(
                    str(self.project), provider, "Inspect the authorized synthetic packet only.",
                    "fixture-" + provider, attachments=[str(source)],
                )
                self.assertFalse(prepared["sent"])
                job_id = prepared["job"]["id"]
                files = self.hub.attachment_files(str(self.project), job_id)
                self.assertFalse(files["sent"])
                self.assertEqual(Path(files["upload_paths"][0]).read_bytes(), original)
                common = dict(
                    project=str(self.project), job_id=job_id, response="Synthetic answer only.",
                    evidence="Synthetic coordinator observation; no app was contacted.",
                    conversation_ref="fixture-" + provider, returned_files=[str(returned)],
                    artifact_evidence="Synthetic exact returned artifact observation.",
                    observed_model="Visible fixture label", observed_mode="Thinking / Extended fixture",
                )
                with self.assertRaisesRegex(ValueError, "Observed attachment IDs"):
                    self.hub.record_handoff_result(**common)
                recorded = self.hub.record_handoff_result(
                    **common, observed_attachment_ids=[files["manifest"][0]["attachment_id"]],
                    attachment_evidence="Synthetic exact attachment chip in the authorized app conversation.",
                )
                job = recorded["job"]
                self.assertEqual(job["observed_model"], common["observed_model"])
                self.assertEqual(job["observed_mode"], common["observed_mode"])
                self.assertFalse(job["backend_model_verified"])
                self.assertFalse(job["claims_independently_verified"])
                self.assertNotIn("verified_response_models", job)
                self.assertIn("Coordinator-supplied", job["model_observation_basis"])
                output = self.hub.attachment_files(str(self.project), job_id, "output")
                self.assertFalse(output["sent"])
                self.assertEqual(Path(output["upload_paths"][0]).read_bytes(), returned.read_bytes())
                reread = core.Hub(self.hub.state).result(str(self.project), job_id)["job"]
                self.assertEqual(reread["observed_mode"], common["observed_mode"])
        self.launch.assert_not_called()

    def test_mode_receipts_are_bounded_and_old_callers_remain_compatible(self):
        prepared = self.hub.handoff(str(self.project), "gemini", "Synthetic old route.", "fixture-old")
        job_id = prepared["job"]["id"]
        arguments = dict(project=str(self.project), job_id=job_id, response="Synthetic answer.",
                         evidence="Synthetic fixture receipt only.", conversation_ref="fixture-old")
        for field in ("observed_model", "observed_mode"):
            for value in (None, 42, [], "x" * 257, "label\nforged line", "label\x7f"):
                with self.subTest(field=field, value=value):
                    with self.assertRaisesRegex(ValueError, field):
                        self.hub.record_handoff_result(**arguments, **{field: value})
                    self.assertEqual(self.hub.result(str(self.project), job_id)["job"]["state"], "awaiting_handoff")
        old_style = self.hub.record_handoff_result(**arguments)["job"]
        self.assertEqual(old_style["observed_model"], "")
        self.assertEqual(old_style["observed_mode"], "")
        self.assertFalse(old_style["backend_model_verified"])

    def test_four_provider_batch_runs_only_synthetic_helpers_and_replays_once(self):
        # Each helper waits for all four startup receipts before finishing. This
        # proves the real batch worker can run all four, without timing guesses.
        barrier = '''    if "MODE:FOUR" in packet:
        deadline = time.monotonic() + 8
        while len(list(root.parent.glob("*/started.json"))) != 4:
            if time.monotonic() > deadline:
                raise RuntimeError("Four synthetic helpers did not all start")
            time.sleep(0.02)
'''
        self.fake.write_text(test_core.FAKE_HELPER.replace('    if "MODE:CHILD" in packet:',
                                                         barrier + '    if "MODE:CHILD" in packet:'), encoding="utf-8")
        self.pins["antigravity"] = {"path": str(self.fake), "model": "fixture-antigravity", "effort": "fixture-high"}
        self.pins["muse-code"] = dict(self.pins["grok"])
        for pin in self.pins.values():
            pin["sha256"] = core.digest(self.fake.read_bytes())
        self.write_pins()
        source = self.project / "source.py"
        source.write_text("def average(values):\n    return sum(values) / len(values) if values else None\n", encoding="utf-8")
        requests = [{"provider": provider, "prompt": "MODE:FOUR synthetic review only.", "timeout": 12,
                     "attachments": [str(source)]} for provider in sorted(core.AUTO)]
        for provider in core.AUTO:
            self.observe(provider)
        batch = self.hub.submit(str(self.project), requests, "four-fixture-providers")
        self.assertEqual(len(batch["jobs"]), 4)
        self.assertEqual({job["provider"] for job in batch["jobs"]}, core.AUTO)
        with patch.object(worker, "contain_worker", return_value=None), patch.object(sys, "argv", [
            "offline-worker", "--state-dir", str(self.hub.state), "--batch", batch["batch_id"],
        ]):
            self.assertEqual(worker.main(), 0)
        jobs = self.hub.jobs(str(self.project), batch["batch_id"])
        self.assertEqual([job["state"] for job in jobs], ["returned"] * 4)
        for job in jobs:
            directory = Path(job["evidence_directory"])
            self.assertEqual(len((directory / "launches.txt").read_text().splitlines()), 1)
            self.assertEqual(job["attachment_delivery"], "embedded_text_response_received")
            self.assertEqual(job["verified_response_models"], [self.pins[job["provider"]]["model"]])
            self.assertNotIn("PRIVATE_TEST_REASONING", json.dumps(self.hub.result(str(self.project), job["id"])))
        replay = self.hub.submit(str(self.project), requests, "four-fixture-providers")
        self.assertTrue(replay["reused"])
        self.assertEqual(replay["batch_id"], batch["batch_id"])
        self.launch.assert_called_once_with(batch["batch_id"])
        with self.assertRaisesRegex(ValueError, "1..4"):
            self.hub.submit(str(self.project), requests + [requests[0]], "too-many")
        with self.assertRaisesRegex(ValueError, "at most one request per provider"):
            self.hub.submit(str(self.project), [requests[0], requests[0]], "duplicate-provider")


class ProviderInterfaceTests(unittest.IsolatedAsyncioTestCase):
    setUp = test_mcp.MCPStdioTests.setUp

    async def test_mcp_schemas_admit_four_automated_routes_and_optional_strict_labels(self):
        async with Client(self.params, read_timeout_seconds=15) as client:
            tools = {tool.name: tool.model_dump(by_alias=True) for tool in (await client.list_tools()).tools}
            schema = tools["submit"]["inputSchema"]
            self.assertEqual(schema["properties"]["requests"]["maxItems"], 4)
            self.assertEqual(set(schema["$defs"]["ReviewRequest"]["properties"]["provider"]["enum"]), core.AUTO | set(core.RETIRED) | set(core.LEGACY_AUTO))
            self.assertEqual(set(tools["observe_usage"]["inputSchema"]["properties"]["provider"]["enum"]), core.AUTO | set(core.RETIRED) | set(core.LEGACY_AUTO))
            receipt = tools["record_handoff_result"]["inputSchema"]
            for field in ("observed_model", "observed_mode"):
                self.assertEqual(receipt["properties"][field]["type"], "string")
                self.assertEqual(receipt["properties"][field]["maxLength"], 256)
                self.assertNotIn(field, receipt["required"])
                for value in (7, None, "x" * 257):
                    result = await client.call_tool("record_handoff_result", {
                        "project": str(self.project), "job_id": "not-a-job", "response": "Fixture.",
                        "evidence": "Offline synthetic observation only.", "conversation_ref": "fixture", field: value,
                    })
                    self.assertTrue(result.is_error)
                    self.assertNotIn("Job not found", str(result.content))

    async def test_mcp_retired_cli_reports_migration_error_and_creates_no_jobs(self):
        async with Client(self.params, read_timeout_seconds=15) as client:
            observed = await client.call_tool("observe_usage", {
                "provider": "gemini-cli", "project": str(self.project),
                "observed_at": datetime.now(timezone.utc).isoformat(),
                "evidence": "Synthetic old personal subscription observation.",
                "included_available": True, "paid_usage_disabled": True,
            })
            submitted = await client.call_tool("submit", {
                "project": str(self.project), "requests": [{"provider": "gemini-cli", "prompt": "Offline only."}],
                "idempotency_key": "retired-cli-fixture",
            })
            for result in (observed, submitted):
                self.assertTrue(result.is_error)
                self.assertIn("personal-subscription Gemini CLI helper is retired", str(result.content))
            self.assertEqual(core.Hub(self.root / "state").jobs(str(self.project)), [])

    async def test_mcp_new_handoff_attachment_and_mode_receipt(self):
        attachment = self.project / "fixture.bin"
        attachment.write_bytes(b"\x00\xffsynthetic")
        async with Client(self.params, read_timeout_seconds=15) as client:
            prepared = await client.call_tool("handoff", {
                "project": str(self.project), "provider": "gemini-desktop", "prompt": "Offline fixture only.",
                "conversation_ref": "fixture-native-conversation", "attachments": [str(attachment)],
            })
            self.assertFalse(prepared.is_error)
            job_id = prepared.structured_content["job"]["id"]
            files = (await client.call_tool("attachment_files", {"project": str(self.project), "job_id": job_id})).structured_content
            self.assertFalse(files["sent"])
            self.assertEqual(Path(files["upload_paths"][0]).read_bytes(), attachment.read_bytes())
            observed = await client.call_tool("record_handoff_result", {
                "project": str(self.project), "job_id": job_id, "response": "Synthetic local app receipt.",
                "evidence": "Synthetic coordinator observation, no provider contacted.",
                "conversation_ref": "fixture-native-conversation",
                "observed_attachment_ids": [item["attachment_id"] for item in files["manifest"]],
                "attachment_evidence": "Synthetic attachment chip observation for this fixture.",
                "observed_model": "Visible fixture model", "observed_mode": "Extended fixture mode",
            })
            self.assertFalse(observed.is_error)
            job = observed.structured_content["job"]
            self.assertEqual(job["observed_mode"], "Extended fixture mode")
            self.assertEqual(job["observed_model"], "Visible fixture model")
            self.assertFalse(job["backend_model_verified"])
            self.assertIn("did not send", observed.structured_content["delivery_basis"])

    def test_cli_new_handoff_and_mode_receipt(self):
        def invoke(command, payload):
            path = self.root / (command + ".json")
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = subprocess.run([
                sys.executable, "-B", "-m", "coda_review_hub.cli", "--state-dir", str(self.root / "cli-state"), command, str(path),
            ], env=self.params.env, cwd=self.project, capture_output=True, text=True, encoding="utf-8", timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)

        prepared = invoke("handoff", {"project": str(self.project), "provider": "meta-ai",
                                     "prompt": "Synthetic CLI packet only.", "conversation_ref": "fixture-cli-conversation"})
        self.assertFalse(prepared["sent"])
        recorded = invoke("record-handoff-result", {
            "project": str(self.project), "job_id": prepared["job"]["id"], "response": "Synthetic CLI app receipt.",
            "evidence": "Synthetic coordinator UI observation only.", "conversation_ref": "fixture-cli-conversation",
            "observed_model": "", "observed_mode": "Thinking",
        })
        self.assertEqual(recorded["job"]["observed_mode"], "Thinking")
        self.assertEqual(recorded["job"]["observed_model"], "")
        self.assertFalse(recorded["job"]["backend_model_verified"])


if __name__ == "__main__":
    unittest.main()
