"""App handoffs require observed saved conversations without inventing history proof."""
import json
import time
import unittest

import test_core
from coda_review_hub import core


class ConversationPolicyTests(unittest.TestCase):
    setUp = test_core.HubTests.setUp
    write_pins = test_core.HubTests.write_pins

    def test_every_app_handoff_requires_saved_history_but_preparation_proves_none(self):
        project = core.project_path(str(self.project))
        historical = {
            "id": "historical-app-fixture", "batch_id": "historical-app-fixture",
            "project": project, "provider": "chatgpt", "state": "awaiting_handoff",
            "conversation_ref": "historical-fixture-reference",
            "instructions": "Historical instructions; no persistence observation was recorded.",
        }
        historical_json = json.dumps(historical)
        with self.hub.connect() as connection:
            connection.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,?,0)",
                (historical["id"], historical["batch_id"], project, historical["provider"],
                 historical["state"], historical_json, time.time()))

        for index, provider in enumerate(core.HANDOFF):
            with self.subTest(provider=provider):
                reference = "fixture-conversation-" + provider
                # A new normal saved chat may acquire its reference only after sending.
                prepared_reference = reference if index % 2 else ""
                prepared = self.hub.handoff(str(self.project), provider,
                    "Synthetic bounded app question.", conversation_ref=prepared_reference)
                job = prepared["job"]
                instructions = job["instructions"]
                if provider == "grok-bot":
                    self.assertIn("saved project-specific thread when the actual Grok Bot UI supports one", instructions)
                    self.assertIn("clear project anchor in the packet and result evidence", instructions)
                    self.assertIn("do not claim a new isolated conversation or filesystem", instructions)
                else:
                    self.assertIn("normal saved, non-Temporary conversation dedicated to this project and name it clearly", instructions)
                for requirement in (
                    "Before sending, inspect the actual conversation mode and history controls",
                    "verify that normal saved mode is active",
                    "brand-new normal saved conversation need not already have a URL or history entry before its first send",
                    "After the response, verify that the completed exchange appears in saved history and can be reopened",
                    "actual conversation title, non-secret reference, observed mode, and post-response history check",
                    "returned-result evidence", "pass the reference as conversation_ref",
                    "If normal saved mode cannot be established, do not send",
                    "cannot verify or change app settings",
                    "conversation reference do not prove persistence",
                ):
                    self.assertIn(requirement, instructions)
                self.assertIs(prepared["sent"], False)
                self.assertEqual(job["submission"], "not_sent")
                self.assertEqual(job["state"], "awaiting_handoff")
                self.assertEqual(job["conversation_ref"], prepared_reference)
                self.assertNotIn("response_evidence", job)
                self.assertFalse(job["claims_independently_verified"])

                evidence = (
                    "Synthetic observation only: title 'Fixture Project Review'; reference "
                    + reference + "; normal saved mode observed before sending; after the response, "
                    "the completed exchange appeared in saved history and reopened."
                )
                recorded = self.hub.record_handoff_result(
                    str(self.project), job["id"], "Synthetic app response.", evidence, reference)
                self.assertEqual(recorded["job"]["response_evidence"], evidence)
                self.assertEqual(recorded["job"]["conversation_ref"], reference)
                self.assertIn("did not send or inspect the app", recorded["delivery_basis"])
                for record in (job, recorded["job"]):
                    self.assertFalse(any(value is True and any(word in key.lower()
                        for word in ("persist", "history", "saved", "temporary"))
                        for key, value in record.items()), "Coordinator evidence must not become verified history")

        self.launch.assert_not_called()
        self.hub.jobs(str(self.project))
        with self.hub.connect() as connection:
            stored = connection.execute("SELECT data FROM jobs WHERE id=?", (historical["id"],)).fetchone()
        self.assertEqual(stored["data"], historical_json)


if __name__ == "__main__":
    unittest.main()
