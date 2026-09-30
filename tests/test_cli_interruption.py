"""Offline worker receipts for incomplete CLI reviews; no provider calls."""
from __future__ import annotations

import json
from pathlib import Path
import unittest

import test_core
from coda_review_hub.core import digest


PARTIAL = "First source checked.\r\nSecond source remains open. \u03c0"
INTERRUPTED_HELPER = test_core.FAKE_HELPER.replace(
    "import argparse, json, os", "import argparse, hashlib, json, os"
).replace(
    '    (output / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")',
    r'''
    for reason in ("tool_limit", "output_limit", "budget_limit", "incomplete"):
        if "MODE:LIMIT:" + reason in packet:
            metadata.update(status="response_received_incomplete", model_review_completed=False,
                response_received=True, completion_reason=reason,
                response_subtype="error_max_turns", response_stop_reason="end_turn",
                response_terminal_reason="max_turns", response_is_error=True,
                partial_answer_available=True)
            partial = "First source checked.\r\nSecond source remains open. \u03c0".encode("utf-8")
            metadata["partial_answer_sha256"] = hashlib.sha256(partial).hexdigest()
            if "MODE:CORRUPT" in packet:
                partial += b"tampered"
            if "MODE:NO_PARTIAL" in packet:
                metadata["partial_answer_available"] = False
                metadata.pop("partial_answer_sha256")
            else:
                (output / "partial_result.txt").write_bytes(partial)
            if "MODE:DELIVERY_CONFLICT" in packet:
                metadata["sent"] = metadata["submission_attempted"] = False
            if "MODE:LINK_PARTIAL" in packet:
                target = output.parent / "synthetic-linked-partial.txt"
                target.write_bytes(partial)
                (output / "partial_result.txt").unlink()
                (output / "partial_result.txt").symlink_to(target)
            code = 1
    if "MODE:SUCCESS_WITH" in packet:
        metadata.update(status="completed", model_review_completed=True, response_is_error=False,
            response_subtype="success", response_terminal_reason="completed", partial_answer_available=False)
        metadata.pop("partial_answer_sha256", None)
        code = 0
    if "MODE:SUCCESS_WITH_UNKNOWN_REASON" in packet:
        metadata["completion_reason"] = "unknown"
    if "MODE:SUCCESS_WITH_MALFORMED_REASON" in packet:
        metadata["completion_reason"] = ["completed"]
    if "MODE:SUCCESS_WITH_MALFORMED_PARTIAL" in packet:
        metadata.update(completion_reason="completed", partial_answer_available="false")
    if "MODE:SUCCESS_WITH_PARTIAL" in packet:
        metadata.update(completion_reason="completed", partial_answer_available=True)
    if "MODE:RECEIVED_FALSE" in packet:
        metadata["response_received"] = False
    if "MODE:UNKNOWN_RECEIPT" in packet:
        metadata.update(status="delivery_unknown", response_received=False, model_review_completed=False)
    if "MODE:DIAGNOSTIC" in packet:
        (output / "result.txt").write_text("SECRET_RAW_DIAGNOSTIC", encoding="utf-8")
    (output / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
''',
)


class CliInterruptionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_core.HubTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.fake.write_bytes(INTERRUPTED_HELPER.encode("utf-8"))
        for pin in self.fixture.pins.values():
            pin["sha256"] = digest(self.fixture.fake.read_bytes())
        self.fixture.write_pins()
        self.hub = self.fixture.hub
        self.project = str(self.fixture.project)

    def run_limit(self, reason="tool_limit", flags=""):
        self.fixture.observe()
        batch = self.fixture.submit(prompt=f"MODE:LIMIT:{reason} {flags}", key=reason + flags)
        job = self.fixture.execute(batch)[0]
        return batch, job, self.hub.result(self.project, job["id"])

    def assert_findings_blocked(self, job):
        # A malformed envelope fails before the state gate and proves nothing.
        envelope = {"schema_version": 1, "summary": "Synthetic normalized review.", "findings": []}
        with self.assertRaisesRegex(ValueError, "actually returned"):
            self.hub.record_review(self.project, job["id"], envelope, "Synthetic normalization evidence.")

    def test_limit_result_preserves_exact_partial_without_finalizing_or_resuming(self):
        for reason in ("tool_limit", "output_limit", "budget_limit", "incomplete"):
            with self.subTest(reason=reason):
                batch, job, result = self.run_limit(reason)
                self.assertEqual(job["state"], "failed")
                self.assertEqual(job["submission"], "response_received_incomplete")
                self.assertEqual(job["completion_reason"], reason)
                self.assertTrue(job["response_received"])
                self.assertTrue(job["partial_answer_available"])
                self.assertFalse(job["provider_resume"])
                self.assertEqual(result["answer"], PARTIAL)
                self.assertEqual(job["answer_sha256"], digest(PARTIAL.encode("utf-8")))
                self.assertEqual(job["response_termination"]["response_subtype"], "error_max_turns")
                self.assertNotIn("PRIVATE_TEST_REASONING", json.dumps(result))
                self.assert_findings_blocked(job)
                replay = self.fixture.submit(prompt=f"MODE:LIMIT:{reason} ", key=reason)
                self.assertEqual(replay["batch_id"], batch["batch_id"])
                self.assertEqual(len(self.hub.jobs(self.project, batch["batch_id"])), 1)

    def test_corrupt_partial_is_not_exposed_as_answer(self):
        _, job, result = self.run_limit(flags="MODE:CORRUPT")
        self.assertEqual(job["state"], "failed")
        self.assertTrue(job["partial_answer_integrity_error"])
        self.assertFalse(job["partial_answer_available"])
        self.assertFalse(job["answer_available"])
        self.assertEqual(result["answer"], "")

    def test_documented_error_without_partial_is_received_but_has_no_answer(self):
        _, job, result = self.run_limit(flags="MODE:NO_PARTIAL")
        self.assertEqual(job["submission"], "response_received_incomplete")
        self.assertTrue(job["response_received"])
        self.assertFalse(job["partial_answer_available"])
        self.assertEqual(result["answer"], "")

    def test_conflicting_delivery_does_not_expose_partial_or_imply_success(self):
        _, job, result = self.run_limit(flags="MODE:DELIVERY_CONFLICT")
        self.assertEqual(job["state"], "delivery_unknown")
        self.assertTrue(job["contradictory_submission_fields"])
        self.assertFalse(job["partial_answer_available"])
        self.assertEqual(result["answer"], "")

    def test_zero_exit_success_with_limit_or_inconsistent_new_fields_cannot_finalize(self):
        for variant in ("LIMIT_REASON", "UNKNOWN_REASON", "MALFORMED_REASON", "MALFORMED_PARTIAL", "PARTIAL"):
            with self.subTest(variant=variant):
                _, job, result = self.run_limit(flags="MODE:SUCCESS_WITH_" + variant + " MODE:DIAGNOSTIC")
                self.assertEqual(job["helper_exit_code"], 0)
                self.assertNotEqual(job["state"], "returned")
                self.assertFalse(job.get("answer_available", False))
                self.assertFalse(job.get("partial_answer_available", False))
                self.assertEqual(result["answer"], "")
                self.assertNotIn("SECRET_RAW_DIAGNOSTIC", json.dumps(result))
                self.assert_findings_blocked(job)

    def test_explicit_not_received_incomplete_receipt_cannot_expose_result_diagnostics(self):
        _, job, result = self.run_limit(flags="MODE:RECEIVED_FALSE MODE:DIAGNOSTIC")
        self.assertEqual(job["state"], "delivery_unknown")
        self.assertNotIn("response_received", job["submission"])
        self.assertFalse(job.get("answer_available", False))
        self.assertFalse(job.get("partial_answer_available", False))
        self.assertEqual(result["answer"], "")
        self.assertNotIn("SECRET_RAW_DIAGNOSTIC", json.dumps(result))
        self.assert_findings_blocked(job)

    def test_unknown_delivery_is_not_upgraded_by_nonterminal_fields(self):
        _, job, result = self.run_limit(flags="MODE:UNKNOWN_RECEIPT MODE:DIAGNOSTIC")
        self.assertEqual(job["state"], "delivery_unknown")
        self.assertNotIn("response_received", job["submission"])
        self.assertFalse(job.get("answer_available", False))
        self.assertEqual(result["answer"], "")
        self.assertNotIn("SECRET_RAW_DIAGNOSTIC", json.dumps(result))
        self.assert_findings_blocked(job)

    def test_saved_partial_is_hash_checked_on_later_result_reads(self):
        _, job, result = self.run_limit()
        self.assertEqual(result["answer"], PARTIAL)
        Path(job["evidence_directory"], "answer.txt").write_bytes(b"TAMPERED_TEXT")
        with self.assertRaisesRegex(ValueError, "hash|receipt"):
            self.hub.result(self.project, job["id"])

    def test_linked_partial_is_refused_even_with_matching_hash(self):
        target = self.fixture.root / "synthetic-link-probe-target.txt"
        link = self.fixture.root / "synthetic-link-probe.txt"
        target.write_text("Synthetic link capability probe.", encoding="utf-8")
        try:
            link.symlink_to(target)
        except OSError as exc:
            self.skipTest(f"File symlink creation unavailable on this host: {type(exc).__name__}")
        else:
            link.unlink()
        _, job, result = self.run_limit(flags="MODE:LINK_PARTIAL")
        self.assertNotEqual(job["state"], "returned")
        self.assertTrue(job["partial_answer_integrity_error"])
        self.assertFalse(job["partial_answer_available"])
        self.assertFalse(job["answer_available"])
        self.assertEqual(result["answer"], "")


if __name__ == "__main__":
    unittest.main()
