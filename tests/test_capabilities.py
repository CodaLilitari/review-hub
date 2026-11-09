"""Offline route/attachment descriptions; no file, app, or provider access."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from coda_review_hub.capabilities import (
    CAPABILITY_FIELDS, all_capabilities, attachment_view, route_capabilities,
)
from coda_review_hub.identity import PROVIDERS


class RouteCapabilityTests(unittest.TestCase):
    def test_catalog_covers_supported_identifiers_with_route_metadata_only(self):
        catalog = all_capabilities()
        self.assertEqual(set(catalog), set(PROVIDERS))
        self.assertEqual(list(catalog), sorted(PROVIDERS))
        for provider, contract in catalog.items():
            self.assertEqual(contract["provider"], provider)
            self.assertEqual(contract["evidence_level"], "local_implementation_contract")
            self.assertTrue(all(name in contract for name in CAPABILITY_FIELDS))
            self.assertFalse(contract["upload_claimed"])
            self.assertFalse(contract["provider_acceptance_verified"])
            self.assertFalse(contract["provider_interpretation_verified"])
            for identity_field in ("agent_name", "user_name", "collaborators", "context_notes"):
                self.assertNotIn(identity_field, contract)
        self.assertEqual(json.loads(json.dumps(catalog)), catalog)

    def test_cli_routes_describe_only_their_implemented_file_transports(self):
        for provider in ("claude-code", "grok", "muse-code", "antigravity"):
            with self.subTest(provider=provider):
                contract = route_capabilities(provider)
                self.assertEqual(contract["transport"], "automated_cli")
                self.assertTrue(contract["available_for_new_work"])
                self.assertTrue(contract["text_snapshot"])
                for name in CAPABILITY_FIELDS[1:]:
                    self.assertIs(contract[name], provider == "claude-code" and name in {"native_file_manifest", "image_visual_input"})
                self.assertIn("SVG", contract["capability_evidence"]["image_visual_input"])
        self.assertEqual(route_capabilities("claude-code")["native_input_media_types"],
                         ["image/gif", "image/jpeg", "image/png", "image/webp"])

    def test_handoffs_distinguish_local_staging_from_app_capabilities(self):
        handoffs = set(PROVIDERS) - {"claude", "claude-code", "grok", "muse-code", "antigravity", "gemini-cli"}
        for provider in handoffs:
            with self.subTest(provider=provider):
                contract = route_capabilities(provider)
                self.assertEqual(contract["transport"], "coordinator_handoff")
                self.assertTrue(contract["native_file_manifest"])
                self.assertTrue(contract["returned_file_snapshot"])
                self.assertFalse(contract["text_snapshot"])
                self.assertTrue(contract["current_app_observation_required"])
                for name in ("image_visual_input", "document_binary_input", "session_resume"):
                    self.assertIsNone(contract[name])

    def test_legacy_claude_alias_preserves_requested_name_and_canonical_route(self):
        alias = route_capabilities("claude")
        actual = route_capabilities("claude-code")
        self.assertEqual(alias["provider"], "claude")
        self.assertEqual(alias["canonical_provider"], "claude-code")
        self.assertEqual({key: value for key, value in alias.items() if key != "provider"},
                         {key: value for key, value in actual.items() if key != "provider"})

    def test_retired_route_is_unavailable_without_erasing_history(self):
        contract = route_capabilities("gemini-cli")
        self.assertFalse(contract["available_for_new_work"])
        self.assertTrue(contract["historical_receipts_available"])
        for name in CAPABILITY_FIELDS:
            self.assertIs(contract[name], False)

    def test_returned_dictionaries_cannot_mutate_future_reports(self):
        report = all_capabilities()
        report["grok"]["image_visual_input"] = True
        report["grok"]["capability_evidence"]["text_snapshot"] = "invented"
        current = route_capabilities("grok")
        self.assertFalse(current["image_visual_input"])
        self.assertNotEqual(current["capability_evidence"]["text_snapshot"], "invented")

    def test_unknown_names_are_not_assigned_speculative_capabilities(self):
        for value in ("unknown", "", None, [], {"provider": "grok"}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                route_capabilities(value)


class AttachmentViewTests(unittest.TestCase):
    def setUp(self):
        self.manifest = {
            "attachment_id": "file-01-0123456789abcdef",
            "sha256": "0123456789abcdef" * 4,
            "original_name": "diagram.svg", "upload_name": "01-diagram.svg",
            "size_bytes": 384, "media_type_hint": "image/svg+xml",
            "source_path": r"C:\private-project\diagram.svg",
            "snapshot_path": r"C:\private-state\attachments\01-diagram.svg",
            "relative_name": "private-subdirectory/diagram.svg",
            "unexpected_private_content": "Never expose this field.",
        }

    def test_preserves_manifest_identifiers_names_and_hash_without_paths(self):
        original = deepcopy(self.manifest)
        view = attachment_view(self.manifest, "input", "utf8_json_in_prompt")
        for key in ("attachment_id", "sha256", "original_name", "upload_name", "size_bytes", "media_type_hint"):
            self.assertEqual(view[key], self.manifest[key])
        for key in ("source_path", "snapshot_path", "relative_name", "unexpected_private_content"):
            self.assertNotIn(key, view)
        self.assertEqual(self.manifest, original)

    def test_svg_source_is_never_reported_as_visual_image_input(self):
        view = attachment_view(self.manifest, "input", "utf8_json_in_prompt")
        self.assertEqual(view["representation"], "inline_utf8_source_text")
        self.assertEqual(view["provider_interpretation"], "source_text_only_no_visual_input")
        self.assertFalse(view["provider_interpretation_verified"])
        self.assertFalse(view["upload_claimed"])

    def test_binary_and_visual_files_cannot_claim_inline_text_transport(self):
        for name in ("image.png", "review.pdf", "report.docx"):
            manifest = {**self.manifest, "original_name": name, "upload_name": "01-" + name}
            with self.subTest(name=name), self.assertRaises(ValueError):
                attachment_view(manifest, "input", "utf8_json_in_prompt")

    def test_native_bytes_can_be_staged_without_claiming_app_acceptance(self):
        for name in ("image.png", "review.pdf", "report.docx", "source.py"):
            manifest = {**self.manifest, "original_name": name, "upload_name": "01-" + name}
            view = attachment_view(manifest, "input", "app_file_handoff")
            self.assertEqual(view["representation"], "staged_native_file_bytes")
            self.assertEqual(view["provider_acceptance"], "unknown_pending_current_app_observation")
            self.assertEqual(view["provider_interpretation"], "unknown_pending_current_app_observation")
            self.assertFalse(view["upload_claimed"])

    def test_output_is_retained_artifact_without_inventing_provider_provenance(self):
        for transport in ("app_file_handoff", "returned_file_snapshot"):
            view = attachment_view(self.manifest, "output", transport)
            self.assertEqual(view["representation"], "retained_returned_file_artifact")
            self.assertIn("does not establish provider origin", view["representation_evidence"])
            self.assertEqual(view["provider_interpretation"], "not_attested")
            self.assertFalse(view["upload_claimed"])

    def test_unknown_direction_and_transport_are_not_silently_classified(self):
        for direction, transport in (("sideways", "app_file_handoff"), ([], "app_file_handoff"), ("input", "api_upload"),
                                     ("input", "returned_file_snapshot"), ("output", "utf8_json_in_prompt")):
            with self.subTest(direction=direction, transport=transport), self.assertRaises(ValueError):
                attachment_view(self.manifest, direction, transport)

    def test_invalid_metadata_does_not_escape_through_the_safe_view(self):
        invalid = [
            ("sha256", "wrong"), ("attachment_id", "../private"),
            ("original_name", r"C:\private\name.txt"), ("upload_name", "folder/name.txt"),
            ("upload_name", "name\n.txt"), ("size_bytes", True), ("size_bytes", -1),
            ("media_type_hint", {"private": "metadata"}),
        ]
        for key, value in invalid:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                attachment_view({**self.manifest, key: value}, "input", "app_file_handoff")

    def test_reports_do_not_read_files_or_call_external_services(self):
        with patch("builtins.open", side_effect=AssertionError("No file reads")), \
                patch.object(Path, "read_bytes", side_effect=AssertionError("No file reads")), \
                patch("subprocess.Popen", side_effect=AssertionError("No process calls")), \
                patch("socket.socket", side_effect=AssertionError("No network calls")):
            all_capabilities()
            attachment_view(self.manifest, "input", "app_file_handoff")
            attachment_view(self.manifest, "output", "returned_file_snapshot")


if __name__ == "__main__":
    unittest.main()
