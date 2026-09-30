"""Native image dispatch contracts using synthetic bytes and offline helpers.

No provider executable, account, network, or live Hub state is used. The helper
records only the exact prepared frame; it does not claim visual interpretation.
"""
from __future__ import annotations

import base64
import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import test_core
import test_attachments
from coda_review_hub import attachments, capabilities


# Reuse the standard offline helper's discovery and sanitized environment. The
# added parser models the native frame receipt without calling a provider.
NATIVE_HELPER = test_core.FAKE_HELPER.replace(
    "import argparse, json, os", "import argparse, base64, hashlib, json, os"
).replace(
    "    args = parser.parse_args()",
    '    parser.add_argument("--input-format", default="text")\n'
    "    args = parser.parse_args()",
).replace(
    '    packet = Path(args.prompt_file).read_text(encoding="utf-8")',
    '    packet_bytes = Path(args.prompt_file).read_bytes()\n'
    '    packet = packet_bytes.decode("utf-8")',
).replace(
    '    (output / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")',
    r'''
    if args.input_format == "stream-json":
        frames = [json.loads(line) for line in packet.splitlines() if line.strip()]
        assert len(frames) == 1
        frame = frames[0]
        assert frame["type"] == "user" and frame["message"]["role"] == "user"
        blocks = frame["message"]["content"]
        assert isinstance(blocks, list) and blocks
        assert all(block["type"] in {"text", "image"} for block in blocks)
        images = []
        for block in blocks:
            if block["type"] == "image":
                source = block["source"]
                assert source["type"] == "base64" and "url" not in source
                raw = base64.b64decode(source["data"], validate=True)
                images.append(hashlib.sha256(raw).hexdigest())
        metadata.update(request_sha256=hashlib.sha256(packet_bytes).hexdigest(),
                        input_format=args.input_format,
                        input_transport="claude_content_blocks",
                        input_image_sha256s=images)
        for field in ("request_sha256", "input_format", "input_transport", "input_image_sha256s"):
            if "MODE:MISSING:" + field in packet:
                metadata.pop(field)
            elif "MODE:MISMATCH:" + field in packet:
                metadata[field] = ["0" * 64] if field == "input_image_sha256s" else "wrong"
        if "MODE:REVERSE_IMAGES" in packet:
            metadata["input_image_sha256s"] = list(reversed(images))
        metadata["fixture_api_environment_keys"] = sorted(key for key in os.environ
            if key in {"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY",
                       "XAI_API_KEY", "ANTHROPIC_BASE_URL"})
        (output / "fixture-input.json").write_text(json.dumps({
            "input_format": args.input_format, "images": images,
            "block_types": [block["type"] for block in blocks],
            "request_sha256": hashlib.sha256(packet_bytes).hexdigest(),
        }), encoding="utf-8")
    (output / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
''',
)


class NativeAttachmentTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_core.HubTests("test_fresh_observation_and_exact_packet_bytes")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.hub, self.project = self.fixture.hub, self.fixture.project
        self.fixture.fake.write_bytes(NATIVE_HELPER.encode("utf-8"))
        for value in self.fixture.pins.values():
            value["sha256"] = test_core.core.digest(self.fixture.fake.read_bytes())
        self.fixture.write_pins()
        self.picture = self.project / "pixel.png"
        self.picture.write_bytes(test_attachments.PNG)
        self.source = self.project / "source.py"
        self.source.write_bytes(b"def answer():\r\n    return 42\r\n")

    def submit(self, files, key="native-one", provider="claude-code", prompt="Review the exact synthetic files."):
        return self.hub.submit(str(self.project), [{
            "provider": provider, "prompt": prompt, "timeout": 5,
            "attachments": [str(file) for file in files],
        }], key)

    @staticmethod
    def packet(item):
        raw = (Path(item["evidence_directory"]) / "packet.txt").read_bytes()
        frames = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
        if len(frames) != 1:
            raise AssertionError("Native input must contain exactly one JSON user frame")
        return raw, frames[0]

    def test_mixed_source_and_image_preserve_exact_bytes_and_bound_names(self):
        unusual = self.project / "assets @name"
        unusual.mkdir()
        picture = unusual / "pixel 'quoted' @fixture.png"
        picture.write_bytes(test_attachments.PNG)
        source = unusual / "source 'quoted' @fixture.py"
        source_bytes = 'label = "π@example.test"\r\n# </text> is only quoted source\r\n'.encode("utf-8")
        source.write_bytes(source_bytes)
        self.fixture.observe()
        item = self.submit([source, picture])["jobs"][0]
        raw, frame = self.packet(item)
        self.assertEqual(frame["type"], "user")
        self.assertEqual(frame["message"]["role"], "user")
        blocks = frame["message"]["content"]
        images = [block for block in blocks if block["type"] == "image"]
        text = "\n".join(block["text"] for block in blocks if block["type"] == "text")
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0]["source"]["type"], "base64")
        self.assertEqual(images[0]["source"]["media_type"], "image/png")
        self.assertEqual(base64.b64decode(images[0]["source"]["data"], validate=True), test_attachments.PNG)
        start = text.index('{\n  "file_snapshots"')
        decoded, _ = json.JSONDecoder().raw_decode(text[start:])
        self.assertEqual(decoded["file_snapshots"][0]["text"].encode("utf-8"), source_bytes)
        self.assertEqual(decoded["file_snapshots"][0]["project_relative_name"], source.relative_to(self.project).as_posix())
        self.assertEqual(item["attachment_transport"], "claude_content_blocks")
        self.assertEqual(item["input_format"], "stream-json")
        self.assertEqual(item["input_image_sha256s"], [test_core.core.digest(test_attachments.PNG)])
        self.assertEqual(item["packet_sha256"], test_core.core.digest(raw))
        # Provider payload carries relative labels and bytes, never source or
        # state paths. Path punctuation cannot add frames, commands, or tools.
        decoded_raw = raw.decode("utf-8")
        for forbidden in (str(self.fixture.root), str(self.project), str(self.fixture.other_project),
                          str(Path(item["evidence_directory"])), '"tool_use"', '"url"'):
            self.assertNotIn(forbidden, decoded_raw)
            self.assertNotIn(json.dumps(forbidden)[1:-1], decoded_raw)

    def test_false_image_header_and_suffix_mismatch_refuse_before_spending(self):
        observation = self.fixture.observe(jobs=2)
        bad = self.project / "pretend.png"
        bad.write_bytes(b"This is text, not PNG bytes.")
        mismatched = self.project / "wrong.jpg"
        mismatched.write_bytes(test_attachments.PNG)
        for index, file in enumerate((bad, mismatched)):
            with self.subTest(file=file.name), self.assertRaises(ValueError):
                self.submit([file], key=f"invalid-native-{index}")
        self.assertEqual(self.fixture.remaining()[observation["id"]], 2)
        self.assertEqual(self.hub.jobs(str(self.project)), [])
        self.fixture.launch.assert_not_called()

    def test_unsupported_document_and_other_cli_routes_offer_handoff_without_spending(self):
        pdf = self.project / "document.pdf"
        pdf.write_bytes(b"%PDF-1.7\nSynthetic fixture only.\n")
        office = self.project / "document.docx"
        office.write_bytes(b"PK\x03\x04Synthetic fixture only.")
        observations = [self.fixture.observe("claude-code", jobs=2), self.fixture.observe("grok"),
                        self.fixture.observe("antigravity")]
        for index, (provider, file) in enumerate((
            ("claude-code", pdf), ("claude-code", office),
            ("grok", self.picture), ("antigravity", self.picture),
        )):
            with self.subTest(provider=provider, file=file.name), self.assertRaisesRegex(ValueError, "(?i)handoff"):
                self.submit([file], provider=provider, key=f"unsupported-native-{index}")
        remaining = self.fixture.remaining()
        self.assertEqual([remaining[item["id"]] for item in observations], [2, 1, 1])
        self.assertEqual(self.hub.jobs(str(self.project)), [])
        self.fixture.launch.assert_not_called()

    def test_native_image_and_encoded_frame_size_caps_refuse_before_job(self):
        observation = self.fixture.observe(jobs=2)
        too_large = self.project / "too-large.png"
        too_large.write_bytes(test_attachments.PNG + b"\0" * (5 * 1024 * 1024 + 1 - len(test_attachments.PNG)))
        with self.assertRaises(ValueError):
            self.submit([too_large], key="native-file-overflow")
        images = []
        for index in range(2):
            image = self.project / f"encoded-large-{index}.png"
            image.write_bytes(test_attachments.PNG + b"\0" * (3 * 1024 * 1024 - len(test_attachments.PNG)))
            images.append(image)
        with self.assertRaises(ValueError):
            self.submit(images, key="native-encoded-overflow")
        self.assertEqual(self.fixture.remaining()[observation["id"]], 2)
        self.assertEqual(self.hub.jobs(str(self.project)), [])
        self.fixture.launch.assert_not_called()

    def test_native_frame_does_not_expand_quoted_source_text_limit(self):
        observation = self.fixture.observe()
        self.source.write_bytes(b"x" * attachments.MAX_PACKET_BYTES)
        with self.assertRaises(ValueError):
            self.submit([self.source, self.picture])
        self.assertEqual(self.fixture.remaining()[observation["id"]], 1)
        self.fixture.launch.assert_not_called()

    def test_native_transport_cannot_bypass_subscription_observation(self):
        with self.assertRaisesRegex(ValueError, "(?i)subscription"):
            self.submit([self.picture])
        self.assertEqual(self.hub.jobs(str(self.project)), [])
        self.fixture.launch.assert_not_called()

    def test_native_worker_uses_staged_original_and_explicit_transport(self):
        self.fixture.observe()
        batch = self.submit([self.picture, self.source])
        item = batch["jobs"][0]
        original_packet = (Path(item["evidence_directory"]) / "packet.txt").read_bytes()
        self.picture.write_bytes(b"Later local source replacement")
        self.source.write_bytes(b"def answer(): return 999\n")
        checked = self.hub.attachment_files(str(self.project), item["id"])
        self.assertEqual(Path(checked["upload_paths"][0]).read_bytes(), test_attachments.PNG)
        with patch.object(test_core.worker.subprocess, "Popen", wraps=test_core.worker.subprocess.Popen) as spawn:
            finished = self.fixture.execute(batch)[0]
        self.assertEqual(finished["state"], "returned")
        self.assertIs(finished["native_input_receipt_matched"], True)
        self.assertFalse(finished["claims_independently_verified"])
        self.assertNotEqual(finished["attachment_delivery"], "embedded_text_response_received")
        spawn.assert_called_once()
        command = spawn.call_args.args[0]
        self.assertEqual(command[command.index("--input-format") + 1], "stream-json")
        self.assertNotIn(str(self.picture), command)
        self.assertNotIn(str(self.source), command)
        self.assertIs(spawn.call_args.kwargs["shell"], False)
        directory = Path(item["evidence_directory"])
        self.assertEqual((directory / "packet.txt").read_bytes(), original_packet)
        receipt = json.loads((directory / "provider" / "fixture-input.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["images"], [test_core.core.digest(test_attachments.PNG)])
        self.assertEqual(receipt["request_sha256"], item["packet_sha256"])

    def test_missing_or_mismatched_native_receipt_never_returns_or_retries(self):
        for mode in ("MISSING", "MISMATCH"):
            for field in ("request_sha256", "input_format", "input_transport", "input_image_sha256s"):
                with self.subTest(mode=mode, field=field):
                    self.fixture.observe()
                    batch = self.submit([self.picture], key=f"bad-receipt-{mode}-{field}",
                                        prompt=f"Synthetic native review MODE:{mode}:{field}")
                    finished = self.fixture.execute(batch)[0]
                    self.assertNotEqual(finished["state"], "returned")
                    self.assertNotEqual(finished["submission"], "completed_response_received")
                    self.assertIs(finished["contradictory_completion_fields"], True)
                    launches = Path(finished["evidence_directory"]) / "launches.txt"
                    self.assertEqual(len(launches.read_text(encoding="utf-8").splitlines()), 1)
                    test_core.worker.run_job(self.hub, finished["id"])
                    self.assertEqual(len(launches.read_text(encoding="utf-8").splitlines()), 1)

    def test_native_helper_exit_without_receipt_cannot_claim_response_received(self):
        # Model a local parser/startup failure before any receipt exists. Its
        # absence cannot establish either a provider send or a provider reply.
        early_exit = NATIVE_HELPER.replace("    output.mkdir()", "    return 2\n    output.mkdir()")
        self.fixture.fake.write_bytes(early_exit.encode("utf-8"))
        for pin in self.fixture.pins.values():
            pin["sha256"] = test_core.core.digest(self.fixture.fake.read_bytes())
        self.fixture.write_pins()
        self.fixture.observe()
        batch = self.submit([self.picture])
        finished = self.fixture.execute(batch)[0]
        self.assertEqual(finished["state"], "delivery_unknown")
        self.assertEqual(finished["submission"], "attempt_or_completion_uncertain")
        self.assertEqual(finished["helper_exit_code"], 2)
        self.assertEqual(finished["helper_status"], "missing_receipt")
        self.assertIs(finished["native_input_receipt_matched"], False)
        self.assertFalse(finished["contradictory_completion_fields"])
        self.assertFalse((Path(finished["evidence_directory"]) / "provider").exists())

    def test_native_partial_requires_matching_input_receipt_before_answer_exposure(self):
        partial_text = "Synthetic image detail checked.\r\nOne image check remains open."
        partial_helper = NATIVE_HELPER.replace(
            '    (output / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")',
            r'''
    partial = b"Synthetic image detail checked.\r\nOne image check remains open."
    (output / "partial_result.txt").write_bytes(partial)
    metadata.update(status="response_received_incomplete", model_review_completed=False,
        response_received=True, completion_reason="tool_limit",
        response_subtype="error_max_turns", response_terminal_reason="max_turns", response_is_error=True,
        partial_answer_available=True, partial_answer_sha256=hashlib.sha256(partial).hexdigest())
    code = 1
    (output / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
''')
        self.fixture.fake.write_bytes(partial_helper.encode("utf-8"))
        for pin in self.fixture.pins.values():
            pin["sha256"] = test_core.core.digest(self.fixture.fake.read_bytes())
        self.fixture.write_pins()
        for field in (None, "request_sha256", "input_format", "input_transport", "input_image_sha256s"):
            with self.subTest(receipt_field=field):
                self.fixture.observe()
                prompt = "Synthetic image partial." + (f" MODE:MISMATCH:{field}" if field else "")
                batch = self.submit([self.picture], key=f"native-partial-{field}", prompt=prompt)
                job = self.fixture.execute(batch)[0]
                result = self.hub.result(str(self.project), job["id"])
                self.assertEqual(job["state"], "failed")
                self.assertEqual(job["submission"], "response_received_incomplete")
                self.assertTrue(job["response_received"])
                self.assertFalse(job["provider_resume"])
                self.assertIs(job["native_input_receipt_matched"], field is None)
                self.assertIs(job["partial_answer_integrity_error"], field is not None)
                self.assertIs(job["partial_answer_available"], field is None)
                self.assertEqual(result["answer"], partial_text if field is None else "")
                if field is None:
                    self.assertEqual(job["answer_sha256"], test_core.core.digest(partial_text.encode("utf-8")))
                else:
                    self.assertFalse(job["answer_available"])
                    self.assertFalse((Path(job["evidence_directory"]) / "answer.txt").exists())

    def test_native_receipt_binds_image_order_not_just_hash_membership(self):
        gif_bytes = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==")
        gif = self.project / "second.gif"
        gif.write_bytes(gif_bytes)
        self.fixture.observe()
        batch = self.submit([gif, self.source, self.picture], prompt="Synthetic MODE:REVERSE_IMAGES")
        item = batch["jobs"][0]
        _, frame = self.packet(item)
        images = [block for block in frame["message"]["content"] if block["type"] == "image"]
        self.assertEqual([base64.b64decode(block["source"]["data"]) for block in images],
                         [gif_bytes, test_attachments.PNG])
        self.assertEqual(item["input_image_sha256s"], [test_core.core.digest(gif_bytes),
                                                     test_core.core.digest(test_attachments.PNG)])
        finished = self.fixture.execute(batch)[0]
        self.assertNotEqual(finished["state"], "returned")
        self.assertIs(finished["contradictory_completion_fields"], True)

    def test_generated_mixed_frame_passes_actual_helper_parser_without_provider_access(self):
        gif_bytes = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==")
        gif = self.project / "first.gif"
        gif.write_bytes(gif_bytes)
        self.source.write_text('label = "unicode π\u2028separator\u2029text\u0085end"\n', encoding="utf-8")
        snapshots = attachments.read_files(str(self.project), [str(gif), str(self.source), str(self.picture)])
        request, transport = attachments.automated_packet(
            "claude-code", "FixtureAgent: Please inspect these exact synthetic images and source. Thank you.", snapshots)
        raw = request.encode("utf-8")
        expected = [test_core.core.digest(gif_bytes), test_core.core.digest(test_attachments.PNG)]
        spec = importlib.util.spec_from_file_location(
            "native_bridge_helper_under_test", test_core.PACKAGE_ROOT / "scripts" / "claude_code_check.py")
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        with patch.object(helper.subprocess, "Popen", side_effect=AssertionError("No provider process")) as spawn, \
             patch.object(helper.subprocess, "run", side_effect=AssertionError("No provider process")) as run:
            observed = helper.validate_input_packet(raw, "stream-json")
        spawn.assert_not_called()
        run.assert_not_called()
        self.assertEqual(transport, "claude_content_blocks")
        self.assertEqual(observed, expected)
        self.assertEqual(raw, request.encode("utf-8"))
        self.assertEqual(helper.sha256(raw), test_core.core.digest(raw))

    def test_native_report_distinguishes_images_from_source_without_active_embeds(self):
        svg = self.project / "diagram.svg"
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"><text>Synthetic only</text></svg>', encoding="utf-8")
        self.fixture.observe()
        batch = self.submit([self.picture, self.source, svg])
        finished = self.fixture.execute(batch)[0]
        self.assertEqual(finished["state"], "returned")
        views = [capabilities.attachment_view(item, "input", finished["attachment_transport"])
                 for item in finished["attachments"]]
        self.assertEqual([view["representation"] for view in views],
                         ["native_image_content_block", "inline_utf8_source_text", "inline_utf8_source_text"])
        for view in views:
            self.assertFalse(view["provider_interpretation_verified"])
            self.assertNotIn("source_path", view)
            self.assertNotIn("snapshot_path", view)
        for format in ("html", "markdown"):
            report = self.hub.comparison_report(str(self.project), [finished["id"]], format)
            content = report["content"]
            self.assertIn("native_image_content_block", content)
            self.assertIn("inline_utf8_source_text", content)
            self.assertIn("SVG is source text", content)
            self.assertIn(test_core.core.digest(test_attachments.PNG), content)
            self.assertFalse(report["sent"])
            self.assertFalse(report["published"])
            self.assertNotIn("<img", content)
            self.assertNotIn("data:image", content)
            self.assertNotIn(base64.b64encode(test_attachments.PNG).decode("ascii"), content)
            self.assertNotIn(str(self.picture), content)

    def test_native_snapshot_tamper_stops_before_helper_spawn(self):
        self.fixture.observe()
        batch = self.submit([self.picture])
        item = batch["jobs"][0]
        snapshots = self.hub.attachment_files(str(self.project), item["id"])
        Path(snapshots["upload_paths"][0]).write_bytes(b"Changed bytes")
        with patch.object(test_core.worker.subprocess, "Popen", side_effect=AssertionError("Must not dispatch")) as spawn:
            finished = self.fixture.execute(batch)[0]
        spawn.assert_not_called()
        self.assertEqual(finished["state"], "blocked")
        self.assertEqual(finished["submission"], "not_started")

    def test_native_packet_tamper_stops_before_helper_spawn(self):
        self.fixture.observe()
        batch = self.submit([self.picture])
        item = batch["jobs"][0]
        packet_path = Path(item["evidence_directory"]) / "packet.txt"
        packet_path.write_bytes(packet_path.read_bytes() + b'\n{"type":"user"}\n')
        with patch.object(test_core.worker.subprocess, "Popen", side_effect=AssertionError("Must not dispatch")) as spawn:
            finished = self.fixture.execute(batch)[0]
        spawn.assert_not_called()
        self.assertEqual(finished["state"], "blocked")
        self.assertEqual(finished["submission"], "not_started")

    def test_native_dispatch_has_no_api_environment_or_billing_fallback(self):
        self.fixture.observe()
        batch = self.submit([self.picture])
        with patch.dict(os.environ, {key: "SYNTHETIC_NOT_A_CREDENTIAL" for key in (
            "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY", "XAI_API_KEY", "ANTHROPIC_BASE_URL"
        )}):
            finished = self.fixture.execute(batch)[0]
        self.assertEqual(finished["state"], "returned")
        receipt = json.loads((Path(finished["evidence_directory"]) / "provider" / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["fixture_api_environment_keys"], [])
        self.assertEqual(finished["provider"], "claude-code")
        self.assertEqual(len(self.hub.jobs(str(self.project))), 1)

    def test_native_idempotency_binds_original_image_bytes(self):
        self.fixture.observe(jobs=2)
        batch = self.submit([self.picture], key="native-same")
        repeated = self.submit([self.picture], key="native-same")
        self.assertTrue(repeated["reused"])
        self.assertEqual(batch["batch_id"], repeated["batch_id"])
        self.picture.write_bytes(test_attachments.PNG + b"changed")
        with self.assertRaises(ValueError):
            self.submit([self.picture], key="native-same")
        self.fixture.launch.assert_called_once()
        self.assertEqual(len(self.hub.jobs(str(self.project))), 1)

    def test_app_handoff_still_stages_native_documents_without_transport_conversion(self):
        pdf = self.project / "document.pdf"
        pdf.write_bytes(b"%PDF-1.7\nSynthetic document bytes.\n")
        prepared = self.hub.handoff(str(self.project), "chatgpt", "Review these exact files.",
                                    conversation_ref="fixture-project-conversation", attachments=[str(pdf)])
        item = prepared["job"]
        self.assertEqual(item["attachment_transport"], "app_file_handoff")
        self.assertEqual(item["attachment_delivery"], "prepared_not_sent")
        self.assertFalse(prepared["sent"])
        files = self.hub.attachment_files(str(self.project), item["id"])
        self.assertEqual(Path(files["upload_paths"][0]).read_bytes(), pdf.read_bytes())
        self.fixture.launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
