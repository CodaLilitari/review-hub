"""Offline model discovery, explicit choices, and upgrade behavior."""
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import sqlite3
import threading
import time
import unittest
from unittest.mock import patch

import test_core
from coda_review_hub import cli, core, worker
from coda_review_hub.models import ModelStore, normalize_models


class ModelStoreTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = ModelStore(temporary.name)
        self.models = [{"id": "best", "resolved_id": "model-1", "efforts": ["low", "max"]}]

    def record(self, **kwargs):
        return self.store.record("fixture", self.models, "Synthetic catalog observation only.", "official_cli", **kwargs)

    def choose(self):
        status = self.record()
        return self.store.select("fixture", "best", "max", status["catalog"]["fingerprint"], "Explicit synthetic user choice.")

    def test_first_use_requires_choice_and_restart_preserves_it(self):
        self.assertTrue(self.record()["selection_required"])
        with self.assertRaisesRegex(ValueError, "Ask the user"):
            self.store.require("fixture")
        self.choose()
        self.assertEqual(ModelStore(self.store.path.parent).require("fixture")["model"], "best")

    def test_runtime_upgrade_and_cosmetic_labels_do_not_reprompt(self):
        self.choose()
        self.models[0]["label"] = "New display name"
        self.assertFalse(self.record(runtime_version="999.0")["selection_required"])

    def test_new_removed_models_efforts_or_resolved_alias_require_choice(self):
        for update in (lambda: self.models.append({"id": "new", "efforts": ["default"]}),
                       lambda: self.models[0]["efforts"].remove("low"),
                       lambda: self.models[0].update(resolved_id="model-2")):
            self.models = [{"id": "best", "resolved_id": "model-1", "efforts": ["low", "max"]}]
            self.choose()
            update()
            self.assertTrue(self.record()["selection_required"])
            with self.assertRaisesRegex(ValueError, "Ask the user"):
                self.store.require("fixture")

    def test_stale_choice_dialog_and_unsupported_level_rejected(self):
        old = self.record()["catalog"]["fingerprint"]
        self.models.append({"id": "new", "efforts": ["default"]})
        new = self.record()["catalog"]["fingerprint"]
        with self.assertRaisesRegex(ValueError, "changed while"):
            self.store.select("fixture", "best", "max", old, "Synthetic user answer after catalog change.")
        with self.assertRaisesRegex(ValueError, "exposed by this account"):
            self.store.select("fixture", "best", "invented-ultra", new, "Synthetic invalid user level.")

    def test_expired_catalog_requires_refresh_then_preserves_choice(self):
        self.choose()
        with self.store.connect() as connection:
            data = self.store.status("fixture")["catalog"]
            data["checked_at"] = time.time() - 1000
            connection.execute("UPDATE catalogs SET data=?", (json.dumps(data),))
        with self.assertRaisesRegex(ValueError, "Refresh"):
            self.store.require("fixture")
        self.assertFalse(self.record()["selection_required"])

    def test_invalid_or_old_manual_observation_rejected(self):
        for value in (datetime.now().isoformat(), (datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()):
            with self.assertRaises(ValueError):
                self.record(observed_at=value)
        for values in ([], [{"id": "x", "efforts": []}], [{"id": "x", "efforts": ["default", "default"]}]):
            with self.assertRaises(ValueError):
                normalize_models(values)

    def test_late_older_discovery_cannot_overwrite_newer_catalog(self):
        older = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        current = self.record()
        with self.assertRaisesRegex(ValueError, "newer account catalog"):
            self.record(observed_at=older)
        self.assertEqual(self.store.status("fixture")["catalog"], current["catalog"])

    def test_runtime_update_advice_is_preserved_without_becoming_an_eligibility_pin(self):
        self.choose()
        advisory = {"status": "checked", "installed_version": "2.1.0", "latest_version": "2.2.0",
                    "update_available": True, "source": "https://downloads.claude.ai/claude-code-releases/latest",
                    "checked_at": datetime.now(timezone.utc).isoformat(), "unneeded_raw_body": "do not store"}
        status = self.record(runtime_update=advisory)
        self.assertTrue(status["catalog"]["runtime_update"]["update_available"])
        self.assertNotIn("unneeded_raw_body", status["catalog"]["runtime_update"])
        self.assertFalse(status["selection_required"])
        self.assertEqual(self.store.require("fixture")["model"], "best")
        self.assertIn("older client can omit newer account models", status["catalog_scope"])
        status = self.record(runtime_version="999.0", runtime_update={"status": "unavailable", "update_available": None})
        self.assertFalse(status["selection_required"])
        self.assertIsNone(status["catalog"]["runtime_update"]["update_available"])


class ModelDispatchTests(unittest.TestCase):
    setUp = test_core.HubTests.setUp
    write_pins = test_core.HubTests.write_pins
    observe = test_core.HubTests.observe
    submit = test_core.HubTests.submit

    def test_no_choice_stops_before_spending_quota_or_launch(self):
        self.observe()
        with self.hub.models.connect() as connection:
            connection.execute("DELETE FROM choices WHERE provider='claude-code'")
        with self.assertRaisesRegex(ValueError, "Ask the user"):
            self.submit()
        self.launch.assert_not_called()
        self.assertEqual(self.hub.jobs(str(self.project)), [])

    def test_new_catalog_stops_dispatch_and_replay_does_not_rediscover(self):
        self.observe(jobs=2)
        batch = self.submit()
        with patch.object(core, "discover", side_effect=AssertionError("Replay must not probe")):
            self.assertEqual(self.submit()["batch_id"], batch["batch_id"])
        self.hub.cancel(str(self.project), batch["jobs"][0]["id"])
        changed = {"source": "official_cli", "models": [{"id": "new-model", "efforts": ["max"]}],
                   "evidence": "Synthetic changed catalog fixture."}
        with patch.object(core, "discover", return_value=changed):
            with self.assertRaisesRegex(ValueError, "Ask the user"):
                self.submit(key="different-new-request")

    def test_legacy_claude_alias_maps_to_code_and_app_is_separate(self):
        self.observe(provider="claude")
        item = self.submit(provider="claude")["jobs"][0]
        self.assertEqual(item["provider"], "claude-code")
        handoff = self.hub.handoff(str(self.project), "claude-desktop", "Synthetic app question.")
        self.assertEqual(handoff["job"]["model"], "fixture-app")
        self.assertFalse(handoff["sent"])

    def test_cli_catalog_cannot_be_replaced_by_app_attestation(self):
        with self.assertRaisesRegex(ValueError, "cannot substitute"):
            self.hub.record_models("claude-code", [{"id": "invented", "efforts": ["max"]}],
                                   "Synthetic false attestation.", datetime.now(timezone.utc).isoformat())

    def test_helper_pin_no_longer_selects_model_or_effort(self):
        self.pins["claude-code"].pop("model")
        self.pins["claude-code"].pop("effort")
        self.write_pins()
        self.observe()
        item = self.submit()["jobs"][0]
        self.assertEqual((item["model"], item["effort"]), ("fixture-opus", "max"))

    def test_interactive_cli_asks_for_both_choices(self):
        with patch.object(cli.sys.stdin, "isatty", return_value=True), patch("builtins.input", side_effect=["bad", "2"]):
            self.assertEqual(cli._choose("Choose model", ["first", "second"], str), "second")
        args = cli.parser().parse_args(["choose-model", "--provider", "claude-code"])
        self.assertEqual(args.command, "choose-model")

    def test_replay_survives_current_identity_and_helper_changes(self):
        self.observe()
        batch = self.submit()
        self.hub.configure_identity(agent_name="DifferentFixtureAgent", user_name="DifferentFixtureUser",
                                    evidence="Explicit synthetic identity change after preparation.")
        self.fake.unlink()
        with patch.object(core, "discover", side_effect=AssertionError("Replay must not probe")):
            replay = self.submit()
        self.assertEqual(replay["batch_id"], batch["batch_id"])
        self.assertEqual(replay["jobs"], batch["jobs"])
        self.launch.assert_called_once()
        with self.assertRaisesRegex(ValueError, "different input"):
            self.submit(prompt="A different caller question.")

    def test_legacy_fingerprint_replay_uses_preserved_inputs_without_rewriting_history(self):
        self.observe()
        batch = self.submit()
        with self.hub.connect() as c:
            c.execute("UPDATE batches SET fingerprint=? WHERE id=?", ("a" * 64, batch["batch_id"]))
            row = c.execute("SELECT data FROM jobs WHERE batch_id=?", (batch["batch_id"],)).fetchone()
            legacy = json.loads(row[0]); legacy["provider"] = "claude"
            c.execute("UPDATE jobs SET provider='claude',data=? WHERE batch_id=?", (json.dumps(legacy), batch["batch_id"]))
        self.fake.unlink()
        replay = self.submit(provider="claude")
        self.assertEqual(replay["jobs"], [{**legacy, "cancel_requested": False}])
        with self.hub.connect() as c:
            self.assertEqual(c.execute("SELECT fingerprint FROM batches WHERE id=?", (batch["batch_id"],)).fetchone()[0], "a" * 64)
        with self.assertRaisesRegex(ValueError, "different input"):
            self.submit(prompt="Different input must remain a conflict.")

    def test_worker_blocks_choice_changes_before_the_running_claim(self):
        self.observe()
        job = self.submit()["jobs"][0]
        fingerprint = self.hub.model_status("claude-code")["catalog"]["fingerprint"]
        self.hub.select_model("claude-code", job["model"], "low", fingerprint, "User changes the synthetic choice before dispatch.")
        with patch.object(worker.subprocess, "Popen", side_effect=AssertionError("No helper should launch")):
            worker.run_job(self.hub, job["id"])
        current = self.hub.jobs(str(self.project))[0]
        self.assertEqual(current["state"], "blocked")
        self.assertEqual(current["submission"], "not_started")

    def test_concurrent_choice_change_waits_until_local_running_claim(self):
        self.observe()
        job = self.submit()["jobs"][0]
        entered, release, selecting = threading.Event(), threading.Event(), threading.Event()
        original = worker.load_helper
        fingerprint = self.hub.model_status("claude-code")["catalog"]["fingerprint"]
        def load(path):
            entered.set()
            if not release.wait(5):
                raise AssertionError("Fixture release timed out")
            return original(path)
        def choose():
            selecting.set()
            result = self.hub.select_model("claude-code", job["model"], "low", fingerprint,
                                           "User changes the synthetic choice concurrently.")
            return result, self.hub.jobs(str(self.project))[0]["state"]
        with ThreadPoolExecutor(max_workers=2) as pool, patch.object(worker, "load_helper", load):
            execution = pool.submit(worker.run_job, self.hub, job["id"])
            self.assertTrue(entered.wait(3))
            change = pool.submit(choose)
            try:
                self.assertTrue(selecting.wait(3))
                time.sleep(0.1)
                self.assertFalse(change.done(), "Choice must serialize with the running claim")
            finally:
                release.set()
            execution.result(timeout=8)
            selected, state_at_choice = change.result(timeout=8)
        self.assertIn(state_at_choice, {"running", "returned"})
        self.assertEqual(selected["selection"]["effort"], "low")
        response = json.loads((Path(job["evidence_directory"]) / "answer.txt").read_text())
        self.assertEqual(response["effort"], "max")

    def test_model_database_contention_does_not_hold_jobs_database_lock(self):
        self.observe()
        job = self.submit()["jobs"][0]
        entered = threading.Event()
        guard = self.hub.models.guard_selection
        @contextmanager
        def observed_guard(*args, **kwargs):
            entered.set()
            with guard(*args, **kwargs) as selection:
                yield selection
        blocker = sqlite3.connect(self.hub.models.path)
        blocker.execute("BEGIN EXCLUSIVE")
        with ThreadPoolExecutor(max_workers=1) as pool, patch.object(self.hub.models, "guard_selection", observed_guard):
            execution = pool.submit(worker.run_job, self.hub, job["id"])
            try:
                self.assertTrue(entered.wait(3))
                other = sqlite3.connect(self.hub.db, timeout=0.2)
                try:
                    other.execute("BEGIN IMMEDIATE")
                    other.execute("UPDATE jobs SET cancel_requested=1 WHERE id=?", (job["id"],))
                    other.commit()
                finally:
                    other.close()
            finally:
                blocker.rollback(); blocker.close()
            execution.result(timeout=8)
        self.assertEqual(self.hub.jobs(str(self.project))[0]["state"], "cancelled")

    def test_app_handoff_requires_a_new_picker_observation_each_time(self):
        first = self.hub.handoff(str(self.project), "claude-desktop", "First synthetic app question.")
        status = self.hub.model_status("claude-desktop")
        self.assertTrue(status["refresh_required"])
        self.assertTrue(status["app_observation_consumed"])
        with self.assertRaisesRegex(ValueError, "Refresh"):
            self.hub.handoff(str(self.project), "claude-desktop", "Second question requires a fresh check.")
        refreshed = self.hub.record_models("claude-desktop", [{"id": "fixture-app", "efforts": ["default"]}],
            "Synthetic second observation of the actual app picker.", datetime.now(timezone.utc).isoformat())
        self.assertFalse(refreshed["selection_required"])
        second = self.hub.handoff(str(self.project), "claude-desktop", "Second checked synthetic question.")
        self.assertNotEqual(first["job"]["id"], second["job"]["id"])
        self.assertGreater(second["job"]["model_picker_observed_at"], first["job"]["model_picker_observed_at"])
        self.assertIn("verify again at actual send", second["job"]["model_selection_basis"])

    def test_returned_app_evidence_remains_recordable_after_later_catalog_change(self):
        first = self.hub.handoff(str(self.project), "claude-desktop", "Synthetic app question.")
        self.hub.record_models("claude-desktop", [{"id": "different-model", "efforts": ["high"]}],
            "Synthetic subsequent app catalog observation.", datetime.now(timezone.utc).isoformat())
        result = self.hub.record_handoff_result(str(self.project), first["job"]["id"], "Synthetic actual answer.",
            "Synthetic observed response after the first request.", "synthetic-conversation", observed_model="fixture-app", observed_mode="default",
            completion_observation={"status": "completed"})
        self.assertEqual(result["job"]["state"], "returned_via_handoff")

    def test_interactive_cli_can_choose_from_a_fresh_observed_app_catalog(self):
        with patch.object(cli, "Hub", return_value=self.hub), patch.object(cli.sys.stdin, "isatty", return_value=True), \
                patch("builtins.input", side_effect=["1", "1"]), redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["choose-model", "--provider", "claude-desktop"]), 0)

    def test_interactive_cli_shows_update_advice_without_blocking_compatible_versions(self):
        for installed, available in (("old-client", True), ("future-compatible-client", False)):
            output = io.StringIO()
            catalog = {"source": "official_cli", "models": [{"id": "fixture-opus", "efforts": ["max"]}],
                       "evidence": "Synthetic installed client account catalog.", "runtime_version": installed,
                       "runtime_update": {"status": "checked", "installed_version": installed, "latest_version": "published-version",
                                          "update_available": available, "source": "https://example.invalid/fixture-release"}}
            with patch.object(cli, "Hub", return_value=self.hub), patch.object(cli.sys.stdin, "isatty", return_value=True), \
                    patch.object(core, "discover", return_value=catalog), patch("builtins.input", side_effect=["1", "1"]), \
                    redirect_stdout(io.StringIO()), redirect_stderr(output):
                self.assertEqual(cli.main(["choose-model", "--provider", "claude-code"]), 0)
            self.assertEqual("can omit newer models" in output.getvalue(), available)

    def test_worker_error_cannot_overwrite_a_concurrent_completed_receipt(self):
        self.observe()
        job = self.submit()["jobs"][0]
        handling, release, writing = threading.Event(), threading.Event(), threading.Event()
        update = self.hub._update
        def paused_update(connection, row, **changes):
            if changes.get("state") == "blocked":
                handling.set()
                if not release.wait(5):
                    raise AssertionError("Fixture release timed out")
            return update(connection, row, **changes)
        def completed_receipt():
            writing.set()
            with self.hub.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                data = {**job, "state": "returned", "submission": "completed_response_received"}
                connection.execute("UPDATE jobs SET state='returned',data=? WHERE id=?", (json.dumps(data), job["id"]))
        with ThreadPoolExecutor(max_workers=2) as pool, patch.object(self.hub, "_update", paused_update), \
                patch.object(self.hub.models, "guard_selection", side_effect=ValueError("Synthetic rejected selection")):
            losing = pool.submit(worker.run_job, self.hub, job["id"])
            self.assertTrue(handling.wait(3))
            winning = pool.submit(completed_receipt)
            try:
                self.assertTrue(writing.wait(3))
                time.sleep(0.1)
                self.assertFalse(winning.done(), "Failure handling must atomically check and update the current row")
            finally:
                release.set()
            losing.result(timeout=8); winning.result(timeout=8)
        self.assertEqual(self.hub.jobs(str(self.project))[0]["state"], "returned")

    def test_containment_failure_does_not_overwrite_a_job_another_worker_completed(self):
        self.observe()
        batch = self.submit()
        job = batch["jobs"][0]
        def containment_failure():
            with self.hub.connect() as c:
                data = {**job, "state": "returned", "submission": "completed_response_received"}
                c.execute("UPDATE jobs SET state='returned',data=? WHERE id=?", (json.dumps(data), job["id"]))
            raise RuntimeError("Synthetic containment failure after another worker completed")
        with patch.object(worker, "Hub", return_value=self.hub), patch.object(worker, "contain_worker", containment_failure), \
                patch.object(worker.sys, "argv", ["worker", "--state-dir", str(self.hub.state), "--batch", batch["batch_id"]]):
            self.assertEqual(worker.main(), 1)
        self.assertEqual(self.hub.jobs(str(self.project))[0]["state"], "returned")


if __name__ == "__main__":
    unittest.main()
