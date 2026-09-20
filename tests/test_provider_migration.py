"""Offline provider expansion, legacy alias conflicts, and helper receipt regressions."""

from __future__ import annotations

import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_core
from coda_review_hub import core, identity


# Reuse the fixture's real offline process and append only receipt variants.
# No provider executable, account, API, or network is involved.
_RECEIPT_VARIANTS = '''    variants = {
        "both-false": {"sent": False, "submission_attempted": False},
        "sent-false": {"sent": False, "submission_attempted": True},
        "attempted-false": {"sent": True, "submission_attempted": False},
        "sent-only-false": {"sent": False},
        "attempted-only-false": {"submission_attempted": False},
        "invalid-text": {"sent": "false", "submission_attempted": True},
        "invalid-integer": {"sent": 1, "submission_attempted": True},
        "sent-only-true": {"sent": True},
        "attempted-only-true": {"submission_attempted": True},
    }
    for label, fields in variants.items():
        if "RECEIPT:" + label in packet:
            metadata.pop("sent", None)
            metadata.pop("submission_attempted", None)
            metadata.update(fields)
            break
'''
_METADATA_MARKER = '    (output / "metadata.json").write_text('
assert test_core.FAKE_HELPER.count(_METADATA_MARKER) == 1
RECEIPT_HELPER = test_core.FAKE_HELPER.replace(_METADATA_MARKER, _RECEIPT_VARIANTS + _METADATA_MARKER)


class ProviderMigrationTests(unittest.TestCase):
    def setUp(self):
        # Composition avoids rediscovering every test in HubTests.
        self.fixture = test_core.HubTests("test_fresh_observation_and_exact_packet_bytes")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.hub = self.fixture.hub
        self.project = str(self.fixture.project)

    def legacy_profile(self, aliases):
        """Write a profile through the previous provider vocabulary, then upgrade."""
        with patch.object(identity, "PROVIDERS", identity.PROVIDERS - identity.ADDED_PROVIDERS):
            profile = self.hub.configure_identity(
                agent_name="FixtureAgent", user_name="FixtureUser",
                aliases=aliases,
                context_notes={"gemini": "Use only the synthetic app conversation."},
                evidence="The synthetic user chose these aliases before the new routes existed.",
            )
        return profile, self.hub.identity.path.read_bytes()

    def enable_synthetic_gemini(self):
        self.fixture.pins["gemini-cli"] = dict(self.fixture.pins["grok"], model="fixture-gemini", effort="high")
        self.fixture.write_pins()

    def install_receipt_helper(self):
        self.fixture.fake.write_bytes(RECEIPT_HELPER.encode("utf-8"))
        for pin in self.fixture.pins.values():
            pin["sha256"] = core.digest(self.fixture.fake.read_bytes())
        self.fixture.write_pins()

    def test_legacy_aliases_are_preserved_and_conflicts_are_readable_without_rewriting(self):
        aliases = {name: "gemini" for name in identity.ADDED_PROVIDERS}
        aliases["app-reviewer"] = "chatgpt"
        original, saved = self.legacy_profile(aliases)
        profile = self.hub.identity_status()
        self.assertEqual(profile["aliases"], original["aliases"])
        self.assertEqual(profile["configured_at"], original["configured_at"])
        self.assertEqual(profile["context_notes"], original["context_notes"])
        self.assertEqual(profile["alias_conflicts"], {
            name: {"previous_target": "gemini", "canonical_provider": name}
            for name in identity.ADDED_PROVIDERS
        })
        self.assertEqual(self.hub.identity.path.read_bytes(), saved)
        self.assertEqual(self.hub.identity.resolve_provider("app-reviewer"), "chatgpt")
        for name in identity.ADDED_PROVIDERS:
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "alias_conflicts"):
                self.hub.identity.resolve_provider(name)
        # Inventory must stay available without interpreting a canonical route
        # name as an old app alias or granting authority to either interpretation.
        routes = {row["provider"]: row for row in self.hub.routes()["routes"]}
        self.assertEqual(routes["gemini"]["configured_context"], original["context_notes"]["gemini"])
        self.assertEqual(routes["gemini-desktop"]["configured_context"], "")

    def test_conflicting_alias_cannot_become_automated_authority_or_a_handoff(self):
        self.enable_synthetic_gemini()
        self.legacy_profile({"gemini-cli": "gemini"})
        observation = self.fixture.observe("gemini-cli")
        with patch("coda_review_hub.worker.subprocess.Popen", side_effect=AssertionError("No helper may start")) as popen:
            with self.assertRaisesRegex(ValueError, "alias_conflicts"):
                self.fixture.submit(provider="gemini-cli")
            for provider in ("gemini-cli", "gemini", "meta-ai"):
                with self.subTest(provider=provider), self.assertRaisesRegex(ValueError, "alias_conflicts"):
                    self.hub.handoff(self.project, provider, "Offline synthetic review.")
            popen.assert_not_called()
        self.fixture.launch.assert_not_called()
        self.assertEqual(self.hub.jobs(self.project), [])
        self.assertEqual(self.fixture.remaining()[observation["id"]], 1)

    def test_explicit_reconfiguration_resolves_conflict_without_silent_retargeting(self):
        self.enable_synthetic_gemini()
        _, saved = self.legacy_profile({"gemini-cli": "gemini"})
        with self.assertRaisesRegex(ValueError, "canonical provider"):
            self.hub.configure_identity(aliases={"gemini-cli": "gemini"},
                                        evidence="The synthetic user has not resolved the old alias.")
        self.assertEqual(self.hub.identity.path.read_bytes(), saved)
        self.hub.configure_identity(
            agent_name="FixtureAgent", user_name="FixtureUser", aliases={"gemini-app-reviewer": "gemini"},
            evidence="The synthetic user explicitly renamed the old alias and accepted the distinct CLI route.",
        )
        self.assertNotIn("alias_conflicts", self.hub.identity_status())
        self.assertEqual(self.hub.identity.resolve_provider("gemini-app-reviewer"), "gemini")
        self.assertEqual(self.hub.identity.resolve_provider("gemini-cli"), "gemini-cli")
        self.fixture.observe("gemini-cli")
        batch = self.fixture.submit(provider="gemini-cli")
        self.assertEqual(batch["jobs"][0]["provider"], "gemini-cli")
        self.assertEqual(batch["jobs"][0]["submission"], "not_started")

    def test_new_configuration_still_refuses_all_canonical_alias_shadows(self):
        saved = self.hub.identity.path.read_bytes()
        for name in identity.PROVIDERS:
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "canonical provider"):
                self.hub.configure_identity(aliases={name: "gemini"},
                                            evidence="A synthetic invalid canonical shadow attempt.")
            self.assertEqual(self.hub.identity.path.read_bytes(), saved)

    def test_legacy_read_does_not_accept_shadows_that_were_never_valid(self):
        original = json.loads(self.hub.identity.path.read_text(encoding="utf-8"))
        for aliases in ({"grok": "claude"}, {"gemini-cli": "gemini-desktop"}, {"gemini-cli": "unknown"}):
            with self.subTest(aliases=aliases):
                self.hub.identity.path.write_text(json.dumps(dict(original, aliases=aliases)), encoding="utf-8")
                with self.assertRaises(ValueError):
                    self.hub.identity_status()

    def test_real_synthetic_helper_conflicting_delivery_receipts_remain_unknown(self):
        self.install_receipt_helper()
        for label in ("both-false", "sent-false", "attempted-false", "sent-only-false",
                      "attempted-only-false", "invalid-text", "invalid-integer"):
            with self.subTest(label=label):
                self.fixture.observe()
                prompt = "RECEIPT:" + label
                batch = self.fixture.submit(prompt=prompt, key=label)
                job = self.fixture.execute(batch)[0]
                self.assertEqual(job["helper_exit_code"], 0)
                self.assertEqual(job["helper_status"], "completed")
                self.assertTrue(job["answer_available"])
                self.assertTrue(job["contradictory_submission_fields"])
                self.assertTrue(job["contradictory_completion_fields"])
                self.assertEqual(job["state"], "delivery_unknown")
                self.assertEqual(job["submission"], "conflicting_helper_submission_receipt")
                result = self.hub.result(self.project, job["id"])
                self.assertIn("synthetic only", result["answer"])
                self.assertNotIn("PRIVATE_TEST_REASONING", json.dumps(result))
                directory = Path(job["evidence_directory"])
                self.assertTrue((directory / "started.json").is_file())
                replay = self.fixture.submit(prompt=prompt, key=label)
                self.assertTrue(replay["reused"])
                self.assertEqual(replay["jobs"][0]["state"], "delivery_unknown")
                self.assertEqual(len((directory / "launches.txt").read_text().splitlines()), 1)

    def test_real_synthetic_helper_accepts_each_unambiguous_delivery_field(self):
        self.install_receipt_helper()
        for label in ("sent-only-true", "attempted-only-true"):
            with self.subTest(label=label):
                self.fixture.observe()
                job = self.fixture.execute(self.fixture.submit(prompt="RECEIPT:" + label, key=label))[0]
                self.assertEqual(job["state"], "returned")
                self.assertEqual(job["submission"], "completed_response_received")
                self.assertFalse(job["contradictory_submission_fields"])


if __name__ == "__main__":
    unittest.main()
