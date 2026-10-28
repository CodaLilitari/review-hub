"""Conditional app fallback must be tied to the exact model/mode control."""
from datetime import datetime, timedelta, timezone
import json
import sqlite3
import tempfile
import unittest

from coda_review_hub.models import ModelStore


class AppFallbackTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = ModelStore(temporary.name)
        self.models = [{"id": "gpt-5.6", "efforts": ["pro"]}]
        self.policy = {"primary_model": "gpt-6", "primary_effort": "pro",
                       "fallback_model": "gpt-5.6", "fallback_effort": "pro", "workspace": "Personal"}
        self.catalog = self.record(selection_policy=self.policy)

    def record(self, **kwargs):
        return self.store.record("chatgpt", self.models,
                                 "Synthetic observed Personal picker controls.", "observed_app", **kwargs)

    def observation(self, **changes):
        return {"primary_model": "gpt-6", "primary_effort": "pro",
                "target_model": "gpt-6", "target_effort": "pro",
                "workspace": "Personal", "scope": "exact_control", "state": "disabled",
                "enabled": False, "selected": False,
                "observed_at": datetime.now(timezone.utc).isoformat(),
                "evidence": "Synthetic exact GPT-6 Pro control is visibly disabled.", **changes}

    def choose(self, observation):
        return self.store.select("chatgpt", "gpt-5.6", "pro", self.catalog["catalog"]["fingerprint"],
                                 "User preauthorized fallback only if primary is unavailable.",
                                 selection_basis="conditional_fallback", fallback_observation=observation)

    def test_generic_menu_lock_does_not_override_enabled_or_selected_primary(self):
        for changes in ({"scope": "menu"}, {"enabled": True}, {"selected": True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.choose(self.observation(
                    evidence="Menu innerText: Locked, opens access options. Usage limit reached.", **changes))
        self.assertIsNone(self.store.status("chatgpt")["selection"])

    def test_exact_disabled_primary_allows_and_retains_conditional_fallback(self):
        observation = self.observation()
        choice = self.choose(observation)["selection"]
        self.assertEqual((choice["model"], choice["effort"]), ("gpt-5.6", "pro"))
        self.assertEqual(choice["fallback_observation"], observation)
        self.assertEqual(self.store.claim_app_selection("chatgpt")["fallback_observation"], observation)

    def test_wrong_target_or_effort_and_stale_observation_are_rejected(self):
        for changes in ({"target_model": "other"}, {"target_effort": "thinking"},
                        {"observed_at": (datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.choose(self.observation(**changes))

    def test_available_catalog_primary_contradicts_disabled_control_claim(self):
        self.models.append({"id": "gpt-6", "efforts": ["pro"]})
        self.catalog = self.record()
        with self.assertRaisesRegex(ValueError, "contradict"):
            self.choose(self.observation())

    def test_provider_limit_requires_actual_primary_selected_at_request(self):
        observation = self.observation(scope="provider_request", state="limit_reached",
                                       selected_model="gpt-6", selected_effort="pro")
        observation.pop("enabled"); observation.pop("selected")
        self.models.append({"id": "gpt-6", "efforts": ["pro"]})
        self.catalog = self.record(observed_at=observation["observed_at"])
        with self.assertRaises(ValueError):
            self.choose({**observation, "selected_model": "gpt-5.6"})
        with self.assertRaises(ValueError):
            self.choose({**observation, "selected_effort": "thinking"})
        self.assertEqual(self.choose(observation)["selection"]["fallback_observation"], observation)

    def test_new_app_observation_requires_new_fallback_evidence(self):
        self.choose(self.observation())
        self.store.claim_app_selection("chatgpt")
        self.catalog = self.record()
        with self.assertRaisesRegex(ValueError, "fallback"):
            self.store.claim_app_selection("chatgpt")
        self.choose(self.observation())
        self.assertEqual(self.store.claim_app_selection("chatgpt")["model"], "gpt-5.6")

    def test_old_provider_error_cannot_be_rebound_to_a_new_catalog(self):
        old = self.observation(scope="provider_request", state="limit_reached",
                               selected_model="gpt-6", selected_effort="pro")
        old.pop("enabled"); old.pop("selected")
        self.choose(old)
        self.store.claim_app_selection("chatgpt")
        self.models.append({"id": "gpt-6", "efforts": ["pro"]})
        later = (datetime.fromisoformat(old["observed_at"])+timedelta(seconds=1)).isoformat()
        self.catalog = self.record(observed_at=later)
        with self.assertRaisesRegex(ValueError, "catalog"):
            self.choose(old)
        fresh = {**old, "observed_at": later}
        self.assertEqual(self.choose(fresh)["selection"]["model"], "gpt-5.6")

    def test_added_unrelated_option_reapplies_standing_primary_without_reasking(self):
        self.models.append({"id": "gpt-6", "efforts": ["pro"]})
        self.catalog = self.record()
        self.store.select("chatgpt", "gpt-6", "pro", self.catalog["catalog"]["fingerprint"],
                          "User's standing primary remains selected.")
        self.models.append({"id": "unrelated", "efforts": ["default"]})
        self.catalog = self.record()
        self.assertTrue(self.catalog["selection_required"])
        self.assertIn("standing", self.catalog["next"])
        self.assertNotIn("Ask the user", self.catalog["next"])
        selected = self.store.select("chatgpt", "gpt-6", "pro", self.catalog["catalog"]["fingerprint"],
                                     "Reapply the already authorized primary after unrelated catalog addition.")
        self.assertFalse(selected["selection_required"])

    def test_old_prose_only_fallback_is_rejected_under_standing_policy(self):
        with self.assertRaisesRegex(ValueError, "selection_basis"):
            self.store.select("chatgpt", "gpt-5.6", "pro", self.catalog["catalog"]["fingerprint"],
                              "Menu says Locked, opens access options. Usage limit reached.")
        with self.assertRaisesRegex(ValueError, "structured"):
            self.choose(None)
        self.assertIsNone(self.store.status("chatgpt")["selection"])

    def test_refresh_preserves_policy_and_primary_choice_needs_no_fallback(self):
        self.models.append({"id": "gpt-6", "efforts": ["pro"]})
        self.catalog = self.record()
        self.assertEqual(self.catalog["catalog"]["selection_policy"], self.policy)
        chosen = self.store.select("chatgpt", "gpt-6", "pro", self.catalog["catalog"]["fingerprint"],
                                   "User's standing primary model preference remains available.")
        self.assertEqual(chosen["selection"]["selection_basis"], "primary")

    def test_current_direct_user_override_has_separate_evidence(self):
        with self.assertRaisesRegex(ValueError, "override"):
            self.store.select("chatgpt", "gpt-5.6", "pro", self.catalog["catalog"]["fingerprint"],
                              "Old standing conditional fallback authorization.", selection_basis="explicit_user_override")
        chosen = self.store.select("chatgpt", "gpt-5.6", "pro", self.catalog["catalog"]["fingerprint"],
                                   "User directly requested this specific model for this review.",
                                   selection_basis="explicit_user_override",
                                   override_evidence="Current human instruction explicitly requests this model despite primary availability.")
        self.assertNotIn("fallback_observation", chosen["selection"])
        self.assertIn("override_evidence", chosen["selection"])

    def test_only_preapproved_fallback_and_configured_primary_can_be_claimed(self):
        self.models.append({"id": "other-model", "efforts": ["pro"]})
        self.catalog = self.record()
        with self.assertRaisesRegex(ValueError, "approved fallback"):
            self.store.select("chatgpt", "other-model", "pro", self.catalog["catalog"]["fingerprint"],
                              "Synthetic standing fallback request.", selection_basis="conditional_fallback",
                              fallback_observation=self.observation())
        with self.assertRaisesRegex(ValueError, "configured primary"):
            self.choose(self.observation(primary_model="other", target_model="other"))

    def test_legacy_replace_cannot_drop_policy_or_write_unclassified_choice(self):
        original = self.store.status("chatgpt")["catalog"]
        legacy_catalog = {k: v for k, v in original.items() if k not in {"selection_policy", "policy_contract_version"}}
        legacy_choice = {"model": "gpt-5.6", "effort": "pro", "catalog_fingerprint": original["fingerprint"],
                         "evidence": "Old worker inferred a lock from generic menu text."}
        for table, data in (("catalogs", legacy_catalog), ("choices", legacy_choice)):
            with self.subTest(table=table), self.assertRaisesRegex(sqlite3.IntegrityError, "policy"):
                with self.store.connect() as c:
                    c.execute("INSERT OR REPLACE INTO app_uses VALUES ('unrelated-fixture', 1)")
                    c.execute(f"INSERT OR REPLACE INTO {table} VALUES (?,?)", ("chatgpt", json.dumps(data)))
            with self.store.connect() as c:
                self.assertIsNone(c.execute("SELECT * FROM app_uses WHERE provider='unrelated-fixture'").fetchone())
            self.assertEqual(self.store.status("chatgpt")["catalog"], original)
            self.assertIsNone(self.store.status("chatgpt")["selection"])

    def test_existing_prepolicy_choice_is_preserved_but_old_consumption_is_blocked(self):
        models = [{"id": "gpt-5.6", "efforts": ["pro"]}]
        before = self.store.record("legacy-app", models, "Synthetic original account catalog.", "observed_app")
        self.store.select("legacy-app", "gpt-5.6", "pro", before["catalog"]["fingerprint"], "Original direct user choice.")
        with self.store.connect() as c:
            original = c.execute("SELECT data FROM choices WHERE provider='legacy-app'").fetchone()[0]
        after = self.store.record("legacy-app", models, "User now authorizes the standing primary/fallback policy.",
                                  "observed_app", selection_policy=self.policy)
        with self.store.connect() as c:
            self.assertEqual(c.execute("SELECT data FROM choices WHERE provider='legacy-app'").fetchone()[0], original)
        with self.assertRaisesRegex(sqlite3.IntegrityError, "policy"):
            with self.store.connect() as c:
                c.execute("INSERT OR REPLACE INTO app_uses VALUES (?,?)", ("legacy-app", after["catalog"]["checked_at"]))
        self.assertTrue(self.store.status("legacy-app")["selection_required"])

    def test_deliberate_new_policy_replacement_and_primary_still_work(self):
        updated = {"primary_model": "gpt-5.6", "primary_effort": "pro",
                   "fallback_model": "gpt-6", "fallback_effort": "pro", "workspace": "Personal"}
        self.catalog = self.record(selection_policy=updated)
        self.assertEqual(self.record()["catalog"]["selection_policy"], updated)
        chosen = self.store.select("chatgpt", "gpt-5.6", "pro", self.catalog["catalog"]["fingerprint"],
                                   "New explicit human instruction changes the standing primary.")
        self.assertEqual(chosen["selection"]["selection_basis"], "primary")
        self.assertEqual(self.store.claim_app_selection("chatgpt")["model"], "gpt-5.6")
