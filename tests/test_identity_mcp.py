"""Identity choice across real stdio/CLI with process and network execution blocked."""

import json
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

from mcp import Client
from coda_review_hub.core import Hub

import test_core
import test_mcp


class MCPIdentityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        test_mcp.MCPStdioTests.setUp(self)
        self.identity_state = self.root / "unconfigured-state"
        # Model the public distribution with no personal seed or helper pins.
        source = self.root / "public-package" / "src" / "coda_review_hub"
        source.mkdir(parents=True)
        for name in ("__init__.py", "attachments.py", "completion.py", "identity.py", "models.py", "core.py", "worker.py", "mcp_server.py", "cli.py", "reviews.py", "capabilities.py", "reporting.py"):
            shutil.copy2(test_mcp.PACKAGE_ROOT / "src" / "coda_review_hub" / name, source / name)
        # Synthetic catalog choices must not load the private identity seed.
        with patch.object(test_core.core, "BASE", source.parents[1]):
            test_core.seed_models(Hub(self.identity_state))
        self.params = self.params.model_copy(update={
            "args": ["-c", test_mcp.GUARDED_SERVER, str(self.identity_state)],
            "env": dict(self.params.env, PYTHONPATH=str(source.parent)),
        })

    async def test_unconfigured_outbound_is_blocked_then_anonymous_handoff_is_allowed(self):
        async with Client(self.params, read_timeout_seconds=15) as client:
            status = await client.call_tool("identity_status")
            self.assertFalse(status.is_error)
            self.assertFalse(status.structured_content["configured"])
            for tool, payload in (
                ("submit", {"project": str(self.project), "idempotency_key": "blocked-identity",
                            "requests": [{"provider": "grok", "prompt": "Offline fixture."}]}),
                ("handoff", {"project": str(self.project), "provider": "gemini", "prompt": "Offline fixture."}),
            ):
                blocked = await client.call_tool(tool, payload)
                self.assertTrue(blocked.is_error)
                self.assertIn("Ask/check the user", " ".join(getattr(item, "text", "") for item in blocked.content))
            jobs = await client.call_tool("jobs", {"project": str(self.project)})
            self.assertEqual(jobs.structured_content, {"result": []})
            configured = await client.call_tool("configure_identity", {
                "evidence": "The offline fixture user explicitly chose anonymous names.",
            })
            self.assertFalse(configured.is_error)
            self.assertTrue(configured.structured_content["configured"])
            self.assertEqual(configured.structured_content["agent_name"], "")
            handoff = await client.call_tool("handoff", {
                "project": str(self.project), "provider": "gemini", "prompt": "Offline fixture; no send.",
            })
            self.assertFalse(handoff.is_error)
            self.assertFalse(handoff.structured_content["sent"])
        async with Client(self.params, read_timeout_seconds=15) as client:
            persisted = await client.call_tool("identity_status")
            self.assertTrue(persisted.structured_content["configured"])

    async def test_identity_schema_is_strict_and_alias_resolves_for_handoff(self):
        async with Client(self.params, read_timeout_seconds=15) as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
            self.assertTrue(tools["identity_status"].model_dump(by_alias=True)["annotations"]["readOnlyHint"])
            for fields in ({"agent_name": 42}, {"aliases": {"editor": 1}}, {"collaborators": []},
                           {"context_notes": {str(i): "note" for i in range(17)}}, {"aliases": {"editor": "arbitrary"}}):
                rejected = await client.call_tool("configure_identity", dict(
                    {"evidence": "Synthetic fixture user naming preference."}, **fields,
                ))
                self.assertTrue(rejected.is_error)
            configured = await client.call_tool("configure_identity", {
                "evidence": "The fixture user explicitly chose these synthetic identities.",
                "agent_name": "Guide", "user_name": "Researcher", "collaborators": {"chatgpt": "Editor"},
                "aliases": {"editor": "chatgpt"}, "context_notes": {"chatgpt": "Use the fixture project conversation."},
            })
            self.assertFalse(configured.is_error)
            handoff = await client.call_tool("handoff", {
                "project": str(self.project), "provider": "editor", "prompt": "Offline fixture; no send.",
            })
            self.assertFalse(handoff.is_error)
            self.assertEqual(handoff.structured_content["job"]["provider"], "chatgpt")
            self.assertFalse(handoff.structured_content["sent"])

    def test_cli_configuration_persists_and_unknown_fields_are_refused(self):
        def invoke(*args):
            return subprocess.run(
                [sys.executable, "-B", "-m", "coda_review_hub.cli", "--state-dir", str(self.identity_state), *args],
                env=self.params.env, cwd=self.project, capture_output=True, text=True, encoding="utf-8", timeout=15,
            )
        initial = invoke("identity-status")
        self.assertEqual(initial.returncode, 0, initial.stderr)
        self.assertFalse(json.loads(initial.stdout)["configured"])
        payload = self.root / "identity-payload.json"
        payload.write_text(json.dumps({"agent_name": "Guide", "evidence": "The synthetic user chose this name."}), encoding="utf-8")
        saved = invoke("configure-identity", str(payload))
        self.assertEqual(saved.returncode, 0, saved.stderr)
        self.assertEqual(json.loads(invoke("identity-status").stdout)["agent_name"], "Guide")
        payload.write_text(json.dumps({"evidence": "The synthetic user chose this name.", "command": "not-permitted"}), encoding="utf-8")
        invalid = invoke("configure-identity", str(payload))
        self.assertEqual(invalid.returncode, 2)
        self.assertIn("Unknown payload fields", json.loads(invalid.stderr)["error"])
        self.assertEqual(json.loads(invoke("identity-status").stdout)["agent_name"], "Guide")


if __name__ == "__main__":
    unittest.main()
