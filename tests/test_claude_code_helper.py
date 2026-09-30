"""Offline Claude Code discovery/isolation tests; no provider is contacted."""
from contextlib import redirect_stdout
import base64
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

    def native_packet(self, images=None, text="FixtureAgent: Please inspect this supplied image. Thank you. π 🖤"):
        if images is None:
            images = [("image/png", base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9ZFY4AAAAASUVORK5CYII="))]
        content = [{"type": "text", "text": text}]
        content.extend({"type": "image", "source": {"type": "base64", "media_type": media,
                       "data": base64.b64encode(data).decode("ascii")}} for media, data in images)
        return {"type": "user", "message": {"role": "user", "content": content},
                "parent_tool_use_id": None}

    def native_bytes(self, value=None):
        return (json.dumps(value if value is not None else self.native_packet(),
                           ensure_ascii=False, separators=(", ", ": ")) + "\n").encode("utf-8")

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

    def test_catalog_excludes_fable_family_versions_and_resolved_aliases(self):
        payload = self.payload()
        ids = ("fable", "fable[1m]", "claude-fable-future", "CLAUDE-FABLE-99[1m]")
        payload["models"].extend({"value": ident, "displayName": "Fixture"} for ident in ids)
        payload["models"].append({"value": "top", "displayName": "Top", "resolvedModel": "claude-fable-future"})
        excluded = []
        models = helper.normalize_catalog(payload, excluded)
        self.assertEqual({entry["id"] for entry in models}, {"opus", "simple"})
        self.assertEqual({entry["id"] for entry in excluded}, {*ids, "top"})
        self.assertTrue(all("usage credits" in entry["reason"] for entry in excluded))

    def test_best_alias_requires_concrete_non_fable_resolution(self):
        for resolved in (None, "best", "opus", "claude-best", "claude-fable-future"):
            payload = self.payload()
            entry = {"value": "best[1m]", "displayName": "Best"}
            if resolved is not None:
                entry["resolvedModel"] = resolved
            payload["models"].append(entry)
            with self.subTest(resolved=resolved):
                self.assertNotIn("best[1m]", {model["id"] for model in helper.normalize_catalog(payload)})
        payload["models"][-1]["resolvedModel"] = "claude-opus-future"
        self.assertIn("best[1m]", {model["id"] for model in helper.normalize_catalog(payload)})

    def test_explicit_credit_requirement_and_indirect_alias_are_excluded(self):
        payload = self.payload()
        payload["models"] += [
            {"value": "credit-tier", "displayName": "Future model", "description": "Requires usage credits"},
            {"value": "indirect", "displayName": "Indirect", "resolvedModel": "credit-tier"},
            {"value": "chain", "displayName": "Chain", "resolvedModel": "indirect"},
        ]
        excluded = []
        models = helper.normalize_catalog(payload, excluded)
        self.assertEqual({entry["id"] for entry in models}, {"opus", "simple"})
        self.assertEqual({entry["id"] for entry in excluded}, {"credit-tier", "indirect", "chain"})

    def test_fable_comparison_is_not_a_family_identity_or_new_version_gate(self):
        payload = {"models": [{"value": "claude-opus-future", "displayName": "Opus future",
                               "description": "Compared with Fable in a benchmark", "futureField": True}]}
        self.assertEqual(helper.normalize_catalog(payload)[0]["id"], "claude-opus-future")

    def test_all_excluded_catalog_fails_before_selection(self):
        with self.assertRaisesRegex(ValueError, "no-extra-charges"):
            helper.normalize_catalog({"models": [{"value": "fable", "displayName": "Fable"}]})

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

    def test_native_input_command_preserves_all_isolation_settings(self):
        native = helper.review_command(self.exe, self.mcp, "opus", "max", "stream-json")
        self.assertEqual(native[native.index("--input-format") + 1], "stream-json")
        native_without_input = native.copy()
        index = native_without_input.index("--input-format")
        del native_without_input[index:index + 2]
        self.assertEqual(native_without_input, helper.review_command(self.exe, self.mcp, "opus", "max"))
        self.assertEqual(native[native.index("--tools") + 1], "")
        self.assertIn("--no-session-persistence", native)
        self.assertIn("--strict-mcp-config", native)
        self.assertNotIn("--add-dir", native)
        self.assertIn("supplied image blocks", helper.SYSTEM_PROMPT)

    def test_native_image_blocks_accept_unicode_and_hash_images_in_order(self):
        # These intentionally test signatures, not complete image decoding.
        images = [("image/png", b"\x89PNG\r\n\x1a\nfixture"),
                  ("image/jpeg", b"\xff\xd8\xfffixture"),
                  ("image/gif", b"GIF87afixture"), ("image/gif", b"GIF89afixture"),
                  ("image/webp", b"RIFF\x10\x00\x00\x00WEBPfixture")]
        packet = self.native_bytes(self.native_packet(images))
        self.assertIn("π 🖤".encode("utf-8"), packet)
        self.assertEqual(helper.validate_input_packet(packet, "stream-json"),
                         [helper.sha256(data) for _, data in images])
        self.assertEqual(helper.validate_input_packet(packet[:-1] + b"\r\n", "stream-json"),
                         [helper.sha256(data) for _, data in images])
        self.assertEqual(helper.validate_input_packet(b"plain UTF-8 packet \xcf\x80", "text"), [])

    def test_native_packet_rejects_extra_frames_duplicates_and_wrong_roles(self):
        packet = self.native_bytes()
        invalid_bytes = [packet + packet, packet + b"\n", packet.rstrip(b"\n"),
                         json.dumps(self.native_packet(), indent=2).encode() + b"\n",
                         packet.replace(b'"type": "user"', b'"type": "user", "type": "user"', 1),
                         b"\xff\n"]
        for invalid in invalid_bytes:
            with self.subTest(invalid=invalid[:40]), self.assertRaises(ValueError):
                helper.validate_input_packet(invalid, "stream-json")
        for level, key, value in (("frame", "type", "control_request"),
                                  ("frame", "parent_tool_use_id", "existing-tool"),
                                  ("frame", "session_id", "unapproved-session"),
                                  ("message", "role", "assistant"),
                                  ("message", "tool_use", {})):
            frame = self.native_packet()
            target = frame if level == "frame" else frame["message"]
            target[key] = value
            with self.subTest(level=level, key=key), self.assertRaises(ValueError):
                helper.validate_input_packet(self.native_bytes(frame), "stream-json")

    def test_native_packet_rejects_tools_urls_documents_and_file_references(self):
        image = self.native_packet()["message"]["content"][1]
        invalid_blocks = [
            {"type": "tool_use", "id": "tool", "name": "Read", "input": {"file_path": "private"}},
            {"type": "tool_result", "tool_use_id": "tool", "content": "private"},
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": "JVBERg=="}},
            {"type": "image", "source": {"type": "url", "url": "https://example.invalid/private"}},
            {"type": "image", "source": {"type": "file", "file_id": "private"}},
            {**image, "file_path": "private"},
            {"type": "text", "text": "look", "file_path": "private"},
            {"type": "image", "source": {**image["source"], "url": "https://example.invalid/private"}},
            {"type": "image", "source": {**image["source"], "media_type": "application/pdf"}},
        ]
        for block in invalid_blocks:
            frame = self.native_packet()
            frame["message"]["content"][1] = block
            with self.subTest(type=block["type"], keys=sorted(block)), self.assertRaises(ValueError):
                helper.validate_input_packet(self.native_bytes(frame), "stream-json")

    def test_native_packet_requires_text_and_image_and_valid_unicode(self):
        for content in ([], [{"type": "text", "text": "Text alone"}],
                        self.native_packet()["message"]["content"][1:],
                        [{"type": "text", "text": " \n"}],
                        [{"type": "text", "text": "\ud800"}]):
            frame = self.native_packet()
            frame["message"]["content"] = content
            with self.subTest(content=repr(content)[:60]), self.assertRaises(ValueError):
                helper.validate_input_packet((json.dumps(frame) + "\n").encode(), "stream-json")

    def test_native_image_rejects_malformed_noncanonical_and_mismatched_base64(self):
        # /x== decodes with ignored nonzero padding bits; canonical form is /w==.
        for data in ("", "%%%%", "\u00e9", "AA=", "/x==", "aGVsbG8=\n",
                     "iVBORw0KGgo=ignored", base64.b64encode(b"ordinary file bytes").decode()):
            frame = self.native_packet()
            frame["message"]["content"][1]["source"]["data"] = data
            with self.subTest(data=data), self.assertRaises(ValueError):
                helper.validate_input_packet(self.native_bytes(frame), "stream-json")
        frame = self.native_packet()
        frame["message"]["content"][1]["source"]["media_type"] = "image/jpeg"
        with self.assertRaisesRegex(ValueError, "signature"):
            helper.validate_input_packet(self.native_bytes(frame), "stream-json")

    def test_native_packet_enforces_encoded_decoded_and_count_limits(self):
        with self.assertRaisesRegex(ValueError, "bounded input size"):
            helper.validate_input_packet(b"x" * (8 * 1024 * 1024 + 1), "stream-json")
        with self.assertRaisesRegex(ValueError, "bounded input size"):
            helper.validate_input_packet(b"x" * (4 * 1024 * 1024 + 1), "text")
        oversized = b"\x89PNG\r\n\x1a\n" + b"x" * (5 * 1024 * 1024 - 7)
        with self.assertRaisesRegex(ValueError, "bounded"):
            helper.validate_input_packet(self.native_bytes(self.native_packet([("image/png", oversized)])),
                                         "stream-json")
        images = [("image/png", b"\x89PNG\r\n\x1a\nfixture")] * 17
        with self.assertRaisesRegex(ValueError, "image count"):
            helper.validate_input_packet(self.native_bytes(self.native_packet(images)), "stream-json")
        self.assertEqual(len(helper.validate_input_packet(self.native_bytes(self.native_packet(images[:16])),
                                                        "stream-json")), 16)

    def test_native_dry_run_validates_without_auth_discovery_or_child_execution(self):
        packet = self.root / "request.jsonl"
        packet.write_bytes(self.native_bytes())
        output = self.root / "native-dry-run"
        argv = ["helper", "--config", str(self.config_file), "--prompt-file", str(packet),
                "--output-dir", str(output), "--model", "opus", "--effort", "max",
                "--input-format", "stream-json", "--dry-run"]
        captured = io.StringIO()
        with patch.object(sys, "argv", argv), patch.object(helper, "discover_in_workspace") as discover, \
                patch.object(helper, "run_child") as child, redirect_stdout(captured):
            self.assertEqual(helper.main(), 0)
        discover.assert_not_called()
        child.assert_not_called()
        self.assertFalse(output.exists())
        metadata = json.loads(captured.getvalue())
        self.assertFalse(metadata["sent"])
        self.assertFalse(metadata["discovery_executed"])
        self.assertEqual(metadata["input_format"], "stream-json")
        self.assertEqual(metadata["input_transport"], "claude_content_blocks")
        self.assertEqual(metadata["request_sha256"], helper.sha256(packet.read_bytes()))
        packet.write_bytes(packet.read_bytes() + packet.read_bytes())
        with patch.object(sys, "argv", argv), patch.object(helper, "discover_in_workspace") as discover, \
                patch.object(helper, "run_child") as child, self.assertRaises(SystemExit) as caught:
            helper.main()
        self.assertEqual(caught.exception.code, 2)
        discover.assert_not_called()
        child.assert_not_called()

    def test_native_review_delivers_exact_bytes_and_records_decoded_image_hashes(self):
        packet = self.root / "request.jsonl"
        raw = self.native_bytes()[:-1] + b"\r\n"
        packet.write_bytes(raw)
        output = self.root / "native-review"
        argv = ["helper", "--config", str(self.config_file), "--prompt-file", str(packet),
                "--output-dir", str(output), "--model", "opus", "--effort", "max",
                "--input-format", "stream-json"]
        response = {"type": "result", "subtype": "success", "is_error": False, "result": "Fixture image review"}
        result = {"stdout": json.dumps(response).encode(), "stderr": b"", "returncode": 0,
                  "timed_out": False, "runtime_seconds": 0.01}
        with patch.object(sys, "argv", argv), \
                patch.object(helper, "discover_in_workspace", return_value=self.catalog()) as discover, \
                patch.object(helper, "run_child", return_value=result) as child, redirect_stdout(io.StringIO()):
            self.assertEqual(helper.main(), 0)
        discover.assert_called_once()
        child.assert_called_once()
        command, cwd, env, timeout, stdin = child.call_args.args
        self.assertEqual(stdin, raw)
        self.assertEqual(command[command.index("--input-format") + 1], "stream-json")
        self.assertEqual(command[command.index("--tools") + 1], "")
        self.assertEqual((output / "prompt.txt").read_bytes(), raw)
        self.assertEqual((output / "request.txt").read_bytes(), raw)
        metadata = json.loads((output / "metadata.json").read_text())
        self.assertEqual(metadata["status"], "completed")
        self.assertEqual(metadata["request_sha256"], helper.sha256(raw))
        self.assertEqual(metadata["input_image_sha256s"], helper.validate_input_packet(raw, "stream-json"))
        self.assertEqual(metadata["input_transport"], "claude_content_blocks")
        self.assertFalse(metadata["isolation"]["session_persistence"])
        self.assertEqual(metadata["isolation"]["tools"], [])

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

    def test_metadata_accepts_catalog_push_before_matching_initialize_only(self):
        event = {"type": "system", "subtype": "commands_changed", "uuid": "fixture-event",
                 "session_id": "fixture-session", "commands": [
                     {"name": "fixture", "description": "private-catalog-never-retain",
                      "argumentHint": "", "aliases": ["fixture-alias"], "builtin": True}]}
        script = (
            "import sys,json; frame=json.loads(sys.stdin.readline()); "
            "assert frame['type']=='control_request'; assert frame['request']['subtype']=='initialize'; "
            f"print({json.dumps(json.dumps(event))},flush=True); "
            "print(json.dumps({'type':'system','subtype':'init','tools':[],'mcp_servers':[]}),flush=True); "
            "print(json.dumps({'type':'control_response','response':{'subtype':'success',"
            "'request_id':frame['request_id'],'response':{'models':[]}}}),flush=True); "
            "rest=sys.stdin.read(); assert not rest"
        )
        captured = io.StringIO()
        with redirect_stdout(captured):
            payload = helper.initialize_metadata([sys.executable, "-c", script], self.root,
                                                 helper.clean_environment(), timeout=5)
        self.assertEqual(payload, {"models": []})
        self.assertEqual(captured.getvalue(), "")
        self.assertNotIn("private-catalog", json.dumps(payload))

    def test_metadata_catalog_shape_validation_accepts_empty_catalog(self):
        helper.validate_commands_changed({"commands": [], "uuid": "event", "session_id": "session"})

    def test_metadata_rejects_malformed_catalog_without_echoing_payload(self):
        base = {"type": "system", "subtype": "commands_changed", "uuid": "event",
                "session_id": "session", "commands": []}
        invalid = [None, {}, [None], [{"name": "sensitive-never-echo"}],
                   [{"name": "n", "description": "d", "argumentHint": "", "aliases": "bad"}],
                   [{"name": "n", "description": "d", "argumentHint": "", "builtin": 1}]]
        for commands in invalid:
            with self.subTest(commands=commands):
                event = {**base, "commands": commands}
                script = f"import sys; sys.stdin.readline(); print({json.dumps(json.dumps(event))},flush=True)"
                with self.assertRaisesRegex(ValueError, "catalog metadata") as caught:
                    helper.initialize_metadata([sys.executable, "-c", script], self.root,
                                               helper.clean_environment(), timeout=5)
                self.assertNotIn("sensitive-never-echo", str(caught.exception))
        for field in ("uuid", "session_id"):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "catalog metadata"):
                helper.validate_commands_changed({**base, field: None})

    def test_metadata_catalog_push_does_not_allow_tools_or_other_activity(self):
        push = {"type": "system", "subtype": "commands_changed", "uuid": "event",
                "session_id": "session", "commands": []}
        for field in ("tools", "mcp_servers"):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "unexpected tools"):
                helper.validate_commands_changed({**push, field: ["unexpected"]})
            event = {"type": "system", "subtype": "init", field: ["unexpected"]}
            script = ("import sys; sys.stdin.readline(); "
                      f"print({json.dumps(json.dumps(push))},flush=True); "
                      f"print({json.dumps(json.dumps(event))},flush=True)")
            with self.subTest(init_field=field), self.assertRaisesRegex(ValueError, "unexpected tools"):
                helper.initialize_metadata([sys.executable, "-c", script], self.root,
                                           helper.clean_environment(), timeout=5)
        activity = [{"type": "assistant", "message": "no"},
                    {"type": "tool", "content": "no"},
                    {"type": "control_request", "request": {"subtype": "can_use_tool"}},
                    {"type": "system", "subtype": "task_started"},
                    {"type": "system", "subtype": "future_event"}]
        for event in activity:
            with self.subTest(event=event):
                script = ("import sys; sys.stdin.readline(); "
                          f"print({json.dumps(json.dumps(push))},flush=True); "
                          f"print({json.dumps(json.dumps(event))},flush=True)")
                with self.assertRaisesRegex(ValueError, "non-metadata"):
                    helper.initialize_metadata([sys.executable, "-c", script], self.root,
                                               helper.clean_environment(), timeout=5)

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
        payload["models"].append({"value": "fable", "displayName": "Fable",
                                  "description": "private-description-never-retain"})
        checks = {"runtime_version": "future", "runtime_provenance": {"sha256": "fixture"},
                  "auth": {"loggedIn": True, "authMethod": "claude.ai"}}
        with patch.object(helper, "runtime_preflight", return_value=checks), patch.object(helper, "initialize_metadata", return_value=payload), patch.object(helper, "check_runtime_update", return_value={"status": "unavailable"}):
            catalog = helper.discover_in_workspace({"exe": str(self.exe)}, self.root, {}, self.mcp)
        text = json.dumps(catalog)
        self.assertNotIn("private@example", text)
        self.assertNotIn("private-org", text)
        self.assertNotIn("private-description", text)
        self.assertIsInstance(catalog["evidence"], str)
        self.assertFalse(catalog["discovery_details"]["user_prompt_sent"])
        self.assertEqual(catalog["discovery_details"]["excluded_models"][0]["id"], "fable")
        self.assertIn("Excluded 1", catalog["evidence"])

    def test_result_metadata_does_not_claim_backend_attestation(self):
        text, receipt = helper.capture_response({"type": "result", "subtype": "success", "is_error": False,
                                                "result": "Fixture answer", "modelUsage": {"future-model": {}}}, 0)
        self.assertEqual(text, "Fixture answer")
        self.assertEqual(receipt["verified_response_models"], [])
        self.assertEqual(receipt["observed_cli_models"], ["future-model"])

    def invoke_response_fixture(self, response, *, returncode=1, timed_out=False):
        packet = self.root / "failure-packet.txt"
        packet.write_text("Synthetic fixture only", encoding="utf-8")
        output = self.root / ("response-fixture-" + str(len(list(self.root.iterdir()))))
        argv = ["helper", "--config", str(self.config_file), "--prompt-file", str(packet),
                "--output-dir", str(output), "--model", "opus", "--effort", "max"]
        stdout = response if isinstance(response, bytes) else json.dumps(response).encode("utf-8")
        fixture = {"stdout": stdout, "stderr": b"private-diagnostic-never-save",
                   "returncode": returncode, "timed_out": timed_out, "runtime_seconds": 0.01}
        with patch.object(sys, "argv", argv), \
                patch.object(helper, "discover_in_workspace", return_value=self.catalog()), \
                patch.object(helper, "run_child", return_value=fixture) as child, redirect_stdout(io.StringIO()):
            exit_code = helper.main()
        self.assertEqual(child.call_count, 1)
        self.assertNotIn("--resume", child.call_args.args[0])
        self.assertNotIn("--continue", child.call_args.args[0])
        metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
        self.assertFalse(metadata["automatic_retry_attempted"])
        return output, metadata, exit_code

    def test_limit_results_preserve_exact_partial_without_becoming_final(self):
        text = "Partial fixture π 🖤\r\nPreserve these trailing spaces  "
        fixtures = [
            ({"subtype": "error_max_turns", "terminal_reason": "max_turns"}, "tool_limit"),
            ({"subtype": "error_max_budget_usd", "terminal_reason": "budget_exhausted"}, "budget_limit"),
            ({"stop_reason": "max_tokens"}, "output_limit"),
            ({"stop_reason": "model_context_window_exceeded"}, "output_limit"),
            ({"stop_reason": "pause_turn"}, "incomplete"),
            ({"terminal_reason": "aborted_streaming"}, "incomplete"),
            ({"terminal_reason": "aborted_tools"}, "incomplete"),
            ({"terminal_reason": "tool_deferred"}, "incomplete"),
            ({"terminal_reason": "hook_stopped"}, "incomplete"),
            ({"terminal_reason": "stop_hook_prevented"}, "incomplete"),
            ({"terminal_reason": "background_requested"}, "incomplete"),
            ({"stop_reason": "tool_deferred"}, "incomplete"),
        ]
        for change, expected in fixtures:
            response = {"type": "result", "subtype": "success", "is_error": False,
                        "result": text, "num_turns": 2, **change}
            if response["subtype"] != "success":
                response["is_error"] = True
                response["errors"] = ["private-error-code-never-save"]
            with self.subTest(change=change):
                output, metadata, exit_code = self.invoke_response_fixture(response)
                self.assertEqual(exit_code, 1)
                self.assertEqual(metadata["status"], "response_received_incomplete")
                self.assertTrue(metadata["response_received"])
                self.assertEqual(metadata["completion_reason"], expected)
                self.assertFalse(metadata["model_review_completed"])
                self.assertTrue(metadata["partial_answer_available"])
                self.assertEqual((output / "partial_result.txt").read_bytes(), text.encode("utf-8"))
                self.assertEqual(metadata["partial_answer_sha256"], helper.sha256(text.encode("utf-8")))
                self.assertFalse((output / "result.txt").exists())
                self.assertFalse((output / "response.raw.json").exists())
                combined = b"".join(path.read_bytes() for path in output.iterdir())
                self.assertNotIn(b"private-error-code-never-save", combined)
                self.assertNotIn(b"private-diagnostic-never-save", combined)

    def test_error_terminal_result_without_text_is_received_but_not_a_partial_answer(self):
        for subtype in ("error_max_turns", "error_max_budget_usd", "error_during_execution",
                        "error_max_structured_output_retries"):
            response = {"type": "result", "subtype": subtype, "is_error": True,
                        "errors": ["private-auth-code-never-save"], "stop_reason": "end_turn"}
            with self.subTest(subtype=subtype):
                output, metadata, exit_code = self.invoke_response_fixture(response)
                self.assertEqual(exit_code, 1)
                self.assertEqual(metadata["status"], "response_received_incomplete")
                self.assertTrue(metadata["response_received"])
                self.assertFalse(metadata["partial_answer_available"])
                self.assertNotIn("partial_answer_sha256", metadata)
                self.assertFalse((output / "partial_result.txt").exists())
                self.assertNotIn("private-auth", json.dumps(metadata))

    def test_terminal_provider_errors_are_classified_without_retaining_error_text(self):
        for terminal in ("blocking_limit", "rapid_refill_breaker", "prompt_too_long", "image_error",
                         "model_error", "api_error", "malformed_tool_use_exhausted",
                         "structured_output_retry_exhausted", "tool_deferred_unavailable", "turn_setup_failed"):
            with self.subTest(terminal=terminal):
                response = {"type": "result", "subtype": "error_during_execution", "is_error": True,
                            "result": "private-error-content", "terminal_reason": terminal,
                            "errors": ["private-error-content"]}
                output, metadata, exit_code = self.invoke_response_fixture(response)
                self.assertEqual(exit_code, 1)
                self.assertEqual(metadata["completion_reason"], "provider_error")
                self.assertEqual(metadata["response_terminal_reason"], terminal)
                self.assertTrue(metadata["response_received"])
                self.assertFalse(metadata["partial_answer_available"])
                self.assertFalse((output / "partial_result.txt").exists())
                self.assertNotIn("private-error-content", json.dumps(metadata))

    def test_success_shaped_error_and_permission_denial_are_not_completed(self):
        base = {"type": "result", "subtype": "success", "is_error": False,
                "result": "Text that must not become a final answer", "stop_reason": "end_turn"}
        for key in ("errors", "permission_denials"):
            for value in ([{"secret": "private-tool-input"}], "private-error-text", {}, None, False):
                response = {**base, key: value}
                with self.subTest(key=key, value=value):
                    with self.assertRaises(ValueError):
                        helper.capture_response(response, 0)
                    output, metadata, exit_code = self.invoke_response_fixture(response, returncode=0)
                    self.assertEqual(exit_code, 1)
                    self.assertEqual(metadata["completion_reason"], "provider_error")
                    self.assertTrue(metadata["response_received"])
                    self.assertFalse(metadata["model_review_completed"])
                    self.assertFalse(metadata["partial_answer_available"])
                    self.assertFalse((output / "result.txt").exists())
                    self.assertFalse((output / "partial_result.txt").exists())
                    self.assertNotIn("private-", json.dumps(metadata))
        text, receipt = helper.capture_response({**base, "errors": [], "permission_denials": []}, 0)
        self.assertTrue(receipt["model_review_completed"])
        self.assertEqual(text, base["result"])

    def test_provider_errors_override_stale_model_stops_without_preserving_diagnostics(self):
        base = {"type": "result", "subtype": "success", "is_error": False,
                "result": "private-diagnostic-result-never-save"}
        contradictions = [
            {"subtype": "error_during_execution", "is_error": True},
            {"subtype": "error_max_structured_output_retries", "is_error": True},
            {"is_error": True},
            {"permission_denials": [{"tool_input": "private-input"}]},
            {"errors": ["private-provider-error"]},
            {"terminal_reason": "prompt_too_long"},
            {"terminal_reason": "api_error"},
        ]
        for change in contradictions:
            for stop in ("max_tokens", "pause_turn"):
                with self.subTest(change=change, stop=stop):
                    output, metadata, exit_code = self.invoke_response_fixture(
                        {**base, "stop_reason": stop, **change})
                    self.assertEqual(exit_code, 1)
                    self.assertEqual(metadata["completion_reason"], "provider_error")
                    self.assertTrue(metadata["response_received"])
                    self.assertFalse(metadata["model_review_completed"])
                    self.assertFalse(metadata["partial_answer_available"])
                    self.assertFalse((output / "partial_result.txt").exists())
                    self.assertFalse((output / "result.txt").exists())
                    self.assertNotIn(b"private-", b"".join(path.read_bytes() for path in output.iterdir()))

    def test_unrecognized_or_malformed_envelope_does_not_claim_response_delivery(self):
        base = {"type": "result", "subtype": "success", "is_error": False, "result": "Fixture"}
        fixtures = [b"private-malformed-json", [], {"type": "assistant", "text": "Fixture"},
                    {key: value for key, value in base.items() if key != "result"},
                    {**base, "subtype": "unknown_future_subtype"}, {**base, "subtype": []},
                    {**base, "is_error": "false"}, {**base, "result": None},
                    {**base, "stop_reason": {}}, {**base, "terminal_reason": []}]
        for response in fixtures:
            with self.subTest(response=response):
                output, metadata, exit_code = self.invoke_response_fixture(response)
                self.assertEqual(exit_code, 1)
                self.assertEqual(metadata["status"], "delivery_unknown")
                self.assertFalse(metadata["response_received"])
                self.assertFalse(metadata["partial_answer_available"])
                self.assertFalse((output / "partial_result.txt").exists())
                self.assertFalse((output / "response.raw.json").exists())

    def test_unknown_stop_reason_is_sanitized_and_does_not_preserve_untrusted_text(self):
        response = {"type": "result", "subtype": "success", "is_error": False,
                    "result": "Unverified text", "stop_reason": "private-token-stop-reason",
                    "terminal_reason": "private-token-terminal-reason"}
        output, metadata, _ = self.invoke_response_fixture(response)
        self.assertEqual(metadata["response_stop_reason"], "unknown")
        self.assertEqual(metadata["response_terminal_reason"], "unknown")
        self.assertEqual(metadata["completion_reason"], "unknown")
        self.assertTrue(metadata["response_received"])
        self.assertFalse(metadata["partial_answer_available"])
        self.assertNotIn("private-token", json.dumps(metadata))

    def test_partial_size_bound_uses_exact_utf8_bytes_without_truncation(self):
        response = {"type": "result", "subtype": "success", "is_error": False,
                    "result": "π" * (helper.MAX_PARTIAL_ANSWER_BYTES // 2), "stop_reason": "max_tokens"}
        output, metadata, _ = self.invoke_response_fixture(response)
        self.assertEqual((output / "partial_result.txt").stat().st_size, helper.MAX_PARTIAL_ANSWER_BYTES)
        self.assertTrue(metadata["partial_answer_available"])
        for text in (response["result"] + "x", "\ud800", " \n"):
            with self.subTest(size=len(text)):
                output, metadata, _ = self.invoke_response_fixture({**response, "result": text})
                self.assertFalse(metadata["partial_answer_available"])
                self.assertFalse((output / "partial_result.txt").exists())

    def test_timeout_does_not_parse_partial_or_success_shaped_stdout(self):
        for response in ({"type": "result", "subtype": "success", "is_error": False,
                          "result": "Fixture should not imply completion", "stop_reason": "end_turn"},
                         {"type": "result", "subtype": "error_max_turns", "is_error": True,
                          "result": "Fixture partial"}, b'{"type":"result","result":"truncated'):
            with self.subTest(response=response):
                output, metadata, exit_code = self.invoke_response_fixture(response, timed_out=True)
                self.assertEqual(exit_code, 1)
                self.assertEqual(metadata["status"], "timeout")
                self.assertFalse(metadata["response_received"])
                self.assertFalse(metadata["partial_answer_available"])
                self.assertFalse((output / "partial_result.txt").exists())
                self.assertFalse((output / "result.txt").exists())

    def test_child_failure_without_response_keeps_delivery_unknown(self):
        packet = self.root / "exception-packet.txt"
        packet.write_text("Synthetic fixture only", encoding="utf-8")
        output = self.root / "exception-output"
        argv = ["helper", "--config", str(self.config_file), "--prompt-file", str(packet),
                "--output-dir", str(output), "--model", "opus", "--effort", "max"]
        with patch.object(sys, "argv", argv), \
                patch.object(helper, "discover_in_workspace", return_value=self.catalog()), \
                patch.object(helper, "run_child", side_effect=OSError("private-child-error")) as child, \
                redirect_stdout(io.StringIO()):
            self.assertEqual(helper.main(), 1)
        self.assertEqual(child.call_count, 1)
        metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["status"], "delivery_unknown")
        self.assertFalse(metadata["response_received"])
        self.assertNotIn("private-child-error", json.dumps(metadata))

    def test_artifact_write_failure_keeps_received_receipt_without_claiming_partial_file(self):
        write_bytes = Path.write_bytes

        def fail_partial(path, data):
            if path.name == "partial_result.txt":
                raise OSError("private-filesystem-error")
            return write_bytes(path, data)

        response = {"type": "result", "subtype": "error_max_turns", "is_error": True,
                    "result": "Fixture partial"}
        with patch.object(Path, "write_bytes", fail_partial):
            output, metadata, exit_code = self.invoke_response_fixture(response)
        self.assertEqual(exit_code, 1)
        self.assertTrue(metadata["response_received"])
        self.assertEqual(metadata["status"], "response_received_incomplete")
        self.assertFalse(metadata["partial_answer_available"])
        self.assertNotIn("partial_answer_sha256", metadata)
        self.assertFalse((output / "partial_result.txt").exists())
        self.assertNotIn("private-filesystem-error", json.dumps(metadata))

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

    def test_direct_review_cannot_bypass_filtered_catalog_with_fable_model(self):
        packet = self.root / "packet.txt"
        packet.write_text("Synthetic packet", encoding="utf-8")
        output = self.root / "excluded-model-out"
        argv = ["helper", "--config", str(self.config_file), "--prompt-file", str(packet),
                "--output-dir", str(output), "--model", "fable", "--effort", "max"]
        with patch.object(sys, "argv", argv), patch.object(helper, "discover_in_workspace", return_value=self.catalog()), patch.object(helper, "run_child") as child, redirect_stdout(io.StringIO()):
            self.assertEqual(helper.main(), 1)
        child.assert_not_called()
        metadata = json.loads((output / "metadata.json").read_text())
        self.assertFalse(metadata["submission_attempted"])
        self.assertFalse(metadata["sent"])


if __name__ == "__main__":
    unittest.main()
