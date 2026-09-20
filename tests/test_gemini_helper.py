"""Offline Gemini helper checks: fake runtimes, profiles and ACP subprocesses only."""

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

import test_core


HELPER_PATH = Path(__file__).resolve().parents[1] / "scripts" / "gemini_check.py"
SPEC = importlib.util.spec_from_file_location("gemini_helper_under_test", HELPER_PATH)
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)


class GeminiHelperTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="reviewhub-gemini-offline-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.profile = self.root / "profile"
        self.dot = self.profile / ".gemini"
        self.dot.mkdir(parents=True)
        self.runtime = self.root / "runtime"
        (self.runtime / "bundle" / "chunks").mkdir(parents=True)
        self.node = self.root / "fake-node.bin"
        self.node.write_bytes(b"not an executable; synthetic hash-pin fixture only")
        (self.runtime / "package.json").write_text(json.dumps({"name": "@google/gemini-cli", "version": helper.VERSION}), encoding="utf-8")
        (self.runtime / "bundle" / "gemini.js").write_text("// synthetic non-executable fixture\n", encoding="utf-8")
        (self.runtime / "bundle" / "chunks" / "dependency.js").write_text("// synthetic dependency\n", encoding="utf-8")
        self.config = {
            "version": helper.VERSION, "node": str(self.node), "node_sha256": helper.sha(self.node.read_bytes()),
            "cli_root": str(self.runtime), "cli_tree_sha256": helper.tree_digest(self.runtime), "profile": str(self.profile),
        }
        self.config_path = self.root / "config.json"
        self.config_path.write_text(json.dumps(self.config), encoding="utf-8")
        self.prompt = self.root / "packet.txt"
        self.prompt.write_bytes("FixtureAgent: Review only this synthetic packet. π\n".encode("utf-8"))

    def valid_response(self, **overrides):
        value = {
            "session_id": "synthetic-session", "response": "Synthetic final answer only.",
            "stats": {"models": {helper.MODEL: {"api": {"totalRequests": 1}}}, "tools": {"totalCalls": 0}},
        }
        value.update(overrides)
        return value

    def interpret(self, response, code=0):
        return helper.interpret_response(json.dumps(response).encode("utf-8"), code, helper.MODEL)

    def main_args(self, output, *extra):
        return ["--config", str(self.config_path), "--prompt-file", str(self.prompt), "--output-dir", str(output), *extra]

    def test_environment_allowlist_excludes_api_keys_proxies_and_runtime_injection(self):
        retained = {"SystemRoot": "C:/Windows", "HOME": "fixture-home", "TEMP": "fixture-temp", "LOCALAPPDATA": "fixture-local"}
        excluded = {name: "synthetic-value" for name in (
            "GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_CLOUD_PROJECT",
            "GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_GENAI_USE_GCA", "CLOUDSDK_AUTH_ACCESS_TOKEN",
            "GEMINI_CLI_HOME", "GEMINI_CLI_SYSTEM_SETTINGS_PATH", "GEMINI_SYSTEM_MD", "NODE_OPTIONS",
            "NODE_PATH", "PATH", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "SSL_CERT_FILE",
            "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "AWS_ACCESS_KEY_ID", "CUSTOM_SECRET",
        )}
        with patch.dict(os.environ, {**retained, **excluded}, clear=True):
            self.assertEqual({key.upper(): value for key, value in helper.safe_env().items()},
                             {key.upper(): value for key, value in retained.items()})
            work = self.root / "work"
            work.mkdir()
            command, env = helper.prepare_runtime(self.config, work)
        self.assertEqual(command[:2], [str(self.node), str(self.runtime / "bundle" / "gemini.js")])
        self.assertEqual(command[2:4], ["--extensions", "none"])
        self.assertEqual(env["GEMINI_CLI_HOME"], str(self.profile))
        self.assertEqual(env["HOME"], str(self.profile))
        self.assertEqual(env["USERPROFILE"], str(self.profile))
        self.assertEqual(env["NO_BROWSER"], "1")
        self.assertEqual(env["PATH"], str(self.node.parent) + os.pathsep + str(Path("C:/Windows") / "System32"))
        for name in excluded.keys() - {"PATH", "GEMINI_CLI_HOME", "GEMINI_CLI_SYSTEM_SETTINGS_PATH", "GEMINI_SYSTEM_MD"}:
            self.assertNotIn(name, env)
        settings = json.loads((work / "system.json").read_text(encoding="utf-8"))
        self.assertEqual(settings["security"]["auth"]["enforcedType"], "oauth-personal")
        self.assertEqual(settings["billing"]["overageStrategy"], "never")
        self.assertEqual(settings["tools"]["core"], [])
        self.assertFalse(settings["hooksConfig"]["enabled"])
        self.assertFalse(settings["admin"]["mcp"]["enabled"])
        self.assertFalse(settings["admin"]["extensions"]["enabled"])
        self.assertEqual((work / "deny.toml").read_text(encoding="utf-8"), helper.DENY_POLICY)
        self.assertEqual((work / ".gemini" / ".env").read_bytes(), b"")

    def test_raw_file_mentions_and_slash_input_are_encoded_losslessly(self):
        packet = "/command @outside.txt\n@decorator\nreader@example.invalid π\n".encode("utf-8")
        request = helper.prepare_request(packet)
        self.assertNotIn(b"@", request)
        self.assertFalse(request.startswith(b"/"))
        self.assertIn(b"\\u0040", request)
        decoded = json.loads(request.decode("utf-8").split("\n", 1)[1])
        self.assertEqual(decoded["review_packet"].encode("utf-8"), packet)
        for invalid in (b"", b" \n\t", b"\xff", b"x" * 131073, b"x" * 131072, b"@" * 22000):
            with self.subTest(invalid_size=len(invalid)):
                with self.assertRaises((ValueError, UnicodeError)):
                    helper.prepare_request(invalid)
        self.assertTrue(helper.prepare_request(b"x" * 130000))

    def test_capability_probe_uses_an_empty_home_without_selecting_oauth(self):
        (self.dot / "oauth_creds.json").write_bytes(b"synthetic marker must never be copied")
        work = self.root / "capability-work"
        work.mkdir()
        command, env = helper.prepare_runtime(self.config, work, capabilities_only=True)
        probe_home = work / "probe-home"
        self.assertEqual(env["GEMINI_CLI_HOME"], str(probe_home))
        self.assertEqual(env["HOME"], str(probe_home))
        self.assertEqual(env["USERPROFILE"], str(probe_home))
        self.assertEqual(list((probe_home / ".gemini").iterdir()), [])
        settings = json.loads((work / "system.json").read_text(encoding="utf-8"))
        self.assertNotIn("selectedType", settings["security"]["auth"])
        self.assertEqual(settings["security"]["auth"]["enforcedType"], "oauth-personal")
        self.assertEqual(env["NO_BROWSER"], "1")
        self.assertNotIn("--prompt", command)

    def test_profile_checks_presence_without_reading_token_bytes(self):
        token = self.dot / "oauth_creds.json"
        token.write_bytes(b"SYNTHETIC_TOKEN_CONTENT_MUST_NOT_BE_READ")
        (self.dot / "settings.json").write_text(json.dumps({"security": {"auth": {"selectedType": "oauth-personal"}}}), encoding="utf-8")
        original_text, original_bytes = Path.read_text, Path.read_bytes

        def guarded_text(path, *args, **kwargs):
            self.assertNotEqual(path, token, "Token contents must not be inspected by preflight")
            return original_text(path, *args, **kwargs)

        def guarded_bytes(path, *args, **kwargs):
            self.assertNotEqual(path, token, "Token contents must not be inspected by preflight")
            return original_bytes(path, *args, **kwargs)

        with patch.object(Path, "read_text", guarded_text), patch.object(Path, "read_bytes", guarded_bytes):
            self.assertTrue(helper.check_profile(self.profile, require_auth=True))
            (self.profile / "GEMINI.md").write_text("Synthetic startup instruction.", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "startup customization"):
                helper.check_profile(self.profile, require_auth=True)

    def test_profile_customizations_and_ancestor_environment_files_are_refused(self):
        customizations = (
            "GEMINI.md", "AGENTS.md", ".agents", ".gemini/extensions", ".gemini/skills",
            ".gemini/commands", ".gemini/policies", ".gemini/agents", ".gemini/GEMINI.md",
        )
        for name in customizations:
            with self.subTest(name=name):
                path = self.profile / name
                path.write_text("Synthetic disallowed customization.", encoding="utf-8")
                try:
                    with self.assertRaisesRegex(ValueError, "startup customization"):
                        helper.check_profile(self.profile, require_auth=False)
                finally:
                    path.unlink()
        for path in (self.profile / ".env", self.dot / ".env", self.root / ".env"):
            with self.subTest(path=path.name):
                path.write_text("SYNTHETIC_FORBIDDEN=1", encoding="utf-8")
                try:
                    with self.assertRaisesRegex(ValueError, "ancestor has an environment file"):
                        helper.check_profile(self.profile, require_auth=False)
                finally:
                    path.unlink()
        settings_path = self.dot / "settings.json"
        for data in ({}, {"security": {"auth": {"selectedType": "gemini-api-key"}}},
                     {"security": {"auth": {"selectedType": "oauth-personal"}}, "mcpServers": {"fixture": {}}}):
            settings_path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "settings differ"):
                helper.check_profile(self.profile, require_auth=False)

    def test_runtime_hashes_cover_node_entrypoint_and_imported_chunks(self):
        self.assertEqual(helper.load_config(self.config_path), self.config)
        for path in (self.node, self.runtime / "bundle" / "gemini.js", self.runtime / "bundle" / "chunks" / "dependency.js"):
            with self.subTest(path=path.name):
                original = path.read_bytes()
                path.write_bytes(original + b"tampered fixture")
                try:
                    with self.assertRaisesRegex(ValueError, "runtime changed"):
                        helper.load_config(self.config_path)
                finally:
                    path.write_bytes(original)
        added = self.runtime / "bundle" / "unexpected.js"
        added.write_text("// unreviewed additional runtime file", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "runtime changed"):
            helper.load_config(self.config_path)

    def test_wrong_runtime_identity_and_unsafe_configuration_are_refused(self):
        package_path = self.runtime / "package.json"
        package_path.write_text(json.dumps({"name": "unofficial-fixture", "version": helper.VERSION}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Unexpected official CLI"):
            helper.load_config(self.config_path)
        package_path.write_text(json.dumps({"name": "@google/gemini-cli", "version": helper.VERSION}), encoding="utf-8")
        for change in ({"version": "0.0.0"}, {"profile": "relative-profile"}, {"unreviewed": "extra"}):
            with self.subTest(change=change):
                self.config_path.write_text(json.dumps({**self.config, **change}), encoding="utf-8")
                with self.assertRaises(ValueError):
                    helper.load_config(self.config_path)

    def test_response_requires_requested_model_no_error_and_zero_tools(self):
        answer, receipt = self.interpret(self.valid_response())
        self.assertEqual(answer, "Synthetic final answer only.")
        self.assertEqual(receipt["status"], "completed")
        self.assertTrue(receipt["model_review_completed"])
        self.assertEqual(receipt["verified_response_models"], [helper.MODEL])
        invalid = [
            self.valid_response(error={"type": "fixture", "message": "Synthetic error"}),
            self.valid_response(warnings=["Maximum turns reached"]),
            self.valid_response(response=""), self.valid_response(response=["invalid answer"]),
            self.valid_response(stats={}), self.valid_response(stats=[]),
            self.valid_response(stats={"models": {"fallback-model": {}}, "tools": {"totalCalls": 0}}),
            self.valid_response(stats={"models": {helper.MODEL: {}, "fallback-model": {}}, "tools": {"totalCalls": 0}}),
        ]
        for calls in (1, -1, False, "0", None):
            invalid.append(self.valid_response(stats={"models": {helper.MODEL: {}}, "tools": {"totalCalls": calls}}))
        for response in invalid:
            with self.subTest(response=response):
                _, receipt = self.interpret(response)
                self.assertFalse(receipt["model_review_completed"])
                self.assertNotEqual(receipt["status"], "completed")
        self.assertFalse(self.interpret(self.valid_response(), code=1)[1]["model_review_completed"])
        for raw in (b"not-json", b"[]", b"null", b"\xff"):
            with self.assertRaises((ValueError, UnicodeError)):
                helper.interpret_response(raw, 0, helper.MODEL)

    def test_explicit_malformed_error_cannot_be_a_success_receipt(self):
        for error in ({}, [], "", False, None):
            with self.subTest(error=error):
                _, receipt = self.interpret(self.valid_response(error=error))
                self.assertFalse(receipt["model_review_completed"], "An explicit malformed error field is not verified success")

    def test_missing_auth_prevents_spawn_and_preserves_exact_request_evidence(self):
        output = self.root / "missing-auth-output"
        with patch.object(helper, "spawn", side_effect=AssertionError("No CLI may launch without auth")) as spawned:
            self.assertEqual(helper.main(self.main_args(output)), 2)
        spawned.assert_not_called()
        metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["status"], "preflight_blocked")
        self.assertFalse(metadata["sent"])
        self.assertFalse(metadata["submission_attempted"])
        self.assertIn("Google sign-in is needed", metadata["error"])
        self.assertEqual((output / "prompt.txt").read_bytes(), self.prompt.read_bytes())
        self.assertEqual(helper.sha((output / "request.txt").read_bytes()), metadata["request_sha256"])
        self.assertFalse((output / "stdout.json").exists())

    def test_dry_run_never_launches_or_creates_output(self):
        output = self.root / "dry-output"
        capture = io.StringIO()
        with patch.object(helper, "spawn", side_effect=AssertionError("Dry run cannot spawn")), redirect_stdout(capture):
            self.assertEqual(helper.main(self.main_args(output, "--dry-run")), 0)
        self.assertFalse(output.exists())
        metadata = json.loads(capture.getvalue())
        self.assertTrue(metadata["runtime_pins_verified"])
        self.assertTrue(metadata["requires_google_signin"])
        self.assertFalse(metadata["sent"])

    def test_synthetic_dispatch_preserves_prompt_request_and_completed_receipt(self):
        (self.dot / "oauth_creds.json").write_bytes(b"synthetic cache marker, not real credentials")
        output = self.root / "synthetic-success"
        captured_request = self.root / "stdin.bin"
        response = self.valid_response()
        program = (
            "import sys; from pathlib import Path; "
            "Path(sys.argv[1]).write_bytes(sys.stdin.buffer.read()); "
            "sys.stdout.write(sys.argv[2])"
        )
        real_spawn = helper.spawn
        commands = []

        def synthetic_spawn(command, cwd, env):
            commands.append(command)
            self.assertEqual(Path(cwd).name[:17], "reviewhub-gemini-")
            return real_spawn([sys.executable, "-I", "-c", program, str(captured_request), json.dumps(response)], cwd, env)

        with patch.object(helper, "spawn", synthetic_spawn):
            self.assertEqual(helper.main(self.main_args(output, "--timeout", "5")), 0)
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0][-6:], ["--model", helper.MODEL, "--output-format", "json", "--prompt", ""])
        metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["status"], "completed")
        self.assertTrue(metadata["model_review_completed"])
        self.assertTrue(metadata["submission_attempted"])
        self.assertEqual(metadata["verified_response_models"], [helper.MODEL])
        self.assertEqual((output / "prompt.txt").read_bytes(), self.prompt.read_bytes())
        self.assertEqual((output / "request.txt").read_bytes(), captured_request.read_bytes())
        self.assertEqual(metadata["request_sha256"], helper.sha(captured_request.read_bytes()))
        self.assertEqual(json.loads((output / "stdout.json").read_bytes()), response)
        self.assertEqual((output / "result.txt").read_text(encoding="utf-8"), response["response"])

    def test_synthetic_dispatch_timeout_remains_delivery_unknown(self):
        (self.dot / "oauth_creds.json").write_bytes(b"synthetic cache marker, not real credentials")
        output = self.root / "synthetic-timeout"
        real_spawn = helper.spawn
        processes = []

        def synthetic_spawn(command, cwd, env):
            process = real_spawn([sys.executable, "-I", "-c", "import sys,time; sys.stdin.buffer.read(); time.sleep(45)"], cwd, env)
            processes.append(process)
            return process

        with patch.object(helper, "spawn", synthetic_spawn):
            self.assertEqual(helper.main(self.main_args(output, "--timeout", "1")), 1)
        self.assertIsNotNone(processes[0].poll())
        metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["status"], "delivery_unknown_timeout")
        self.assertTrue(metadata["sent"])
        self.assertTrue(metadata["submission_attempted"])
        self.assertFalse(metadata["model_review_completed"])
        self.assertFalse((output / "result.txt").exists())

    def test_receipt_write_failure_after_spawn_terminates_the_synthetic_process(self):
        (self.dot / "oauth_creds.json").write_bytes(b"synthetic cache marker, not real credentials")
        output = self.root / "synthetic-receipt-write-failure"
        real_spawn, real_write_json = helper.spawn, helper.write_json
        processes = []

        def synthetic_spawn(command, cwd, env):
            process = real_spawn([sys.executable, "-I", "-c", "import time; time.sleep(45)"], cwd, env)
            processes.append(process)
            return process

        def failing_receipt(path, value):
            if Path(path).name == "metadata.json" and value.get("status") == "dispatch_started":
                raise OSError("Synthetic dispatch receipt write failure")
            return real_write_json(path, value)

        try:
            with patch.object(helper, "spawn", synthetic_spawn), patch.object(helper, "write_json", failing_receipt):
                self.assertEqual(helper.main(self.main_args(output, "--timeout", "5")), 2)
            self.assertEqual(len(processes), 1)
            self.assertIsNotNone(processes[0].poll(), "The launched CLI must be cleaned up if its first receipt cannot be written")
            metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["status"], "delivery_unknown")
            self.assertFalse(metadata["model_review_completed"])
        finally:
            # Keep the regression safe even when the implementation is faulty.
            for process in processes:
                helper.kill_tree(process)
                process.communicate(timeout=10)

    def test_acp_probe_denies_callbacks_and_never_requests_auth_session_or_prompt(self):
        transcript = self.root / "acp-transcript.json"
        program = r'''
import json, sys
from pathlib import Path
request = json.loads(sys.stdin.readline())
records = [request]
for index, method in enumerate(("fs/read_text_file", "fs/write_text_file", "terminal/create", "session/request_permission"), 20):
    print(json.dumps({"jsonrpc": "2.0", "id": index, "method": method, "params": {}}), flush=True)
    records.append(json.loads(sys.stdin.readline()))
Path(sys.argv[1]).write_text(json.dumps(records), encoding="utf-8")
print(json.dumps({"jsonrpc": "2.0", "id": 1, "result": {
    "protocolVersion": 1, "agentInfo": {"name": "synthetic-agent"}, "agentCapabilities": {},
    "authMethods": [{"id": "oauth-personal", "name": "Synthetic Google sign-in", "unneeded": "omit this"}]}}), flush=True)
sys.stdin.read()
'''
        receipt = helper.probe_acp([sys.executable, "-I", "-c", program, str(transcript)], self.root, helper.safe_env(), timeout=5)
        self.assertTrue(receipt["initialized"])
        self.assertFalse(receipt["prompt_sent"])
        self.assertFalse(receipt["session_created"])
        self.assertEqual(receipt["authMethods"], [{"id": "oauth-personal", "name": "Synthetic Google sign-in"}])
        records = json.loads(transcript.read_text(encoding="utf-8"))
        self.assertEqual(records[0]["method"], "initialize")
        self.assertEqual(records[0]["params"]["clientCapabilities"], {"fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False})
        self.assertEqual(len(records), 5)
        self.assertEqual([item["id"] for item in records[1:]], list(range(20, 24)))
        self.assertTrue(all(item["error"]["code"] == -32601 and "method" not in item for item in records[1:]))

    def test_acp_timeout_terminates_synthetic_process_tree(self):
        pids_path = self.root / "timeout-pids.json"
        program = r'''
import json, os, subprocess, sys, time
from pathlib import Path
sys.stdin.readline()
child = subprocess.Popen([sys.executable, "-I", "-c", "import time; time.sleep(45)"],
    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
Path(sys.argv[1]).write_text(json.dumps([os.getpid(), child.pid]), encoding="utf-8")
time.sleep(45)
'''
        with self.assertRaisesRegex(ValueError, "timed out"):
            helper.probe_acp([sys.executable, "-I", "-c", program, str(pids_path)], self.root, helper.safe_env(), timeout=1.5)
        pids = json.loads(pids_path.read_text(encoding="utf-8"))
        test_core.wait_for(lambda: all(not test_core.process_alive(pid) for pid in pids), seconds=5)

    def test_acp_malformed_json_values_fail_as_controlled_protocol_errors(self):
        for value in ("null", "[]"):
            with self.subTest(value=value):
                program = "import sys; sys.stdin.readline(); print(" + repr(value) + ", flush=True)"
                with self.assertRaises(ValueError):
                    helper.probe_acp([sys.executable, "-I", "-c", program], self.root, helper.safe_env(), timeout=3)

    def test_acp_malformed_initialization_is_not_reported_as_a_capability_success(self):
        for result in ({"protocolVersion": True}, {"protocolVersion": 2},
                       {"protocolVersion": 1, "authMethods": None}):
            with self.subTest(result=result):
                response = json.dumps({"jsonrpc": "2.0", "id": 1, "result": result})
                program = "import sys; sys.stdin.readline(); print(" + repr(response) + ", flush=True)"
                with self.assertRaises(ValueError):
                    helper.probe_acp([sys.executable, "-I", "-c", program], self.root, helper.safe_env(), timeout=3)


if __name__ == "__main__":
    unittest.main()
