"""Offline Grok helper contract tests. No provider or real CLI is invoked."""
from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


HELPER_PATH = Path(__file__).resolve().parents[1] / "scripts/grok_check.py"
SPEC = importlib.util.spec_from_file_location("grok_under_test", HELPER_PATH)
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)


class RetainedInput(io.BytesIO):
    def close(self):
        self.sent = self.getvalue()
        super().close()


class FakeProcess:
    def __init__(self, messages):
        self.stdin = RetainedInput()
        self.stdout = io.BytesIO(b"".join(json.dumps(m).encode() + b"\n" for m in messages))
        self.stderr = io.BytesIO(b"")
        self.returncode = None
        self.pid = 999999999

    def wait(self, timeout):
        self.returncode = 0
        return 0

    def poll(self):
        return self.returncode


class GrokHelperTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="reviewhub-grok-offline-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.profile = self.root / "profile"
        self.profile.mkdir()
        self.work = self.root / "work"
        self.work.mkdir()
        self.exe = self.root / "fixture-not-executable.bin"
        self.exe.write_bytes(b"Synthetic fixture only")
        self.config = {"exe": self.exe, "profile": self.profile}
        self.config_path = self.root / "grok.json"
        self.config_path.write_text(json.dumps({k: str(v) for k, v in self.config.items()}), encoding="utf-8")

    def startup(self):
        return {"projectRoot": None, "projectInstructions": [], "skills": [], "agents": [],
                "plugins": [], "hooks": [], "mcpServers": [], "lspServers": [], "marketplaces": [],
                "permissions": {"sources": [], "skipped": [], "mcpLockdownSources": [],
                    "marketplaceLockdownSources": [], "managedMarketplaces": [],
                    "managedSettingsActive": False, "managedSettingsExists": False},
                "configSources": {"layers": []}, "externalCompat": {"cells": []}}

    def catalog_payload(self):
        return {"result": {"currentModelId": "grok-future", "availableModels": [
            {"modelId": "grok-future", "name": "Future Model", "_meta": {
                "supportsReasoningEffort": True, "reasoningEffort": "high", "additiveMetadata": 123,
                "reasoningEfforts": [{"id": "deep", "value": "xhigh", "label": "Deep"},
                                     {"id": "balanced", "value": "medium", "label": "Balanced"}]}},
            {"modelId": "grok-plain", "name": "Plain Model", "_meta": {}}]}, "newMetadata": True}

    def catalog(self):
        models, evidence = helper.normalize_catalog(self.catalog_payload())
        return {"provider": "grok", "source": "official_cli", "runtime_version": "grok synthetic",
                "models": models, "evidence": "Synthetic metadata only", "discovery_details": evidence}

    def result(self, stdout=b"", **kwargs):
        return {"stdout": stdout, "stderr": b"", "returncode": 0, "timed_out": False,
                "runtime_seconds": 0, **kwargs}

    def response(self, **changes):
        return {"text": "Synthetic review result", "stopReason": "end_turn", "sessionId": "test-session",
                "requestId": "test-request", "num_turns": 1, "usage": {"input_tokens": 1},
                "modelUsage": {"grok-future-build": {"modelCalls": 1}}, **changes}

    def test_runtime_config_accepts_future_metadata_and_preserves_profile(self):
        self.config_path.write_text(json.dumps({"exe": str(self.exe), "profile": str(self.profile),
                                               "version": "future-release", "extra": True}), encoding="utf-8")
        loaded = helper.load_config(self.config_path)
        self.assertEqual(loaded, self.config)

    def test_environment_removes_auth_routing_proxy_and_external_startup_injections(self):
        dangerous = {"XAI_API_KEY": "fixture", "GROK_AUTH": "fixture", "GROK_AUTH_PATH": "fixture",
            "GROK_MODELS_LIST_URL": "https://invalid.example", "GROK_CLI_CHAT_PROXY_BASE_URL": "fixture",
            "HTTPS_PROXY": "fixture", "GROK_DEPLOYMENT_KEY": "fixture", "PYTHONPATH": "fixture"}
        with patch.dict(os.environ, dangerous):
            env = helper.safe_env(self.profile)
        self.assertFalse(set(dangerous) & set(env))
        self.assertEqual(env["GROK_HOME"], str(self.profile))
        self.assertEqual(env["GROK_CLAUDE_HOOKS_ENABLED"], "0")
        self.assertEqual(env["GROK_WORKFLOWS"], "0")

    def test_worker_loaded_helper_no_arg_environment_uses_configured_profile(self):
        from coda_review_hub.worker import load_helper

        # Match the worker's verified-byte snapshot import and no-argument call,
        # using only a synthetic local executable/profile configuration.
        runner = self.work / "pinned_helper.py"
        runner.write_bytes(HELPER_PATH.read_bytes())
        worker_helper = load_helper(runner)
        injected = {"XAI_API_KEY": "fixture-secret", "GROK_AUTH_PATH": "untrusted",
                    "GROK_HOME": "wrong-profile", "HTTPS_PROXY": "untrusted",
                    "GROK_CLAUDE_HOOKS_ENABLED": "1", "PYTHONPATH": "untrusted"}
        with patch.object(worker_helper, "DEFAULT_CONFIG", self.config_path), patch.dict(os.environ, injected):
            env = worker_helper.safe_env()
            explicit = worker_helper.safe_env(self.profile)
        self.assertEqual(env, explicit)
        self.assertEqual(env["GROK_HOME"], str(self.profile.resolve()))
        self.assertFalse({"XAI_API_KEY", "GROK_AUTH_PATH", "HTTPS_PROXY", "PYTHONPATH"} & set(env))
        self.assertEqual(env["GROK_CLAUDE_HOOKS_ENABLED"], "0")
        self.assertEqual(env["GROK_DISABLE_AUTOUPDATER"], "1")

    def test_no_arg_environment_fails_closed_for_missing_runtime_config(self):
        with patch.object(helper, "DEFAULT_CONFIG", self.root / "missing.json"), \
             self.assertRaises(FileNotFoundError):
            helper.safe_env()

    def test_explicit_profile_environment_does_not_require_default_config(self):
        with patch.object(helper, "load_config", side_effect=AssertionError("must not read default config")):
            env = helper.safe_env(self.profile)
        self.assertEqual(env["GROK_HOME"], str(self.profile))

    @unittest.skipUnless(os.name == "nt", "Windows publisher contract")
    def test_publisher_validation_accepts_changed_signed_bytes_without_version_pin(self):
        signature = self.result(json.dumps({"status": "Valid", "subject": "CN=X.AI LLC, O=X.AI LLC, C=US"}).encode())
        with patch.object(helper, "run_child", return_value=signature) as child:
            first = helper.verify_runtime(self.exe, self.work, {})
            self.exe.write_bytes(b"A different synthetic official release")
            second = helper.verify_runtime(self.exe, self.work, {})
        self.assertNotEqual(first["executable_sha256"], second["executable_sha256"])
        self.assertTrue(first["valid"] and second["valid"])
        self.assertEqual(child.call_args.args[2]["REVIEW_HUB_VERIFY_EXE"], str(self.exe))
        self.assertNotIn(str(self.exe), child.call_args.args[0][-1])

    @unittest.skipUnless(os.name == "nt", "Windows publisher contract")
    def test_publisher_validation_rejects_untrusted_or_other_signed_publishers(self):
        for status, subject in (("NotSigned", "O=X.AI LLC"), ("Valid", "O=Another Publisher"),
                                ("Valid", "O=X.AI LLC Impostor")):
            signature = self.result(json.dumps({"status": status, "subject": subject}).encode())
            with self.subTest(status=status, subject=subject), \
                 patch.object(helper, "run_child", return_value=signature), self.assertRaises(RuntimeError):
                helper.verify_runtime(self.exe, self.work, {})

    def test_startup_accepts_additive_metadata_but_requires_guard_fields(self):
        data = self.startup()
        data["harmlessVersionMetadata"] = {"future": True}
        self.assertTrue(helper.inspect_startup(data, self.profile)["passed"])
        del data["hooks"]
        with self.assertRaises(ValueError):
            helper.inspect_startup(data, self.profile)

    def test_startup_rejects_byok_model_config_despite_subscription_banner(self):
        data = self.startup()
        config_file = self.profile / "config.toml"
        config_file.write_text('[model.test]\napi_key = "synthetic-not-a-key"\n', encoding="utf-8")
        data["configSources"]["layers"] = [{"role": "user", "path": str(config_file)}]
        result = helper.inspect_startup(data, self.profile)
        self.assertFalse(result["passed"])
        self.assertIn("unexpected_config_key_group", result["failure_categories"])

    def test_startup_rejects_hooks_external_imports_and_unexpected_layers(self):
        data = self.startup()
        data["hooks"] = [{"name": "fixture"}]
        data["externalCompat"]["cells"] = [{"enabled": True}]
        data["configSources"]["layers"] = [{"role": "project", "path": "must-not-be-read"}]
        result = helper.inspect_startup(data, self.profile)
        self.assertEqual(set(result["failure_categories"]),
                         {"hooks", "external_compatibility_enabled", "unexpected_config_layer"})

    def test_auth_catalog_requires_exact_oauth_host_banner(self):
        valid = "You are logged in with grok.com.\n\nAvailable models:\n  * grok-future (default)\n  - grok-plain\n"
        self.assertEqual(helper.auth_catalog(valid), {"grok-future", "grok-plain"})
        self.assertEqual(helper.auth_catalog(valid.replace("\n", "\r\n")), {"grok-future", "grok-plain"})
        for banner in ("You are using XAI_API_KEY.", "You are logged in with grok.com.attacker.",
                       "You are not authenticated."):
            with self.subTest(banner=banner), self.assertRaises(RuntimeError):
                helper.auth_catalog(valid.replace("You are logged in with grok.com.", banner))

    def test_dynamic_model_and_remapped_effort_catalog(self):
        models, evidence = helper.normalize_catalog(self.catalog_payload())
        self.assertEqual(models[0], {"id": "grok-future", "label": "Future Model", "efforts": ["deep", "balanced"]})
        self.assertEqual(models[1]["efforts"], ["default"])
        self.assertEqual(evidence["effort_menus"]["grok-future"]["options"][0], {"id": "deep", "value": "xhigh"})

    def test_missing_effort_menu_is_not_a_fabricated_legacy_default(self):
        data = self.catalog_payload()
        del data["result"]["availableModels"][0]["_meta"]["reasoningEfforts"]
        with self.assertRaisesRegex(ValueError, "does not advertise"):
            helper.normalize_catalog(data)

    def test_catalog_rejects_nested_errors_duplicate_ids_and_wrong_types(self):
        data = self.catalog_payload()
        data["error"] = "fixture failure"
        with self.assertRaises(ValueError):
            helper.normalize_catalog(data)
        data = self.catalog_payload()
        data["result"]["availableModels"].append(data["result"]["availableModels"][0])
        with self.assertRaises(ValueError):
            helper.normalize_catalog(data)
        data = self.catalog_payload()
        data["result"]["availableModels"][0]["_meta"]["supportsReasoningEffort"] = "true"
        with self.assertRaises(ValueError):
            helper.normalize_catalog(data)

    def test_selection_never_silently_downgrades_and_omits_unsupported_effort(self):
        catalog = self.catalog()
        self.assertEqual(helper.validate_selection(catalog, "grok-future", "deep"), "deep")
        for invalid in (("unknown", "deep"), ("grok-future", "max"), ("grok-plain", "deep")):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                helper.validate_selection(catalog, *invalid)
        for sentinel in ("none", "default"):
            effort = helper.validate_selection(catalog, "grok-plain", sentinel)
            self.assertIsNone(effort)
            command = helper.review_command(self.exe, self.root / "packet.txt", "grok-plain", effort)
            self.assertNotIn("--reasoning-effort", command)

    def test_acp_discovery_sends_exactly_initialize_and_catalog_without_auth_or_session(self):
        process = FakeProcess([
            {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": 1, "authMethods": [{"id": "cached_token"}]}},
            {"jsonrpc": "2.0", "id": 2, "result": self.catalog_payload()}])
        with patch.object(helper.subprocess, "Popen", return_value=process) as popen:
            payload, evidence = helper.acp_catalog(self.exe, self.work, {}, timeout=2)
        sent = [json.loads(line) for line in process.stdin.sent.splitlines()]
        self.assertEqual([m["method"] for m in sent], ["initialize", "_x.ai/models/list"])
        self.assertEqual(sent[1]["params"], {})
        self.assertFalse(sent[0]["params"]["clientCapabilities"]["terminal"])
        self.assertFalse(evidence["prompt_sent"])
        self.assertFalse(evidence["auth_attempted"])
        self.assertFalse(evidence["session_created"])
        self.assertEqual(payload, self.catalog_payload())
        self.assertIn("--no-leader", popen.call_args.args[0])
        self.assertFalse(popen.call_args.kwargs["shell"])

    def test_acp_discovery_refuses_client_requests_without_executing_them(self):
        process = FakeProcess([{"jsonrpc": "2.0", "id": 8, "method": "fs/read_text_file",
                                "params": {"path": "unrelated"}}])
        with patch.object(helper.subprocess, "Popen", return_value=process), self.assertRaises(RuntimeError):
            helper.acp_catalog(self.exe, self.work, {}, timeout=2)
        sent = [json.loads(line) for line in process.stdin.sent.splitlines()]
        self.assertEqual(sent[-1]["error"]["code"], -32601)
        self.assertEqual(len(sent), 2)

    def test_acp_discovery_does_not_authenticate_or_prompt_after_unknown_method(self):
        process = FakeProcess([
            {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": 1, "authMethods": [{"id": "cached_token"}]}},
            {"jsonrpc": "2.0", "id": 2, "error": {"code": -32601, "message": "not supported"}}])
        with patch.object(helper.subprocess, "Popen", return_value=process), self.assertRaises(RuntimeError):
            helper.acp_catalog(self.exe, self.work, {}, timeout=2)
        sent = [json.loads(line) for line in process.stdin.sent.splitlines()]
        self.assertEqual([m["method"] for m in sent], ["initialize", "_x.ai/models/list"])

    def test_full_discovery_uses_no_generating_commands_and_keeps_only_sanitized_evidence(self):
        results = [self.result(b"grok 99.0.0"), self.result(json.dumps(self.startup()).encode()),
                   self.result(b"You are logged in with grok.com.\nAvailable models:\n * grok-future (default)\n - grok-plain\n")]
        trust = {"method": "fixture", "valid": True, "executable_sha256": helper.sha256(self.exe.read_bytes())}
        with patch.object(helper, "verify_runtime", return_value=trust), \
             patch.object(helper, "run_child", side_effect=results) as child, \
             patch.object(helper, "acp_catalog", return_value=(self.catalog_payload(), {"prompt_sent": False})):
            catalog = helper._discover(self.config, self.work, {})
        self.assertEqual(catalog["runtime_version"], "grok 99.0.0")
        self.assertEqual([m["id"] for m in catalog["models"]], ["grok-future", "grok-plain"])
        for call in child.call_args_list:
            self.assertNotIn("--prompt-file", call.args[0])
            self.assertNotIn("-p", call.args[0])
        self.assertIsInstance(catalog["evidence"], str)
        self.assertLess(len(catalog["evidence"]), 300)
        self.assertFalse(catalog["discovery_details"]["subscription_quota_verified"])

    def test_response_accepts_additive_metadata_and_rejects_conflicting_completion(self):
        self.assertTrue(helper.capture_response(self.response(additive={"future": 1}))["model_review_completed"])
        for changes in ({"terminal_reason": "error"}, {"stop_reason": "max_tokens"},
                        {"subtype": "error"}, {"toolCalls": [{"name": "fixture"}]},
                        {"num_turns": 2}, {"is_error": True}):
            with self.subTest(changes=changes):
                self.assertFalse(helper.capture_response(self.response(**changes))["model_review_completed"])

    def test_dry_run_preserves_bytes_and_never_launches_or_writes(self):
        packet = self.root / "packet.txt"
        content = "FixtureCoordinator: Review this packet. Thank you. π\n".encode()
        packet.write_bytes(content)
        output = self.root / "new-output"
        argv = ["grok_check.py", "--config", str(self.config_path), "--prompt-file", str(packet),
                "--output-dir", str(output), "--model", "grok-future", "--effort", "deep", "--dry-run"]
        text = io.StringIO()
        with patch.object(sys, "argv", argv), patch.object(helper.subprocess, "Popen") as popen, redirect_stdout(text):
            self.assertEqual(helper.main(), 0)
        popen.assert_not_called()
        self.assertFalse(output.exists())
        receipt = json.loads(text.getvalue())
        self.assertEqual(receipt["request_sha256"], helper.sha256(content))
        self.assertEqual(receipt["prompt_sha256"], receipt["request_sha256"])

    def test_review_requires_explicit_model_and_effort(self):
        argv = ["grok_check.py", "--config", str(self.config_path), "--prompt-file", "unused",
                "--output-dir", "unused"]
        with patch.object(sys, "argv", argv), patch.object(helper.subprocess, "Popen") as popen, \
             patch.object(sys, "stderr", io.StringIO()), self.assertRaises(SystemExit):
            helper.main()
        popen.assert_not_called()

    def test_review_saves_original_packet_unchanged_and_validates_before_dispatch(self):
        packet = self.root / "packet.txt"
        content = b"NeutralCoordinator: Please check this bounded text. Thank you.\n"
        packet.write_bytes(content)
        output = self.root / "review-output"
        argv = ["grok_check.py", "--config", str(self.config_path), "--prompt-file", str(packet),
                "--output-dir", str(output), "--model", "grok-future", "--effort", "deep"]
        with patch.object(sys, "argv", argv), patch.object(helper, "_discover", return_value=self.catalog()), \
             patch.object(helper, "run_child", return_value=self.result(json.dumps(self.response()).encode(),
                 stderr=b"SYNTHETIC-LOGIN-SECRET must never persist")) as child, \
             redirect_stdout(io.StringIO()):
            self.assertEqual(helper.main(), 0)
        self.assertEqual((output / "request.txt").read_bytes(), content)
        self.assertEqual((output / "prompt.txt").read_bytes(), content)
        self.assertIn("deep", child.call_args.args[0])
        self.assertEqual(json.loads((output / "metadata.json").read_text())["status"], "completed")
        self.assertFalse((output / "stderr.txt").exists())
        self.assertTrue((output / "response.raw.json").exists())
        self.assertNotIn(b"SYNTHETIC-LOGIN-SECRET", b"".join(p.read_bytes() for p in output.iterdir()))

    def test_failed_review_discards_auth_text_error_json_and_stderr(self):
        secret = "SYNTHETIC-LOGIN-SECRET"
        responses = [
            self.result(("Open https://invalid.example/login?code=" + secret).encode(), returncode=1),
            self.result(("Device code: " + secret).encode()),
            self.result(json.dumps({"type": "error", "text": secret, "error": secret,
                                    secret: True, "modelUsage": {secret: {"modelCalls": 1}}}).encode()),
            self.result(json.dumps(self.response(text=secret, stopReason="max_tokens")).encode()),
            self.result(secret.encode(), timed_out=True),
        ]
        packet = self.root / "packet.txt"
        packet.write_text("NeutralCoordinator: Bounded fixture.", encoding="utf-8")
        for index, response in enumerate(responses):
            response["stderr"] = ("Login code " + secret).encode()
            output = self.root / f"failed-output-{index}"
            argv = ["grok_check.py", "--config", str(self.config_path), "--prompt-file", str(packet),
                    "--output-dir", str(output), "--model", "grok-future", "--effort", "deep"]
            console = io.StringIO()
            with self.subTest(index=index), patch.object(sys, "argv", argv), \
                 patch.object(helper, "_discover", return_value=self.catalog()), \
                 patch.object(helper, "run_child", return_value=response), redirect_stdout(console):
                self.assertEqual(helper.main(), 1)
            files = {p.name for p in output.iterdir()}
            self.assertEqual(files, {"prompt.txt", "request.txt", "metadata.json"})
            saved = b"".join(p.read_bytes() for p in output.iterdir()).decode()
            self.assertNotIn(secret, saved + console.getvalue())
            self.assertFalse(json.loads((output / "metadata.json").read_text())["model_review_completed"])

    def test_discovery_failure_console_never_copies_arbitrary_exception_text(self):
        secret = "SYNTHETIC-LOGIN-SECRET"
        argv = ["grok_check.py", "--config", str(self.config_path), "--discover-models"]
        console = io.StringIO()
        with patch.object(sys, "argv", argv), \
             patch.object(helper, "discover_models", side_effect=RuntimeError(secret)), redirect_stdout(console):
            self.assertEqual(helper.main(), 1)
        self.assertNotIn(secret, console.getvalue())
        self.assertFalse(json.loads(console.getvalue())["prompt_sent"])

    def test_discovery_version_and_inspection_failures_discard_login_output(self):
        secret = "SYNTHETIC-LOGIN-SECRET"
        trust = {"method": "fixture", "valid": True, "executable_sha256": helper.sha256(self.exe.read_bytes())}
        scenarios = [[self.result(secret.encode())],
                     [self.result(b"grok 99.0.0"), self.result(("Login code " + secret).encode())]]
        for responses in scenarios:
            with patch.object(helper, "verify_runtime", return_value=trust), \
                 patch.object(helper, "run_child", side_effect=responses), self.assertRaises(RuntimeError) as error:
                helper._discover(self.config, self.work, {})
            self.assertNotIn(secret, str(error.exception))


if __name__ == "__main__":
    unittest.main()
