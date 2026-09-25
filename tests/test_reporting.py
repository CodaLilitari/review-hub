"""Static report safety and receipt semantics; no provider or browser required."""
from copy import deepcopy
from html import escape
from html.parser import HTMLParser
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from coda_review_hub.reporting import render_report


class MarkupInventory(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.attributes = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attributes.extend(attrs)


class ReportingTests(unittest.TestCase):
    def fixture(self):
        return {"schema_version": 1, "project": r"C:\fixture\project", "generated_at": "2026-09-25T20:00:00Z",
                "capabilities": {"automated": ["fixture"], "native_images": False}, "jobs": [{
                    "job": {"id": "job-one", "provider": "fixture-reviewer", "state": "returned",
                            "submission": "completed_response_received", "model": "requested-model",
                            "effort": "high", "observed_model": "observed-model", "observed_mode": "Pro",
                            "verified_response_models": ["response-label"],
                            "claims_independently_verified": False,
                            "attachment_transport": "utf8_json_in_prompt", "attachment_delivery": "embedded_text_response_received",
                            "packet_sha256": "a" * 64, "answer_sha256": "b" * 64},
                    "answer": "A useful review.\nThis is advice.",
                    "lineage": {"parent_job_id": "parent-one", "relation": "followup", "resumed": False},
                    "attachments": {"input": [{"attachment_id": "file-one", "original_name": "drawing.svg",
                        "relative_name": "assets/drawing.svg", "size_bytes": 100, "sha256": "c" * 64,
                        "media_type_hint": "image/svg+xml", "source_path": r"C:\fixture\drawing.svg",
                        "representation": {"kind": "text", "source_sha256": "d" * 64}}], "output": []},
                    "review": {"schema_version": 1, "summary": "One potential issue.", "recorded_at": "recorded-time",
                        "source_answer_sha256": "b" * 64, "limitations": ["No runtime validation."], "findings": [{
                            "id": "finding-one", "severity": "medium", "claim": "A boundary may be wrong.",
                            "evidence_status": "supported_by_packet", "uncertainty": "Not reproduced.",
                            "verification": "Needs an independent test.", "proposed_change": "Check the boundary.",
                            "anchors": [{"attachment_id": "file-one", "sha256": "c" * 64,
                                "start_line": 2, "end_line": 4, "quote": "if x < 0:\n    stop()",
                                "check": {"status": "matched", "detail": "Quote matches recorded snapshot."}}]}]}}]}

    def assert_inert_html(self, rendered):
        parser = MarkupInventory()
        parser.feed(rendered)
        forbidden = {"script", "a", "img", "svg", "iframe", "object", "embed", "form", "input",
                     "video", "audio", "source", "link", "base"}
        self.assertFalse(forbidden & set(parser.tags))
        self.assertFalse(any(name.startswith("on") or name in {"href", "src", "srcset", "action"}
                             for name, _ in parser.attributes))
        return parser

    def test_html_preserves_requested_observed_evidence_and_attachment_distinctions(self):
        rendered = render_report(self.fixture())
        self.assert_inert_html(rendered)
        for phrase in ("Requested model", "Observed app model", "Requested thinking / effort", "Pro",
                       "requested-model", "observed-model", "response-label", "parent-one", "followup",
                       "utf8_json_in_prompt", "Original files and text representations are distinct",
                       "SVG source is not a viewed image", "drawing.svg", "source_sha256",
                       "matched", "Quote matches recorded snapshot.", "Needs an independent test.",
                       "No runtime validation.", "Raw answer", "Independent findings verification recorded"):
            self.assertIn(phrase, rendered)
        self.assertIn("&lt; 0", rendered)
        self.assertIn('Content-Security-Policy', rendered)
        self.assertIn("script-src 'none'", rendered)
        self.assertIn("img-src 'none'", rendered)

    def test_all_provider_controlled_surfaces_are_escaped_not_active_markup(self):
        payload = '</style><script>alert(1)</script><img src="https://bad.invalid/pixel" onerror="run()"><a href="file:///secret">open</a><svg onload="run()">'
        data = self.fixture()
        data.update(project=payload, generated_at=payload, capabilities={payload: payload})
        item = data["jobs"][0]
        item["job"] = {key: payload for key in item["job"]}
        item["answer"] = payload
        item["lineage"] = {payload: payload}
        item["attachments"] = {"input": [{"original_name": payload, "sha256": payload,
                                          "representation": {payload: payload}}], "output": [{"source_path": payload}]}
        review = item["review"]
        review.update(summary=payload, recorded_at=payload, source_answer_sha256=payload, limitations=[payload])
        finding = review["findings"][0]
        finding.update({key: payload for key in finding if key != "anchors"})
        finding["anchors"] = [{"attachment_id": payload, "sha256": payload, "quote": payload,
                               "start_line": payload, "end_line": payload,
                               "check": {"status": payload, "detail": payload}}]
        rendered = render_report(data)
        parser = self.assert_inert_html(rendered)
        self.assertEqual(parser.tags.count("style"), 1)
        self.assertIn(escape(payload, quote=True), rendered)
        self.assertNotIn(payload, rendered)
        self.assertNotIn('class="badge ' + payload, rendered)

    def test_markdown_contains_no_provider_markup_or_active_links_outside_literals(self):
        payload = '<script>alert(1)</script>\n![pixel](https://bad.invalid/pixel)\n[open](file:///secret)\n```\n</details>\n~~~~\nhttps://bad.invalid'
        data = self.fixture()
        data["project"] = payload
        item = data["jobs"][0]
        item["job"]["provider"] = payload + "| extra cell"
        item["answer"] = payload
        item["review"]["summary"] = payload
        item["review"]["findings"][0]["anchors"][0]["quote"] = payload
        rendered = render_report(data, "markdown")
        self.assertNotIn("<script>", rendered)
        self.assertNotIn("</style>", rendered)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertIn("&#124; extra cell", rendered)
        self.assertIn("````text\n", rendered)
        # All attacker-controlled multiline Markdown is inside a longer fence.
        outside = []
        fence = None
        for line in rendered.splitlines():
            if fence is None:
                match = re.fullmatch(r"(`{3,})text", line)
                if match:
                    fence = match.group(1)
                else:
                    outside.append(line)
            elif line == fence:
                fence = None
        self.assertIsNone(fence)
        prose = "\n".join(line for line in outside if not line.startswith("|"))
        self.assertNotIn("![pixel]", prose)
        self.assertNotIn("[open]", prose)
        self.assertNotIn("https://bad.invalid", prose)
        self.assertEqual(rendered.count("</details>"), 1)

    def test_fence_is_longer_than_every_untrusted_backtick_run(self):
        data = self.fixture()
        data["jobs"][0]["answer"] = "`" * 40 + "\n# break out\n" + "`" * 70
        rendered = render_report(data, "markdown")
        self.assertIn("`" * 71 + "text\n", rendered)
        self.assertIn("\n" + "`" * 71 + "\n", rendered)

    def test_incomplete_handoff_and_unknown_state_never_imply_success_or_no_issues(self):
        data = self.fixture()
        data["jobs"] = [{"job": {"provider": "app", "state": state, "submission": "not_sent"},
                         "answer": "", "review": None, "lineage": {}, "attachments": {}}
                        for state in ("prepared", "running", "awaiting_handoff", "future-unrecognized-state", "delivery_unknown")]
        for format in ("html", "markdown"):
            rendered = render_report(data, format)
            self.assertIn("future-unrecognized-state", rendered)
            self.assertIn("awaiting_handoff", rendered)
            self.assertIn("No structured review recorded", rendered)
            self.assertIn("This is not a finding of no issues", rendered)
            self.assertIn("No answer recorded", rendered)
            self.assertIn("not_sent", rendered)
            self.assertNotIn("completed_response_received", rendered)
        self.assertIn('class="badge ">future-unrecognized-state', render_report(data))

    def test_empty_review_missing_anchor_check_and_no_jobs_have_clear_states(self):
        data = self.fixture()
        del data["jobs"][0]["review"]["findings"][0]["anchors"][0]["check"]
        for format in ("html", "markdown"):
            self.assertIn("Not checked", render_report(data, format))
        data["jobs"][0]["review"]["findings"] = []
        for format in ("html", "markdown"):
            self.assertIn("no independent all-clear is implied", render_report(data, format))
        data["jobs"] = []
        for format in ("html", "markdown"):
            self.assertIn("No review jobs recorded", render_report(data, format))

    def test_answer_integrity_and_truncation_notice_remain_visible(self):
        data = self.fixture()
        job = data["jobs"][0]["job"]
        job["source_answer_integrity"] = "changed"
        job["answer_notice"] = "Answer display truncated at 64000 characters; stored answer changed."
        for format in ("html", "markdown"):
            rendered = render_report(data, format)
            self.assertIn("Source answer integrity", rendered)
            self.assertIn("Answer display notice", rendered)
            self.assertIn("changed", rendered)
            self.assertIn("Answer display truncated at 64000 characters; stored answer changed.", rendered)

    def test_renderer_is_pure_and_does_not_open_attachment_paths(self):
        data = self.fixture()
        before = deepcopy(data)
        with patch("builtins.open", side_effect=AssertionError("Renderer must not read files")):
            first = render_report(data)
            self.assertEqual(first, render_report(data))
            render_report(data, "markdown")
        self.assertEqual(data, before)

    def test_invalid_report_contract_and_unknown_format_are_rejected(self):
        for data in (None, {}, {"schema_version": True, "jobs": []}, {"schema_version": 2, "jobs": []},
                     {"schema_version": 1, "jobs": {}}, {"schema_version": 1, "jobs": ["bad"]}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                render_report(data)
        with self.assertRaisesRegex(ValueError, "format"):
            render_report(self.fixture(), "pdf")


if __name__ == "__main__":
    unittest.main()
