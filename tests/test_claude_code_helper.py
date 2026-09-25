"""Offline Claude Code discovery/isolation tests; no provider is contacted."""
from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "claude_code_helper_under_test", Path(__file__).resolve().parents[1] / "scripts/claude_code_check.py")
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)


class ClaudeCodeHelperTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="claude-code-offline-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.exe = self.root / "fixture.exe"
        self.exe.write_bytes(b"MZoffline-only-not-executable")
        self.config_file = self.root / "config.json"
        self.config_file.write_text(json.dumps({"exe": str(self.exe)}), encoding="utf-8")
        self.mcp = self.root / "empty-mcp.json"
        self.mcp.write_text('{"mcpServers":{}}', encoding="utf-8")

    def payload(self):
        return {"fast_mode_state": "off", "models": [
            {"value": "opus", "resolvedModel": "claude-opus-future", "displayName": "Opus future",
             "description": "Fixture", "supportsEffort": True,
             "supportedEffortLevels": ["medium", "high", "max"]},
            {"value": "simple", "displayName": "Simple", "supportsEffort": False},
        ]}

    def catalog(self):
        return {"provider": "claude-code", "source": "official_cli", "runtime_version": "future-version",
                "models": helper.normalize_catalog(self.payload()),
                "evidence": "Synthetic offline initialization fixture, no provider contacted.",
                "discovery_details": {"user_prompt_sent": False,
                             "runtime_provenance": {"sha256": helper.sha256(self.exe.read_bytes())}}}

    def test_catalog_accepts_additive_fields_and_future_models(self):
        payload = self.payload()
        payload["future_metadata"] = {"version": 99}
        payload["models"][0]["new_property"] = True
        models = helper.normalize_catalog(payload)
        self.assertEqual(models[0]["resolved_id"], "claude-opus-future")
        self.assertEqual(models[0]["efforts"], ["high", "max", "medium"])
        self.assertEqual(models[1]["efforts"], ["default"])

    def test_catalog_does_not_invent_effort_when_absent(self):
        models = helper.normalize_catalog({"models": [{"value": "new", "displayName": "New"}]})
        self.assertEqual(models[0]["efforts"], ["default"])

    def test_catalog_rejects_duplicate_selection(self):
        payload = self.payload()
        payload["models"].append(payload["models"][0].copy())
        with self.assertRaises(ValueError):
            helper.normalize_catalog(payload)

    def test_catalog_rejects_malformed_efforts(self):
        payload = self.payload()
        payload["models"][0]["supportedEffortLevels"] = "high"
        with self.assertRaises(ValueError):
            helper.normalize_catalog(payload)

    def test_fast_mode_is_not_silently_accepted(self):
        payload = self.payload()
        payload["fast_mode_state"] = "on"
        with self.assertRaises(ValueError):
            helper.normalize_catalog(payload)

    def test_ultracode_is_not_a_scalar_effort_choice(self):
        payload = self.payload()
        payload["models"][0]["supportedEffortLevels"].append("ultracode")
        self.assertNotIn("ultracode", helper.normalize_catalog(payload)[0]["efforts"])

    def test_selection_requires_current_model_and_model_specific_effort(self):
        helper.validate_selection(self.catalog(), "opus", "max")
        for model, effort in (("retired", "max"), ("simple", "max"), ("opus", "xhigh")):
            with self.subTest(model=model, effort=effort), self.assertRaises(ValueError):
                helper.validate_selection(self.catalog(), model, effort)

    def test_omitted_effort_is_explicit_default_choice(self):
        args = helper.review_command(self.exe, self.mcp, "simple", "default")
        self.assertNotIn("--effort", args)
        self.assertEqual(args[args.index("--model") + 1], "simple")

    def test_review_preserves_isolation_flags(self):
        args = helper.review_command(self.exe, self.mcp, "opus", "max")
        for flag in ("--safe-mode", "--strict-mcp-config", "--disable-slash-commands",
                     "--no-session-persistence", "--no-chrome"):
            self.assertIn(flag, args)
        self.assertEqual(args[args.index("--tools") + 1], "")
        self.assertEqual(args[args.index("--setting-sources") + 1], "")
        self.assertNotIn("--bare", args)
        self.assertNotIn("--fallback-model", args)

    def test_environment_removes_alternative_credentials(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fixture-secret", "CLAUDE_CODE_USE_BEDROCK": "1",
                                    "CLAUDE_CODE_OAUTH_TOKEN": "fixture-secret", "HTTP_PROXY": "fixture"}):
            env = helper.clean_environment()
        for key in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_OAUTH_TOKEN", "HTTP_PROXY"):
            self.assertNotIn(key, env)
        self.assertEqual(env["CLAUDE_CODE_SAFE_MODE"], "1")

    def test_config_accepts_additive_evidence_without_freezing_hash(self):
        self.config_file.write_text(json.dumps({"exe": str(self.exe), "observed_version": "old", "sha256": "old"}))
        self.assertEqual(helper.load_config(self.config_file)["exe"], str(self.exe))
        self.exe.write_bytes(b"MZupdated-fixture")
        self.assertEqual(helper.load_config(self.config_file)["exe"], str(self.exe))

    def test_config_rejects_shell_shim(self):
        shim = self.root / "fixture.cmd"
        shim.write_text("echo fixture")
        self.config_file.write_text(json.dumps({"exe": str(shim)}))
        with self.assertRaises(ValueError):
            helper.load_config(self.config_file)

    def test_release_advisory_checks_fixed_public_endpoint_without_blocking_newer_runtime(self):
        for installed, latest, expected in (("2.1.227 (Claude Code)", "2.1.282", True),
                                             ("2.1.282 (Claude Code)", "2.1.282", False),
                                             ("9.0.0 (Claude Code)", "2.1.282", False)):
            with self.subTest(installed=installed), patch.object(helper.urllib.request, "urlopen", return_value=io.BytesIO(latest.encode())) as request:
                advice = helper.check_runtime_update(installed)
            self.assertEqual(advice["status"], "checked")
            self.assertEqual(advice["update_available"], expected)
            args, kwargs = request.call_args
            self.assertEqual(args[0].full_url, helper.RELEASE_VERSION_URL)
            self.assertEqual(kwargs["timeout"], 5)
            self.assertNotIn("Authorization", args[0].headers)

    def test_release_advisory_does_not_leak_errors_or_claim_currentness(self):
        for content in (b"not-a-release-secret", b"2.1.282\nprivate-secret", b"a" * 129):
            with self.subTest(content=content), patch.object(helper.urllib.request, "urlopen", return_value=io.BytesIO(content)):
                advice = helper.check_runtime_update("2.1.227 (Claude Code)")
            self.assertEqual(advice["status"], "unavailable")
            self.assertIsNone(advice["latest_version"])
            self.assertIsNone(advice["update_available"])
            self.assertNotIn("secret", json.dumps(advice))
        with patch.object(helper.urllib.request, "urlopen", side_effect=OSError("private-network-secret")):
            advice = helper.check_runtime_update("2.1.227 (Claude Code)")
        self.assertEqual(advice["status"], "unavailable")
        self.assertNotIn("secret", json.dumps(advice))

    def test_runtime_requires_claude_subscription_not_api_login(self):
        responses = [
            {"returncode": 0, "timed_out": False, "stdout": b"9.0.0 (Claude Code)", "stderr": b""},
            {"returncode": 0, "timed_out": False, "stdout": " ".join(helper.REQUIRED_FLAGS).encode(), "stderr": b""},
            {"returncode": 0, "timed_out": False,
             "stdout": b'{"loggedIn":true,"authMethod":"api-key","secret":"never-save-me"}', "stderr": b""},
        ]
        with patch.object(helper, "verify_publisher", return_value={}), patch.object(helper, "run_child", side_effect=responses):
            with self.assertRaisesRegex(ValueError, "claude.ai") as caught:
                helper.runtime_preflight({"exe": str(self.exe)}, self.root, {})
        self.assertNotIn("never-save-me", str(caught.exception))

    def test_native_metadata_uses_control_frame_only(self):
        script = (
            "import sys,json; frame=json.loads(sys.stdin.readline()); "
            "assert frame['type']=='control_request'; assert frame['request']['subtype']=='initialize'; "
            "payload={'models':[{'value':'future','displayName':'Future','supportsEffort':False}]}; "
            "print(json.dumps({'type':'control_response','response':{'subtype':'success',"
            "'request_id':frame['request_id'],'response':payload}}),flush=True); "
            "rest=sys.stdin.read(); assert not rest"
        )
        payload = helper.initialize_metadata([sys.executable, "-c", script], self.root, helper.clean_environment(), timeout=5)
        self.assertEqual(payload["models"][0]["value"], "future")

    def test_metadata_rejects_model_activity(self):
        script = "import sys,json; sys.stdin.readline(); print(json.dumps({'type':'assistant','message':'not-metadata'}),flush=True)"
        with self.assertRaisesRegex(ValueError, "non-metadata"):
            helper.initialize_metadata([sys.executable, "-c", script], self.root, helper.clean_environment(), timeout=5)

    def test_metadata_rejects_error_without_echoing_sensitive_message(self):
        script = (
            "import sys,json; f=json.loads(sys.stdin.readline()); "
            "print(json.dumps({'type':'control_response','response':{'subtype':'error',"
            "'request_id':f['request_id'],'error':'sensitive-auth-challenge'}}),flush=True)"
        )
        with self.assertRaisesRegex(ValueError, "refused") as caught:
            helper.initialize_metadata([sys.executable, "-c", script], self.root, helper.clean_environment(), timeout=5)
        self.assertNotIn("sensitive", str(caught.exception))

    def test_discovery_returns_no_raw_account_data(self):
        payload = self.payload()
        payload["account"] = {"email": "private@example.invalid", "organization": "private-org"}
        checks = {"runtime_version": "future", "runtime_provenance": {"sha256": "fixture"},
                  "auth": {"loggedIn": True, "authMethod": "claude.ai"}}
        with patch.object(helper, "runtime_preflight", return_value=checks), patch.object(helper, "initialize_metadata", return_value=payload), patch.object(helper, "check_runtime_update", return_value={"status": "unavailable"}):
            catalog = helper.discover_in_workspace({"exe": str(self.exe)}, self.root, {}, self.mcp)
        text = json.dumps(catalog)
        self.assertNotIn("private@example", text)
        self.assertNotIn("private-org", text)
        self.assertIsInstance(catalog["evidence"], str)
        self.assertFalse(catalog["discovery_details"]["user_prompt_sent"])

    def test_result_metadata_does_not_claim_backend_attestation(self):
        text, receipt = helper.capture_response({"type": "result", "subtype": "success", "is_error": False,
                                                "result": "Fixture answer", "modelUsage": {"future-model": {}}}, 0)
        self.assertEqual(text, "Fixture answer")
        self.assertEqual(receipt["verified_response_models"], [])
        self.assertEqual(receipt["observed_cli_models"], ["future-model"])

    def test_review_requires_explicit_choices(self):
        with patch.object(sys, "argv", ["helper", "--prompt-file", "packet", "--output-dir", "out"]):
            with self.assertRaises(SystemExit) as caught:
                helper.main()
        self.assertEqual(caught.exception.code, 2)

    def test_review_packet_remains_exact_and_preflight_failure_sends_nothing(self):
        packet = self.root / "packet.txt"
        packet.write_text("FixtureSender: Please check this. Thank you. π", encoding="utf-8")
        output = self.root / "out"
        argv = ["helper", "--config", str(self.config_file), "--prompt-file", str(packet),
                "--output-dir", str(output), "--model", "opus", "--effort", "max"]
        with patch.object(sys, "argv", argv), patch.object(helper, "discover_in_workspace", side_effect=ValueError("Fixture discovery failure")), redirect_stdout(io.StringIO()):
            self.assertEqual(helper.main(), 1)
        self.assertEqual((output / "prompt.txt").read_bytes(), packet.read_bytes())
        self.assertEqual((output / "request.txt").read_bytes(), packet.read_bytes())
        metadata = json.loads((output / "metadata.json").read_text())
        self.assertFalse(metadata["sent"])
        self.assertFalse(metadata["submission_attempted"])

    def test_auth_error_stdout_and_stderr_are_not_persisted(self):
        packet = self.root / "packet.txt"
        packet.write_text("Synthetic packet", encoding="utf-8")
        output = self.root / "failed-out"
        argv = ["helper", "--config", str(self.config_file), "--prompt-file", str(packet),
                "--output-dir", str(output), "--model", "opus", "--effort", "max"]
        failure = {"stdout": b"sensitive-login-code-on-stdout", "stderr": b"sensitive-login-code-on-stderr",
                   "returncode": 1, "timed_out": False, "runtime_seconds": 0.01}
        with patch.object(sys, "argv", argv), patch.object(helper, "discover_in_workspace", return_value=self.catalog()), patch.object(helper, "run_child", return_value=failure), redirect_stdout(io.StringIO()):
            self.assertEqual(helper.main(), 1)
        combined = b"".join(path.read_bytes() for path in output.iterdir())
        self.assertNotIn(b"sensitive-login-code", combined)
        self.assertFalse((output / "response.raw.json").exists())


if __name__ == "__main__":
    unittest.main()
