"""Offline attachment contracts across the real MCP and CLI interfaces."""

import json
import hashlib
from pathlib import Path
import subprocess
import sys
import unittest

from mcp import Client

import test_mcp


class MCPAttachmentTests(unittest.IsolatedAsyncioTestCase):
    setUp = test_mcp.MCPStdioTests.setUp

    async def test_attachment_lists_are_strict_and_bounded(self):
        async with Client(self.params, read_timeout_seconds=15) as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
            self.assertTrue(tools["attachment_files"].model_dump(by_alias=True)["annotations"]["readOnlyHint"])
            for value in ("source.py", [42], ["source.py"] * 17):
                with self.subTest(value=value):
                    submit = await client.call_tool("submit", {
                        "project": str(self.project), "idempotency_key": "invalid-attachments",
                        "requests": [{"provider": "claude", "prompt": "Offline schema test.", "attachments": value}],
                    })
                    self.assertTrue(submit.is_error)
                    handoff = await client.call_tool("handoff", {
                        "project": str(self.project), "provider": "gemini", "prompt": "Offline schema test.",
                        "attachments": value,
                    })
                    self.assertTrue(handoff.is_error)
                    for field in ("observed_attachment_ids", "returned_files"):
                        recorded = await client.call_tool("record_handoff_result", {
                            "project": str(self.project), "job_id": "nonexistent",
                            "response": "Synthetic response", "evidence": "Offline fixture evidence only.",
                            "conversation_ref": "synthetic-conversation", field: value,
                        })
                        self.assertTrue(recorded.is_error)
            invalid_direction = await client.call_tool("attachment_files", {
                "project": str(self.project), "job_id": "nonexistent", "direction": "arbitrary-root",
            })
            self.assertTrue(invalid_direction.is_error)

    async def test_nonproject_and_url_attachments_are_refused(self):
        outside = self.root / "outside.txt"
        outside.write_text("Synthetic file outside the authorized project.", encoding="utf-8")
        async with Client(self.params, read_timeout_seconds=15) as client:
            for candidate in (str(outside), "https://example.invalid/source.txt", str(self.project)):
                with self.subTest(candidate=candidate):
                    result = await client.call_tool("handoff", {
                        "project": str(self.project), "provider": "gemini", "prompt": "Offline scope test.",
                        "attachments": [candidate],
                    })
                    self.assertTrue(result.is_error)
            jobs = await client.call_tool("jobs", {"project": str(self.project)})
            self.assertFalse(jobs.is_error)
            self.assertEqual(jobs.structured_content, {"result": []})

    async def test_automated_binary_attachment_is_refused_without_dispatch(self):
        binary = self.project / "fixture.bin"
        binary.write_bytes(b"\x00\xff\x80synthetic binary")
        async with Client(self.params, read_timeout_seconds=15) as client:
            result = await client.call_tool("submit", {
                "project": str(self.project), "idempotency_key": "binary-not-sent",
                "requests": [{"provider": "grok", "prompt": "Offline binary rejection.", "attachments": [str(binary)]}],
            })
            self.assertTrue(result.is_error)
            self.assertIn("UTF-8", " ".join(getattr(item, "text", "") for item in result.content))
            jobs = await client.call_tool("jobs", {"project": str(self.project)})
            self.assertEqual(jobs.structured_content, {"result": []})

    async def test_input_snapshots_exact_evidence_and_returned_artifacts(self):
        first = self.project / "source.py"
        second = self.project / "diagram.png"
        first_bytes = "value = 'π'\n".encode("utf-8")
        second_bytes = b"\x89PNG\r\n\x1a\nsynthetic fixture bytes"
        first.write_bytes(first_bytes)
        second.write_bytes(second_bytes)
        returned_file = self.project / "returned.txt"
        returned_file.write_text("Synthetic downloaded artifact; no provider contacted.\n", encoding="utf-8")
        async with Client(self.params, read_timeout_seconds=15) as client:
            prepared = await client.call_tool("handoff", {
                "project": str(self.project), "provider": "gemini", "prompt": "Offline attachment round trip.",
                "conversation_ref": "synthetic-attachment-conversation", "attachments": [str(first), str(second)],
            })
            self.assertFalse(prepared.is_error)
            job_id = prepared.structured_content["job"]["id"]
            files = await client.call_tool("attachment_files", {"project": str(self.project), "job_id": job_id})
            self.assertFalse(files.is_error)
            manifest = files.structured_content
            self.assertTrue(manifest["verified"])
            self.assertFalse(manifest["sent"])
            self.assertEqual(manifest["direction"], "input")
            self.assertEqual(manifest["upload_paths"], [item["snapshot_path"] for item in manifest["manifest"]])
            self.assertEqual([Path(path).read_bytes() for path in manifest["upload_paths"]], [first_bytes, second_bytes])
            self.assertEqual([item["sha256"] for item in manifest["manifest"]],
                             [hashlib.sha256(data).hexdigest() for data in (first_bytes, second_bytes)])
            self.assertNotIn(str(first), manifest["upload_paths"])
            first.write_text("Changed original after snapshot.\n", encoding="utf-8")
            stable = await client.call_tool("attachment_files", {"project": str(self.project), "job_id": job_id})
            self.assertEqual(stable.structured_content["manifest_sha256"], manifest["manifest_sha256"])
            self.assertEqual(Path(stable.structured_content["upload_paths"][0]).read_bytes(), first_bytes)
            ids = [item["attachment_id"] for item in manifest["manifest"]]
            recording = {
                "project": str(self.project), "job_id": job_id,
                "response": "Synthetic app response; no provider contacted.",
                "evidence": "Offline fixture response observation only.",
                "conversation_ref": "synthetic-attachment-conversation",
                "returned_files": [str(returned_file)],
                "artifact_evidence": "Offline fixture represents an explicitly observed downloaded artifact.",
            }
            for extra in ({}, {"observed_attachment_ids": ids},
                          {"observed_attachment_ids": list(reversed(ids)), "attachment_evidence": "Wrong order fixture."}):
                refused = await client.call_tool("record_handoff_result", dict(recording, **extra))
                self.assertTrue(refused.is_error)
            recorded = await client.call_tool("record_handoff_result", dict(
                recording, observed_attachment_ids=ids,
                attachment_evidence="Offline fixture records both attachment chips in exact manifest order.",
            ))
            self.assertFalse(recorded.is_error)
            self.assertEqual(len(recorded.structured_content["job"]["attachments"]), 2)
            self.assertEqual(len(recorded.structured_content["job"]["returned_artifacts"]), 1)
            output = await client.call_tool("attachment_files", {
                "project": str(self.project), "job_id": job_id, "direction": "output",
            })
            self.assertFalse(output.is_error)
            self.assertFalse(output.structured_content["sent"])
            self.assertTrue(output.structured_content["verified"])
            self.assertEqual(Path(output.structured_content["upload_paths"][0]).read_bytes(), returned_file.read_bytes())
            # A changed staged snapshot must be refused on the next read.
            Path(manifest["upload_paths"][0]).write_bytes(b"tampered fixture")
            tampered = await client.call_tool("attachment_files", {"project": str(self.project), "job_id": job_id})
            self.assertTrue(tampered.is_error)

    def invoke_cli(self, *args):
        return subprocess.run(
            [sys.executable, "-B", "-m", "coda_review_hub.cli", "--state-dir", str(self.root / "cli-state"), *args],
            env=self.params.env, cwd=self.project, capture_output=True, text=True, encoding="utf-8", timeout=15,
        )

    def test_cli_attachment_direction_is_restricted(self):
        rejected = self.invoke_cli("attachment-files", "--project", str(self.project),
                                   "--job-id", "nonexistent", "--direction", "arbitrary-root")
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("invalid choice", rejected.stderr)

    def test_cli_attachment_handoff_and_record_fields(self):
        attachment = self.project / "input.txt"
        attachment.write_text("Synthetic CLI attachment.\n", encoding="utf-8")
        returned = self.project / "output.txt"
        returned.write_text("Synthetic returned artifact.\n", encoding="utf-8")
        packet = self.root / "handoff.json"
        packet.write_text(json.dumps({
            "project": str(self.project), "provider": "gemini", "prompt": "Offline CLI attachment handoff.",
            "conversation_ref": "synthetic-cli-conversation", "attachments": [str(attachment)],
        }), encoding="utf-8")
        prepared = self.invoke_cli("handoff", str(packet))
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        job_id = json.loads(prepared.stdout)["job"]["id"]
        file_list = self.invoke_cli("attachment-files", "--project", str(self.project), "--job-id", job_id)
        self.assertEqual(file_list.returncode, 0, file_list.stderr)
        manifest = json.loads(file_list.stdout)
        self.assertFalse(manifest["sent"])
        record = self.root / "record.json"
        record.write_text(json.dumps({
            "project": str(self.project), "job_id": job_id, "response": "Synthetic app response.",
            "evidence": "Offline CLI observation fixture.", "conversation_ref": "synthetic-cli-conversation",
            "observed_attachment_ids": [item["attachment_id"] for item in manifest["manifest"]],
            "attachment_evidence": "Synthetic exact attachment chip observed in fixture.",
            "returned_files": [str(returned)], "artifact_evidence": "Synthetic downloaded artifact observed in fixture.",
        }), encoding="utf-8")
        recorded = self.invoke_cli("record-handoff-result", str(record))
        self.assertEqual(recorded.returncode, 0, recorded.stderr)
        output = self.invoke_cli("attachment-files", "--project", str(self.project), "--job-id", job_id, "--direction", "output")
        self.assertEqual(output.returncode, 0, output.stderr)
        output_manifest = json.loads(output.stdout)
        self.assertFalse(output_manifest["sent"])
        self.assertEqual(Path(output_manifest["upload_paths"][0]).read_bytes(), returned.read_bytes())


if __name__ == "__main__":
    unittest.main()
