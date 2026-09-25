"""Offline provider expansion, legacy alias conflicts, and helper receipt regressions."""

from __future__ import annotations

import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_core
from coda_review_hub import core, identity, worker


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

    def enable_synthetic_antigravity(self):
        self.fixture.pins["antigravity"] = dict(self.fixture.pins["grok"], model="fixture-antigravity", effort="fixture-high")
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
        self.enable_synthetic_antigravity()
        self.legacy_profile({"antigravity": "gemini"})
        observation = self.fixture.observe("antigravity")
        with patch("coda_review_hub.worker.subprocess.Popen", side_effect=AssertionError("No helper may start")) as popen:
            with self.assertRaisesRegex(ValueError, "alias_conflicts"):
                self.fixture.submit(provider="antigravity")
            for provider in ("antigravity", "gemini", "meta-ai"):
                with self.subTest(provider=provider), self.assertRaisesRegex(ValueError, "alias_conflicts"):
                    self.hub.handoff(self.project, provider, "Offline synthetic review.")
            popen.assert_not_called()
        self.fixture.launch.assert_not_called()
        self.assertEqual(self.hub.jobs(self.project), [])
        self.assertEqual(self.fixture.remaining()[observation["id"]], 1)

    def test_explicit_reconfiguration_resolves_conflict_without_silent_retargeting(self):
        self.enable_synthetic_antigravity()
        _, saved = self.legacy_profile({"antigravity": "gemini"})
        with self.assertRaisesRegex(ValueError, "canonical provider"):
            self.hub.configure_identity(aliases={"antigravity": "gemini"},
                                        evidence="The synthetic user has not resolved the old alias.")
        self.assertEqual(self.hub.identity.path.read_bytes(), saved)
        self.hub.configure_identity(
            agent_name="FixtureAgent", user_name="FixtureUser", aliases={"gemini-app-reviewer": "gemini"},
            evidence="The synthetic user explicitly renamed the old alias and accepted the distinct CLI route.",
        )
        self.assertNotIn("alias_conflicts", self.hub.identity_status())
        self.assertEqual(self.hub.identity.resolve_provider("gemini-app-reviewer"), "gemini")
        self.assertEqual(self.hub.identity.resolve_provider("antigravity"), "antigravity")
        self.fixture.observe("antigravity")
        batch = self.fixture.submit(provider="antigravity")
        self.assertEqual(batch["jobs"][0]["provider"], "antigravity")
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

    def legacy_cli_job(self, *, completed=False):
        """Create real synthetic records with the pre-transition route vocabulary."""
        self.fixture.pins["gemini-cli"] = dict(self.fixture.pins["grok"], model="fixture-legacy-gemini")
        # Add the retired route's synthetic catalog to this fixture only, so
        # dispatch still exercises native discovery and explicit model choice.
        grok_entry = '{"id": "fixture-grok", "efforts": ["xhigh"]},'
        legacy_entry = '{"id": "fixture-legacy-gemini", "efforts": ["xhigh"]},'
        self.assertEqual(test_core.FAKE_HELPER.count(grok_entry), 1)
        legacy_helper = test_core.FAKE_HELPER.replace(grok_entry, grok_entry + "\n                " + legacy_entry)
        self.fixture.fake.write_bytes(legacy_helper.encode("utf-8"))
        for pin in self.fixture.pins.values():
            pin["sha256"] = core.digest(self.fixture.fake.read_bytes())
        self.fixture.write_pins()
        with patch.object(core, "AUTO", core.AUTO | {"gemini-cli"}), \
                patch.object(core, "RETIRED", {}), patch.object(worker, "RETIRED", {}):
            catalog = self.hub.refresh_models("gemini-cli")
            self.hub.select_model("gemini-cli", "fixture-legacy-gemini", "xhigh",
                                  catalog["catalog"]["fingerprint"], "Explicit synthetic legacy model choice.")
            observation = self.fixture.observe("gemini-cli", jobs=2)
            batch = self.fixture.submit(provider="gemini-cli", key="legacy-cli")
            if completed:
                self.fixture.execute(batch)
        return batch, observation

    def test_retired_cli_blocks_new_allowances_and_sends_without_retargeting(self):
        batch, observation = self.legacy_cli_job(completed=True)
        before = self.fixture.remaining()
        self.fixture.launch.reset_mock()
        self.enable_synthetic_antigravity()
        with self.assertRaisesRegex(ValueError, "personal-subscription Gemini CLI helper is retired"):
            self.fixture.observe("gemini-cli")
        for key in ("legacy-cli", "new-cli"):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "never redirects"):
                self.fixture.submit(provider="gemini-cli", key=key)
        # A remaining Gemini allowance cannot authorize the distinct new route.
        with self.assertRaisesRegex(ValueError, "fresh available-subscription"):
            self.fixture.submit(provider="antigravity", key="new-antigravity")
        self.assertEqual(self.fixture.remaining(), before)
        self.assertEqual(before[observation["id"]], 1)
        self.assertEqual(len(self.hub.jobs(self.project)), 1)
        self.fixture.launch.assert_not_called()
        retired = next(route for route in self.hub.routes()["routes"] if route["provider"] == "gemini-cli")
        self.assertFalse(retired["enabled"])
        self.assertEqual(retired["transport"], "retired_cli")
        self.assertEqual(self.hub.identity.resolve_provider("gemini-cli"), "gemini-cli")

    def test_completed_cli_records_and_identity_survive_upgrade_without_rewriting(self):
        self.hub.configure_identity(
            agent_name="FixtureAgent", user_name="FixtureUser",
            collaborators={"gemini-cli": "Established fixture collaborator", "gemini": "App fixture"},
            context_notes={"gemini-cli": "Historical project context."},
            evidence="Synthetic established identity preferences predating this migration.",
        )
        batch, _ = self.legacy_cli_job(completed=True)
        job_id = batch["jobs"][0]["id"]
        before = self.hub.result(self.project, job_id)
        job_file = Path(before["job"]["evidence_directory"]) / "job.json"
        saved_job, saved_identity = job_file.read_bytes(), self.hub.identity.path.read_bytes()
        reloaded = core.Hub(self.hub.state)
        self.assertEqual(reloaded.result(self.project, job_id), before)
        self.assertEqual(reloaded.jobs(self.project)[0]["provider"], "gemini-cli")
        self.assertEqual(reloaded.identity_status()["collaborators"]["gemini-cli"], "Established fixture collaborator")
        self.assertNotIn("antigravity", reloaded.identity_status()["collaborators"])
        self.assertEqual(job_file.read_bytes(), saved_job)
        self.assertEqual(self.hub.identity.path.read_bytes(), saved_identity)

    def test_preupgrade_queued_cli_job_cannot_launch_after_retirement(self):
        batch, _ = self.legacy_cli_job()
        job_id = batch["jobs"][0]["id"]
        with patch.object(worker.subprocess, "Popen", side_effect=AssertionError("No retired helper launch")) as popen:
            worker.run_job(self.hub, job_id)
            popen.assert_not_called()
        job = self.hub.result(self.project, job_id)["job"]
        self.assertEqual(job["provider"], "gemini-cli")
        self.assertEqual(job["state"], "blocked")
        self.assertEqual(job["submission"], "not_started")
        self.assertIn("helper is retired", job["error"])
        self.assertFalse((Path(job["evidence_directory"]) / "pinned_helper.py").exists())

    def test_antigravity_alias_from_v03_can_target_any_preexisting_route_without_rewrite(self):
        with patch.object(identity, "PROVIDERS", identity.PROVIDERS - {"antigravity"}):
            self.hub.configure_identity(
                aliases={"antigravity": "gemini-cli"}, collaborators={"gemini-cli": "Existing fixture"},
                evidence="Synthetic v0.3 user selected Antigravity as an alias before canonical support.",
            )
        saved = self.hub.identity.path.read_bytes()
        profile = self.hub.identity_status()
        self.assertEqual(profile["aliases"], {"antigravity": "gemini-cli"})
        self.assertEqual(profile["alias_conflicts"]["antigravity"]["previous_target"], "gemini-cli")
        self.assertEqual(self.hub.identity.path.read_bytes(), saved)
        with self.assertRaisesRegex(ValueError, "alias_conflicts"):
            self.fixture.submit(provider="antigravity")

    def install_observed_model_helper(self):
        observation = '''    metadata["verified_response_models"] = []
    metadata["observed_cli_models"] = [args.model]
    metadata["model_evidence"] = "CLI init configuration only; not response-backend attestation."
    if "MODEL:INCOMPLETE" in packet:
        metadata["model_review_completed"] = False
    if "MODEL:EMPTY" in packet:
        (output / "result.txt").write_text("", encoding="utf-8")
    if "MODEL:UNCONFIRMEDDELIVERY" in packet:
        metadata.update(sent=False, submission_attempted=False)
    if "MODEL:MALFORMED" in packet:
        metadata["observed_cli_models"] = [args.model, {"untrusted": "not a model label"}]
        metadata["model_evidence"] = {"not": "a descriptive string"}
'''
        self.fixture.fake.write_text(test_core.FAKE_HELPER.replace(_METADATA_MARKER, observation + _METADATA_MARKER), encoding="utf-8")
        self.enable_synthetic_antigravity()
        for pin in self.fixture.pins.values():
            pin["sha256"] = core.digest(self.fixture.fake.read_bytes())
        self.fixture.write_pins()

    def test_cli_model_observations_are_preserved_without_backend_promotion_or_completion_override(self):
        self.install_observed_model_helper()
        cases = {
            "MODEL:COMPLETE": "returned", "MODE:UNKNOWN": "failed", "MODE:FAIL": "failed",
            "MODE:PREFLIGHT": "blocked", "MODE:CONFLICT": "failed",
            "MODEL:INCOMPLETE": "delivery_unknown", "MODEL:EMPTY": "delivery_unknown",
            "MODEL:UNCONFIRMEDDELIVERY": "delivery_unknown",
        }
        for prompt, expected in cases.items():
            with self.subTest(prompt=prompt):
                self.fixture.observe("antigravity")
                batch = self.fixture.submit(provider="antigravity", prompt=prompt, key=prompt)
                job = self.fixture.execute(batch)[0]
                self.assertEqual(job["state"], expected)
                self.assertEqual(job["observed_cli_models"], ["fixture-antigravity"])
                self.assertEqual(job["verified_response_models"], [])
                self.assertEqual(job["model_evidence"], "CLI init configuration only; not response-backend attestation.")
                self.assertFalse(job["claims_independently_verified"])
                reread = core.Hub(self.hub.state).result(self.project, job["id"])["job"]
                self.assertEqual(reread["observed_cli_models"], job["observed_cli_models"])
                self.assertEqual(reread["model_evidence"], job["model_evidence"])
                self.assertEqual(reread["verified_response_models"], [])

    def test_malformed_model_observations_are_not_exposed_as_labels_or_verified_models(self):
        self.install_observed_model_helper()
        self.fixture.observe("antigravity")
        batch = self.fixture.submit(provider="antigravity", prompt="MODEL:MALFORMED", key="malformed-labels")
        job = self.fixture.execute(batch)[0]
        self.assertEqual(job["state"], "returned")
        self.assertEqual(job["observed_cli_models"], [])
        self.assertEqual(job["model_evidence"], "")
        self.assertEqual(job["verified_response_models"], [])

    def test_legacy_helper_receipt_does_not_invent_cli_model_evidence(self):
        self.fixture.observe()
        job = self.fixture.execute(self.fixture.submit())[0]
        self.assertEqual(job["state"], "returned")
        self.assertEqual(job["verified_response_models"], ["fixture-opus"])
        self.assertEqual(job["observed_cli_models"], [])
        self.assertEqual(job["model_evidence"], "")

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
