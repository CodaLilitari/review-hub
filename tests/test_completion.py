"""Pure app-turn completion decisions with no provider or filesystem access."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from coda_review_hub.completion import classify_completion


class CompletionTests(unittest.TestCase):
    def classify(self, observation=None, prior=None, response="Synthetic answer.", evidence="Synthetic observed UI."):
        return classify_completion(response, evidence, observation, [] if prior is None else prior)

    def test_missing_unknown_and_generic_finished_text_never_prove_completion(self):
        for observation in (None, {}, {"status": "unknown"}):
            with self.subTest(observation=observation):
                result = self.classify(observation, response="Finished. Everything is done.", evidence="The UI says finished.")
                self.assertEqual(result["status"], "unknown")
                self.assertFalse(result["complete"])
                self.assertEqual(result["reported_status"], "unknown")
        self.assertIn("observation_missing", self.classify()["signals"])

    def test_hard_interruption_reason_wins_completed_status_and_finished_ui(self):
        reasons = {
            "tool budget": "tool_limit", "max_tools": "tool_limit", "tool_use_limit": "tool_limit",
            "max_tokens": "output_limit", "length": "output_limit", "cancelled": "cancelled",
            "error": "provider_error", "delivery_unknown": "delivery_unknown", "timeout": "delivery_unknown",
        }
        for reason, expected in reasons.items():
            with self.subTest(reason=reason):
                result = self.classify({"status": "completed", "provider_stop_reason": reason}, evidence="The UI says finished.")
                self.assertEqual(result["status"], expected)
                self.assertFalse(result["complete"])
                self.assertEqual(result["reported_status"], "completed")
                self.assertEqual(result["provider_stop_reason"], reason)

    def test_reported_interruption_wins_success_reason(self):
        for status in ("tool_limit", "output_limit", "cancelled", "provider_error", "delivery_unknown", "incomplete"):
            with self.subTest(status=status):
                result = self.classify({"status": status, "provider_stop_reason": "end_turn"})
                self.assertEqual(result["status"], status)
                self.assertFalse(result["complete"])

    def test_known_success_observations_can_complete_without_open_work(self):
        for observation in ({"status": "completed"}, {"provider_stop_reason": "end_turn"},
                            {"provider_stop_reason": "stop_sequence"}, {"provider_stop_reason": "completed"},
                            {"provider_stop_reason": "success"}):
            with self.subTest(observation=observation):
                result = self.classify(observation)
                self.assertEqual(result["status"], "completed")
                self.assertTrue(result["complete"])
                self.assertIn("explicit_completion_observation", result["signals"])

    def test_unknown_nonempty_reason_blocks_even_reported_completion(self):
        for reason in ("future_finish", "stop", "unknown", "custom_done", "error_max_budget_usd", "max_budget_usd"):
            with self.subTest(reason=reason):
                result = self.classify({"status": "completed", "provider_stop_reason": reason})
                self.assertEqual(result["status"], "unknown")
                self.assertFalse(result["complete"])
                self.assertIn("unrecognized_provider_stop_reason", result["signals"])

    def test_reason_spelling_is_preserved_while_comparison_is_normalized(self):
        result = self.classify({"status": "completed", "provider_stop_reason": "  MAX-TOKENS  "})
        self.assertEqual(result["status"], "output_limit")
        self.assertEqual(result["provider_stop_reason"], "MAX-TOKENS")

    def test_tool_call_and_turn_exhaustion_stop_reasons_beat_reported_completion(self):
        for reason in ("tool_call_limit", "max_tool_calls", "max_turns", "error_max_turns", "MAX-TURNS"):
            with self.subTest(reason=reason):
                result = self.classify({"status": "completed", "provider_stop_reason": reason})
                self.assertEqual(result["status"], "tool_limit")
                self.assertFalse(result["complete"])

    def test_pause_tool_request_and_refusal_are_incomplete_not_tool_exhaustion(self):
        for reason in ("pause_turn", "tool_use", "refusal"):
            with self.subTest(reason=reason):
                result = self.classify({"status": "completed", "provider_stop_reason": reason})
                self.assertEqual(result["status"], "incomplete")
                self.assertFalse(result["complete"])
                self.assertEqual(result["reported_status"], "completed")

    def test_bounded_tool_call_and_turn_limit_messages_block_false_final(self):
        phrases = (
            "I've reached the maximum number of tool calls. The source checks are still unfinished.",
            "Tool call limit reached. Please click Continue so I can finish the audit.",
            "I ran out of tool calls before checking the figures.",
            "I have exhausted my tool budget. I cannot finish the last source check in this response.",
            "Tool\u2011call budget exhausted.", "Reached the maximum allowed tool uses.",
            "Exceeded the maximum number of 10 tools.", "I hit my turn limit.",
            "The turn limit has been reached.", "I reached the maximum number of turns.",
        )
        for phrase in phrases:
            for source in ("response", "evidence"):
                with self.subTest(phrase=phrase, source=source):
                    result = self.classify({"status": "completed", "provider_stop_reason": "end_turn"},
                                          **{source: phrase})
                    self.assertEqual(result["status"], "tool_limit")
                    self.assertFalse(result["complete"])
                    self.assertIn(source + "_cue:tool_limit", result["signals"])

    def test_tool_configuration_discussion_and_currency_budget_are_not_tool_cues(self):
        for response in ("Review complete. Consider increasing the tool call limit.",
                         "Set --max-turns 10; the maximum number of tool calls is configurable.",
                         "Review complete. The tool supports a maximum of ten turns."):
            with self.subTest(response=response):
                result = self.classify({"status": "completed"}, response=response)
                self.assertTrue(result["complete"])
                self.assertFalse(any("_cue:" in signal for signal in result["signals"]))
        currency = self.classify({"status": "completed", "provider_stop_reason": "error_max_budget_usd"},
                                 response="I reached the maximum budget of $1.")
        self.assertEqual(currency["status"], "unknown")
        self.assertFalse(currency["complete"])
        self.assertFalse(any("_cue:tool_limit" in signal for signal in currency["signals"]))

    def test_historical_new_tool_call_cue_remains_conservative_after_check_closure(self):
        result = self.classify({"status": "completed", "resolved_checks": ["Check figures"]},
                              prior=["Check figures"],
                              response="Earlier the app said 'Tool call limit reached'; the figures are now checked.")
        self.assertEqual(result["status"], "tool_limit")
        self.assertFalse(result["complete"])
        self.assertEqual(result["outstanding_checks"], [])
        self.assertIn("may quote earlier interruptions", result["basis"])

    def test_tool_limit_cues_in_response_or_evidence_block_false_final(self):
        for phrase in ("reached its tool-use limit", "ran out of tool budget", "REACHED ITS TOOL\u2011USE LIMIT",
                       "hit the tool limit", "hit the tool-use limit", "tool-use limit has been reached"):
            for source in ("response", "evidence"):
                with self.subTest(phrase=phrase, source=source):
                    result = self.classify({"status": "completed"}, **{source: "The app " + phrase + "."})
                    self.assertEqual(result["status"], "tool_limit")
                    self.assertFalse(result["complete"])
                    self.assertIn(source + "_cue:tool_limit", result["signals"])

    def test_finished_ui_and_verdict_do_not_override_explicit_unfinished_tool_limit(self):
        response = "Verdict: the design appears sound.\r\nI hit the tool limit. Select Continue to finish the source checks.\r\n"
        result = self.classify({"status": "completed", "continue_available": False,
                               "outstanding_checks": [], "resolved_checks": []}, response=response,
                              evidence="Synthetic UI reports response finished; source checks are unfinished.")
        self.assertEqual(result["status"], "tool_limit")
        self.assertFalse(result["complete"])

    def test_exact_unfinished_work_statements_beat_reported_or_structured_completion(self):
        for phrase in ("Checks remain unfinished", "Checks remain open", "## Not completed", "## Not re-verified this pass"):
            for observation in ({"status": "completed"}, {"provider_stop_reason": "end_turn"}):
                for source in ("response", "evidence"):
                    with self.subTest(phrase=phrase, observation=observation, source=source):
                        result = self.classify(observation, **{source: phrase + "\nSynthetic source checks."})
                        self.assertEqual(result["status"], "incomplete")
                        self.assertFalse(result["complete"])
                        self.assertIn(source + "_cue:incomplete", result["signals"])

    def test_review_can_be_complete_even_though_the_reviewed_artifact_needs_repairs(self):
        result = self.classify({"status": "completed", "provider_stop_reason": "success"},
                              response="Review completed. Repairs still required in the submitted code.")
        self.assertTrue(result["complete"])
        self.assertFalse(any("_cue:" in signal for signal in result["signals"]))

    def test_explicit_incomplete_stays_incomplete_with_an_unrecognized_stop_reason(self):
        result = self.classify({"status": "incomplete", "provider_stop_reason": "unrecognized_provider_reason"})
        self.assertEqual(result["status"], "incomplete")
        self.assertFalse(result["complete"])
        self.assertIn("unrecognized_provider_stop_reason", result["signals"])

    def test_output_limit_cues_are_conservative_but_generic_discussion_is_not_a_cue(self):
        for phrase in ("reached its output limit", "ran out of output tokens", "reached the maximum output length"):
            result = self.classify({"status": "completed"}, response="The app " + phrase + ".")
            self.assertEqual(result["status"], "output_limit")
            self.assertFalse(result["complete"])
        result = self.classify(response="The document discusses output limits and tool budgets.")
        self.assertEqual(result["status"], "unknown")
        self.assertFalse(any("_cue:" in signal for signal in result["signals"]))

    def test_quoted_old_limit_cues_remain_partial_without_claiming_a_current_verified_limit(self):
        result = self.classify({"status": "completed"}, response="Earlier it said 'reached its tool-use limit'; I now say done.")
        self.assertFalse(result["complete"])
        self.assertIn("may quote earlier interruptions", result["basis"])
        self.assertIn("no app or provider UI was inspected", result["basis"])

    def test_continue_and_new_outstanding_checks_each_prevent_completion(self):
        for additions in ({"continue_available": True}, {"outstanding_checks": ["Verify source A"]}):
            with self.subTest(additions=additions):
                result = self.classify({"status": "completed", "provider_stop_reason": "end_turn", **additions})
                self.assertEqual(result["status"], "incomplete")
                self.assertFalse(result["complete"])

    def test_prior_work_carries_forward_and_merges_without_duplicate_checks(self):
        result = self.classify({"status": "completed", "outstanding_checks": ["Check B", "Check C"],
                                "resolved_checks": ["Check A"]}, prior=["Check A", "Check B"])
        self.assertEqual(result["outstanding_checks"], ["Check B", "Check C"])
        self.assertEqual(result["resolved_checks"], ["Check A"])
        self.assertEqual(result["status"], "incomplete")
        carried = self.classify({"status": "completed"}, prior=["Unresolved source check"])
        self.assertEqual(carried["outstanding_checks"], ["Unresolved source check"])
        self.assertFalse(carried["complete"])

    def test_explicit_closure_requires_all_prior_work_resolved_and_completion_observed(self):
        observation = {"status": "completed", "resolved_checks": ["Check A", "Check B"]}
        result = self.classify(observation, prior=["Check A", "Check B"])
        self.assertTrue(result["complete"])
        self.assertEqual(result["outstanding_checks"], [])
        no_finish = self.classify({"resolved_checks": ["Check A"]}, prior=["Check A"])
        self.assertEqual(no_finish["status"], "unknown")
        self.assertFalse(no_finish["complete"])

    def test_resolved_checks_must_be_prior_work_and_cannot_also_be_outstanding(self):
        for observation in ({"resolved_checks": ["Unknown check"]},
                            {"resolved_checks": ["Check A"], "outstanding_checks": ["Check A"]}):
            with self.subTest(observation=observation), self.assertRaises(ValueError):
                self.classify(observation, prior=["Check A"])

    def test_strict_observation_validation(self):
        values = [
            True, [], "completed", {"complete": True}, {"status": "finished"}, {"status": None},
            {"provider_stop_reason": None}, {"provider_stop_reason": "x" * 129},
            {"provider_stop_reason": "end_turn\n"}, {"continue_available": 1},
            {"continue_available": "false"}, {"continue_available": None},
            {"outstanding_checks": "Check A"}, {"outstanding_checks": [" "]},
            {"outstanding_checks": ["x" * 501]}, {"outstanding_checks": ["A", " A "]},
            {"outstanding_checks": ["A\nB"]}, {"resolved_checks": [1]},
            {"outstanding_checks": [str(i) for i in range(65)]},
        ]
        for observation in values:
            with self.subTest(observation=observation), self.assertRaises(ValueError):
                self.classify(observation)
        for prior in (None, "A", ["A", "A"], ["x" * 501]):
            with self.subTest(prior=prior), self.assertRaises(ValueError):
                classify_completion("Answer", "Evidence", None, prior)
        for response, evidence in ((None, "Evidence"), ("Answer", False)):
            with self.assertRaises(ValueError):
                classify_completion(response, evidence, None, [])

    def test_merged_outstanding_work_remains_bounded(self):
        with self.assertRaisesRegex(ValueError, "Merged outstanding"):
            self.classify({"outstanding_checks": ["new check"]}, prior=[str(i) for i in range(64)])

    def test_pure_classification_does_not_mutate_inputs_or_access_external_state(self):
        observation = {"status": "completed", "resolved_checks": [" A "], "outstanding_checks": ["B"]}
        original = deepcopy(observation)
        prior = ["A"]
        with patch("builtins.open", side_effect=AssertionError("No file access")), \
                patch("subprocess.Popen", side_effect=AssertionError("No processes")), \
                patch("socket.socket", side_effect=AssertionError("No network")):
            result = self.classify(observation, prior=prior)
        result["outstanding_checks"].append("Mutate returned data only")
        self.assertEqual(observation, original)
        self.assertEqual(prior, ["A"])


if __name__ == "__main__":
    unittest.main()
