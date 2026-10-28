"""Offline Grok Bot contracts; private names never promote the bot into Build.

Compose the existing temporary BASE/state fixture without inheriting its suite.
No real identity, provider catalog, native app, or worker process is accessed.
"""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import unittest
from unittest.mock import patch

import test_core
from coda_review_hub import core
from coda_review_hub.capabilities import handoff_route_metadata, route_capabilities


BOT_METADATA = {
    "label": "Grok Bot",
    "app_surface": "browser",
    "foreground_desktop_fallback": False,
    "headless_response_route_verified": False,
    "observed_browser_entry_pattern": "https://grok.com/bot/<observed-id>",
    "dispatch_mode": "manual_coordinator",
    "automatic_fallback": False,
    "billing_enforcement": "coordinator_observation_only",
    "current_app_observation_required": True,
}


class GrokBotTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_core.HubTests("test_fresh_observation_and_exact_packet_bytes")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.hub = self.fixture.hub
        self.project = str(self.fixture.project)
        self.discover = self.enterContext(patch.object(
            core, "discover", side_effect=AssertionError("Offline test forbids catalog discovery")))
        self.spawn = self.enterContext(patch.object(
            core.subprocess, "Popen", side_effect=AssertionError("Offline test forbids process launch")))
        self.hub.configure_identity(
            agent_name="FixtureAgent", user_name="FixtureUser",
            collaborators={"chatgpt": "FixtureChat", "grok": "FixtureBuild", "meta-muse": "FixtureMuse"},
            aliases={"saved-chat": "chatgpt", "saved-build": "grok"},
            context_notes={"chatgpt": "Preserve the synthetic saved chat.",
                           "meta-muse": "Preserve the unrelated synthetic browser choice."},
            evidence="Existing synthetic profile choices; no real user profile is read.",
        )

    def tearDown(self):
        self.fixture.launch.assert_not_called()
        self.discover.assert_not_called()
        self.spawn.assert_not_called()

    def configure_bot(self, alias="grokbot", name="FixtureBot"):
        """The API replaces profiles: explicitly preserve every unrelated field."""
        current = self.hub.identity_status()
        return self.hub.configure_identity(
            agent_name=current["agent_name"], user_name=current["user_name"],
            collaborators={**current["collaborators"], "grok-bot": name},
            aliases={**current["aliases"], alias: "grok-bot"},
            context_notes={**current["context_notes"], "grok-bot": "Synthetic saved bot conversation only."},
            evidence="Explicit synthetic addition of a bot name and alias; preserve existing choices.",
        )

    def observe_bot(self, choose=True):
        status = self.hub.record_models(
            "grokbot", [{"id": "fixture-bot-mode", "efforts": ["default"]}],
            "Synthetic current native bot observation; no real app or account accessed.",
            datetime.now(timezone.utc).isoformat(),
        )
        if choose:
            status = self.hub.select_model(
                "grokbot", "fixture-bot-mode", "default", status["catalog"]["fingerprint"],
                "Explicit synthetic choice of the observed bot mode.",
            )
        return status

    def assert_bot_metadata(self, value):
        for key, expected in BOT_METADATA.items():
            with self.subTest(metadata_field=key):
                self.assertEqual(value[key], expected)

    def test_public_default_has_no_global_bot_alias_or_collaborator_name(self):
        public = core.Hub(self.fixture.root / "unconfigured-public-state")
        status = public.identity_status()
        self.assertFalse(status["configured"])
        self.assertEqual(status["aliases"], {})
        self.assertEqual(status["collaborators"], {})
        self.assertFalse(public.identity.path.exists())
        with self.assertRaises(ValueError):
            public.identity.resolve_provider("grokbot")
        with self.assertRaises(ValueError):
            public.capabilities("grokbot")
        self.assertEqual(public.capabilities("grok-bot")["canonical_provider"], "grok-bot")
        route = next(r for r in public.routes()["routes"] if r["provider"] == "grok-bot")
        self.assertIsNone(route["collaborator_name"])
        self.configure_bot(alias="my-private-bot", name="DifferentFixtureName")
        self.assertEqual(self.hub.identity.resolve_provider("my-private-bot"), "grok-bot")
        with self.assertRaises(ValueError):
            self.hub.identity.resolve_provider("grokbot")

    def test_metadata_and_catalog_keep_bot_separate_from_build(self):
        self.configure_bot()
        listing = self.hub.routes()
        routes = {r["provider"]: r for r in listing["routes"]}
        self.assertEqual(listing["route_counts"], {"automated": 3, "coordinator_handoff": 11, "retired": 1})
        self.assertNotIn("grokbot", routes)
        self.assert_bot_metadata(routes["grok-bot"])
        self.assertEqual(routes["grok-bot"]["transport"], "coordinator_handoff")
        self.assertFalse(routes["grok-bot"]["live_ready"])
        self.assertEqual(routes["grok-bot"]["collaborator_name"], "FixtureBot")
        self.assertEqual(routes["grok"]["label"], "Grok Build CLI")
        self.assertEqual(routes["grok"]["transport"], "cli")
        self.assertEqual(routes["grok"]["collaborator_name"], "FixtureBuild")
        for contract in (handoff_route_metadata("grok-bot"), route_capabilities("grok-bot"),
                         self.hub.capabilities("grokbot")):
            self.assert_bot_metadata(contract)
        capability = self.hub.capabilities("grokbot")
        self.assertEqual(capability["canonical_provider"], "grok-bot")
        for field in ("image_visual_input", "document_binary_input", "session_resume"):
            self.assertIsNone(capability[field])
        for field in ("upload_claimed", "provider_acceptance_verified", "provider_interpretation_verified"):
            self.assertFalse(capability[field])
        self.assertEqual(self.hub.capabilities("grok")["transport"], "automated_cli")
        self.assertNotIn("grokbot", self.hub.capabilities())

    def test_usage_contract_requires_the_applicable_account_plan_and_meter(self):
        self.configure_bot()
        contracts = [handoff_route_metadata("grok-bot"),
                     route_capabilities("grok-bot"), self.hub.capabilities("grokbot")]
        contracts.append(next(r for r in self.hub.routes()["routes"]
                              if r["provider"] == "grok-bot"))
        for metadata in contracts:
            with self.subTest(surface=metadata.get("transport", "metadata")):
                scope = metadata["usage_contract"]
                self.assertTrue(scope["account_and_plan_required"])
                self.assertEqual(scope["unknown_meter_conclusion"], "unknown")
                self.assertIn("Cursor", scope["legacy_meter"])
                self.assertIn("Grok Bot", scope["legacy_meter"])
                self.assertIn("verified", scope["shared_plan_meter"])
                self.assertIn("The X Subscription", scope["shared_plan_meter"])
                self.assertIn("used_or_remaining", scope["required_meter_evidence"])
                self.assertIn("paid_extra_controls", scope["required_meter_evidence"])
                self.assertFalse(scope["general_grok_percentage_alone_proves_bot_allowance"])
        self.assertNotIn("usage_contract", handoff_route_metadata("grok"))

    def test_build_exhaustion_does_not_turn_bot_handoff_into_an_exhaustion_claim(self):
        self.configure_bot()
        self.observe_bot()
        with self.assertRaisesRegex(ValueError, "prior allowance revoked"):
            self.hub.observe_usage(
                provider="grok", project=self.project,
                observed_at=datetime.now(timezone.utc).isoformat(),
                evidence="Synthetic Grok Build included allowance exhausted; no Bot meter observed.",
                included_available=False, paid_usage_disabled=True, max_jobs=1)
        prepared = self.hub.handoff(self.project, "grokbot", "Synthetic bounded Bot review.")
        job = prepared["job"]
        self.assertEqual(job["state"], "awaiting_handoff")
        self.assertFalse(prepared["sent"])
        self.assertEqual(job["usage_contract"]["unknown_meter_conclusion"], "unknown")
        self.assertIn("account and plan", job["instructions"])
        self.assertIn("unknown", job["instructions"])
        self.assertNotIn("included_available", job)

    def test_alias_model_methods_share_only_the_canonical_bot_catalog(self):
        self.configure_bot()
        build_before = deepcopy(self.hub.model_status("grok"))
        recorded = self.observe_bot(choose=False)
        self.assertEqual(recorded["provider"], "grok-bot")
        self.assertEqual(recorded["catalog"]["source"], "observed_app")
        self.assertTrue(recorded["selection_required"])
        selected = self.hub.select_model(
            "grokbot", "fixture-bot-mode", "default", recorded["catalog"]["fingerprint"],
            "Explicit synthetic model selection through the private alias.",
        )
        self.assertEqual(selected["provider"], "grok-bot")
        self.assertEqual(self.hub.model_status("grokbot"), self.hub.model_status("grok-bot"))
        refreshed = self.hub.refresh_models("grokbot")
        self.assertEqual(refreshed["provider"], "grok-bot")
        self.assertTrue(refreshed["refresh_required"])
        self.assertEqual(refreshed["selection"]["model"], "fixture-bot-mode")
        self.assertEqual(build_before["selection"]["model"], "fixture-grok")
        self.assertNotEqual(refreshed["selection"]["model"], build_before["selection"]["model"])
        self.assertIn("signed-in app", refreshed["next"])
        self.assertIsNone(self.hub.models.status("grokbot")["catalog"])
        self.assertIsNone(self.hub.models.status("grokbot")["selection"])
        self.assertEqual(self.hub.model_status("grok"), build_before)

    def test_alias_handoff_consumes_bot_observation_and_requires_a_fresh_one(self):
        self.configure_bot()
        self.observe_bot()
        build_before = deepcopy(self.hub.model_status("grok"))
        prompt = "Synthetic bounded bot packet.\r\nPreserve exact bytes: \u03c0.\r\n"
        reference = "https://grok.com/bot/fixture-bot-id"
        prepared = self.hub.handoff(self.project, "grokbot", prompt, reference)
        job = prepared["job"]
        self.assertFalse(prepared["sent"])
        self.assertEqual(job["provider"], "grok-bot")
        self.assertEqual(job["state"], "awaiting_handoff")
        self.assertEqual(job["submission"], "not_sent")
        self.assertEqual(job["model"], "fixture-bot-mode")
        self.assertFalse(job["backend_model_verified"])
        self.assertEqual(job["conversation_ref"], reference)
        self.assert_bot_metadata(job)
        evidence = Path(job["evidence_directory"])
        self.assertEqual((evidence / "original.txt").read_bytes(), prompt.encode("utf-8"))
        self.assertEqual((evidence / "packet.txt").read_bytes(), prepared["packet"].encode("utf-8"))
        self.assertIn(prompt, prepared["packet"])
        self.assertIn("Grok Bot scope: The shared cloud computer is not an isolation boundary.", prepared["packet"])
        self.assertIn("Review only the authorized packet and actions above.", prepared["packet"])
        self.assertIn("Report missing inputs or access rather than expanding scope.", prepared["packet"])
        self.assertTrue(self.hub.model_status("grokbot")["app_observation_consumed"])
        with self.assertRaisesRegex(ValueError, "Refresh"):
            self.hub.handoff(self.project, "grok-bot", "No stale observation reuse.")
        self.observe_bot(choose=False)
        second = self.hub.handoff(self.project, "grok-bot", "Synthetic fresh observation.")["job"]
        self.assertEqual(second["provider"], "grok-bot")
        self.assertEqual(self.hub.model_status("grok"), build_before)

    def test_submit_refuses_bot_without_spending_build_allowance_or_preparing_jobs(self):
        self.configure_bot()
        self.observe_bot()
        allowance = self.fixture.observe("grok", jobs=2)
        bot_before = deepcopy(self.hub.model_status("grok-bot"))
        cases = [
            [{"provider": "grokbot", "prompt": "Must remain a manual bot handoff."}],
            [{"provider": "grok-bot", "prompt": "Canonical bot must not dispatch."}],
            [{"provider": "grok", "prompt": "Build must not launch a partial batch."},
             {"provider": "grokbot", "prompt": "Bot prevents the whole automated batch."}],
        ]
        for index, requests in enumerate(cases):
            with self.subTest(requests=requests), self.assertRaises(ValueError):
                self.hub.submit(self.project, requests, f"offline-refused-bot-{index}")
            self.assertEqual(self.fixture.remaining()[allowance["id"]], 2)
            self.assertEqual(self.hub.model_status("grok-bot"), bot_before)
            self.assertEqual(self.hub.jobs(self.project), [])
        self.assertFalse((self.hub.state / "artifacts").exists())

    def test_native_snapshot_and_exact_response_continuation_remain_bot(self):
        self.configure_bot()
        self.observe_bot()
        source = self.fixture.project / "synthetic-bot-document.pdf"
        original = b"%PDF-synthetic-only\x00\xff\r\nNot a real document."
        source.write_bytes(original)
        reference = "fixture-saved-bot-conversation"
        job = self.hub.handoff(self.project, "grokbot", "Inspect the exact synthetic file only.",
                               reference, attachments=[str(source)])["job"]
        files = self.hub.attachment_files(self.project, job["id"])
        source.write_bytes(b"Modified original must not change the prepared snapshot.")
        self.assertEqual(Path(files["upload_paths"][0]).read_bytes(), original)
        self.assertFalse(files["sent"])
        common = dict(project=self.project, job_id=job["id"], conversation_ref=reference,
                      evidence="Synthetic coordinator observation in the same saved bot conversation.",
                      observed_attachment_ids=[item["attachment_id"] for item in files["manifest"]],
                      attachment_evidence="Synthetic exact accepted attachment chip; no real app used.")
        partial_text = "Synthetic first response.\r\nOne check remains.\r\n"
        partial = self.hub.record_handoff_result(
            **common, response=partial_text,
            completion_observation={"status": "tool_limit", "continue_available": True,
                                    "outstanding_checks": ["Check the synthetic footer"]})["job"]
        self.assertEqual(partial["provider"], "grok-bot")
        self.assertEqual(partial["state"], "needs_continuation")
        prior = partial["handoff_turns"][-1]
        final_text = "Synthetic footer check complete.\r\n"
        final_args = dict(common, response=final_text, previous_turn_id=prior["turn_id"],
                          completion_observation={"status": "completed",
                                                  "resolved_checks": ["Check the synthetic footer"]})
        with self.assertRaisesRegex(ValueError, "Conversation reference differs"):
            self.hub.record_handoff_result(**{**final_args, "conversation_ref": "fixture-build-session"})
        complete = self.hub.record_handoff_result(**final_args)["job"]
        reread = core.Hub(self.hub.state)
        self.assertEqual(complete["state"], "returned_via_handoff")
        self.assertEqual(complete["provider"], "grok-bot")
        self.assert_bot_metadata(reread.result(self.project, job["id"])["job"])
        self.assertEqual(reread.result(self.project, job["id"])["answer"], final_text)
        self.assertEqual(reread.result(self.project, job["id"], turn_id=prior["turn_id"])["answer"], partial_text)
        self.assertEqual(complete["handoff_turns"][-1]["previous_answer_sha256"], prior["answer_sha256"])
        self.assertFalse(complete["backend_model_verified"])

    def test_additive_full_profile_update_retains_unrelated_names_notes_and_choices(self):
        before = deepcopy(self.hub.identity_status())
        choices = {p: deepcopy(self.hub.models.status(p)["selection"]) for p in core.AUTO | set(core.HANDOFF)}
        self.configure_bot()
        after = core.Hub(self.hub.state).identity_status()
        for key in ("agent_name", "user_name"):
            self.assertEqual(after[key], before[key])
        for field in ("collaborators", "aliases", "context_notes"):
            for key, value in before[field].items():
                self.assertEqual(after[field][key], value)
        self.assertEqual(after["aliases"]["grokbot"], "grok-bot")
        self.assertEqual(after["collaborators"]["grok-bot"], "FixtureBot")
        self.assertEqual(self.hub.identity.resolve_provider("grok"), "grok")
        self.assertEqual(self.hub.identity.resolve_provider("saved-build"), "grok")
        self.assertEqual({p: self.hub.models.status(p)["selection"] for p in choices}, choices)


if __name__ == "__main__":
    unittest.main()
