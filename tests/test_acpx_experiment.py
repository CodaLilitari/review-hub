"""Mock subprocess tests only; no acpx package, providers, or credentials used."""
from dataclasses import replace
from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("review_hub_mock_acp_contract",
    Path(__file__).resolve().parents[1] / "experimental/acpx/contract.py")
contract = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = contract
SPEC.loader.exec_module(contract)
PROBE_SPEC = importlib.util.spec_from_file_location("review_hub_mock_acp_probe",
    Path(__file__).resolve().parents[1] / "experimental/acpx/probe.py")
probe = importlib.util.module_from_spec(PROBE_SPEC)
with patch.dict(sys.modules, {"contract": contract}):
    PROBE_SPEC.loader.exec_module(probe)


class AcpxExperimentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="acp-contract-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.command = contract.MockCommand.reviewed()
        self.runner = contract.Experiment(self.root / "state.sqlite3", self.command)
        self.scope = contract.Scope(str(self.project))

    def scenario(self, value):
        (self.project / ".acp-mock-control.json").write_text(json.dumps({"scenario": value}))

    def methods(self):
        path = self.project / ".acp-mock-events.jsonl"
        return [json.loads(line)["method"] for line in path.read_text().splitlines()] if path.exists() else []

    def run_mock(self, key="one", **kwargs):
        return self.runner.run(self.scope, key, "Synthetic packet", opt_in=True, **kwargs)

    def test_explicit_opt_in_and_exact_known_command_are_required(self):
        with self.assertRaisesRegex(contract.ContractError, "opt-in"):
            self.runner.run(self.scope, "key", "Synthetic packet")
        for command in (replace(self.command, agent=str(self.root / "other.py")),
                        replace(self.command, agent_sha256="0" * 64)):
            with self.subTest(command=command), self.assertRaises(contract.ContractError):
                contract.Experiment(self.root / "other.sqlite3", command).run(self.scope, "key", "Input", opt_in=True)
        self.assertEqual(self.methods(), [])

    def test_new_session_and_final_response_are_distinct_from_authentication(self):
        receipt = self.run_mock()
        self.assertEqual(receipt["status"], "returned")
        self.assertEqual(receipt["answer"], "Synthetic mock answer.")
        self.assertTrue(receipt["prompt_written"])
        self.assertFalse(receipt["account_authenticated"])
        self.assertEqual(self.methods(), ["initialize", "session/new", "session/prompt"])

    def test_relative_agent_cannot_execute_project_shadow_after_cwd_change(self):
        relative = Path("experimental/acpx/mock_agent.py")
        shadow = self.project / relative
        shadow.parent.mkdir(parents=True)
        shadow.write_text("raise RuntimeError('Unreviewed project shadow must never execute')")
        command = replace(self.command, agent=str(relative))
        original_cwd = Path.cwd()
        try:
            os.chdir(Path(__file__).resolve().parents[1])
            # This is the bypass condition: validation's old resolution found
            # the reviewed source, but Popen(cwd=project) would find the shadow.
            self.assertEqual(relative.resolve(), contract.MOCK_AGENT)
            self.assertNotEqual(shadow.resolve(), contract.MOCK_AGENT)
            with patch.object(contract.subprocess, "Popen") as spawn:
                with self.assertRaisesRegex(contract.ContractError, "absolute"):
                    contract.Experiment(self.root / "shadow.sqlite3", command).run(
                        self.scope, "shadow", "Synthetic input", opt_in=True)
            spawn.assert_not_called()
        finally:
            os.chdir(original_cwd)

    def test_relative_interpreter_is_rejected_before_project_cwd_launch(self):
        executable = Path(sys.executable).resolve()
        command = replace(self.command, executable=executable.name)
        original_cwd = Path.cwd()
        try:
            os.chdir(executable.parent)
            self.assertEqual(Path(command.executable).resolve(), executable)
            with patch.object(contract.subprocess, "Popen") as spawn:
                with self.assertRaisesRegex(contract.ContractError, "absolute"):
                    contract.Experiment(self.root / "interpreter.sqlite3", command).run(
                        self.scope, "interpreter", "Synthetic input", opt_in=True)
            spawn.assert_not_called()
        finally:
            os.chdir(original_cwd)

    def test_launch_arguments_use_verified_canonical_absolute_paths(self):
        executable, agent = Path(self.command.executable), Path(self.command.agent)
        command = replace(self.command,
                          executable=str(executable.parent / ".." / executable.parent.name / executable.name),
                          agent=str(agent.parent / ".." / agent.parent.name / agent.name))
        self.assertEqual(command.validate(), [str(executable.resolve()), "-I", str(agent.resolve())])

    def test_probe_stops_on_failed_first_step_or_absent_session(self):
        for receipt in ({"status": "blocked", "session_id": None},
                        {"status": "returned", "session_id": None},
                        {"status": "returned", "session_id": " "}):
            with self.subTest(receipt=receipt), patch.object(probe, "Experiment") as factory, redirect_stdout(io.StringIO()) as output:
                factory.return_value.run.return_value = receipt
                self.assertEqual(probe.main(["--allow-mock-command"]), 1)
                self.assertEqual(factory.return_value.run.call_count, 1)
            self.assertNotIn("resumed", json.loads(output.getvalue()))
            self.assertNotIn("duplicate", json.loads(output.getvalue()))

    def test_probe_stops_on_unsuccessful_or_mismatched_duplicate(self):
        first = {"status": "returned", "session_id": "mock-exact"}
        for duplicate in ({"status": "blocked", "session_id": "mock-exact", "duplicate": True},
                          {"status": "returned", "session_id": "other", "duplicate": True},
                          {"status": "returned", "session_id": "mock-exact"}):
            with self.subTest(duplicate=duplicate), patch.object(probe, "Experiment") as factory, redirect_stdout(io.StringIO()) as output:
                factory.return_value.run.side_effect = [first, duplicate]
                self.assertEqual(probe.main(["--allow-mock-command"]), 1)
                self.assertEqual(factory.return_value.run.call_count, 2)
            self.assertNotIn("resumed", json.loads(output.getvalue()))

    def test_probe_load_uses_exact_session_and_every_required_step_controls_exit(self):
        first = {"status": "returned", "session_id": "mock-exact"}
        duplicate = {**first, "duplicate": True}
        for final, expected in (({"status": "blocked", "session_id": "mock-exact"}, 1),
                                ({"status": "returned", "session_id": "other"}, 1),
                                (first, 0)):
            with self.subTest(final=final), patch.object(probe, "Experiment") as factory, redirect_stdout(io.StringIO()):
                factory.return_value.run.side_effect = [first, duplicate, final]
                self.assertEqual(probe.main(["--allow-mock-command"]), expected)
                self.assertEqual(factory.return_value.run.call_count, 3)
                self.assertEqual(factory.return_value.run.call_args_list[2].kwargs["session_id"], "mock-exact")

    def test_resume_loads_exact_session_and_does_not_mix_replayed_history(self):
        first = self.run_mock()
        start = len(self.methods())
        resumed = self.run_mock("two", session_id=first["session_id"])
        self.assertEqual(resumed["session_id"], first["session_id"])
        self.assertEqual(resumed["answer"], "Synthetic mock answer.")
        self.assertEqual(self.methods()[start:], ["initialize", "session/load", "session/prompt"])

    def test_resume_mismatched_project_account_route_or_session_never_launches(self):
        first = self.run_mock()
        other = self.root / "other-project"
        other.mkdir()
        scopes = (contract.Scope(str(other)), contract.Scope(str(self.project), "mock:other-account"),
                  contract.Scope(str(self.project), route="provider-is-not-enabled"))
        with patch.object(contract.subprocess, "Popen") as spawn:
            for scope in scopes:
                with self.subTest(scope=scope), self.assertRaises(contract.ContractError):
                    self.runner.run(scope, "two", "Input", opt_in=True, session_id=first["session_id"])
            with self.assertRaises(contract.ContractError):
                self.run_mock("two", session_id="unknown-session")
        spawn.assert_not_called()

    def test_failed_resume_never_creates_new_session_or_replays_prompt(self):
        first = self.run_mock()
        self.scenario("resume_failed")
        start = len(self.methods())
        failed = self.run_mock("two", session_id=first["session_id"])
        self.assertEqual(failed["status"], "blocked")
        self.assertEqual(failed["reason"], "resume_failed")
        self.assertFalse(failed["prompt_attempted"])
        self.assertEqual(self.methods()[start:], ["initialize", "session/load"])
        replay = self.run_mock("two", session_id=first["session_id"])
        self.assertTrue(replay["duplicate"])
        self.assertEqual(self.methods()[start:], ["initialize", "session/load"])
        self.assertNotIn("synthetic-private", self.runner.state.read_bytes().decode(errors="ignore"))

    def test_missing_resume_capability_stops_before_load(self):
        first = self.run_mock()
        self.scenario("resume_unsupported")
        start = len(self.methods())
        receipt = self.run_mock("two", session_id=first["session_id"])
        self.assertEqual(receipt["reason"], "resume_unsupported")
        self.assertEqual(self.methods()[start:], ["initialize"])

    def test_completed_duplicate_is_local_and_conflicting_key_is_rejected(self):
        first = self.run_mock()
        with patch.object(contract.subprocess, "Popen") as spawn:
            duplicate = self.run_mock()
            with self.assertRaisesRegex(contract.ContractError, "different inputs"):
                self.runner.run(self.scope, "one", "Different", opt_in=True)
        spawn.assert_not_called()
        self.assertEqual(duplicate["answer"], first["answer"])
        self.assertTrue(duplicate["duplicate"])

    def test_permissions_are_cancelled_even_if_only_allow_option_is_offered(self):
        self.scenario("permission")
        receipt = self.run_mock()
        self.assertEqual(receipt["status"], "returned")
        self.assertEqual(receipt["permissions_denied"], 1)
        self.assertIn("permission_denied", self.methods())

    def test_unadvertised_file_request_is_denied_and_aborts_turn(self):
        self.scenario("forbidden_request")
        receipt = self.run_mock()
        self.assertEqual(receipt["status"], "delivery_unknown")
        self.assertEqual(receipt["reason"], "forbidden_client_request")
        self.assertEqual(receipt["answer"], "")

    def test_disconnect_malformed_size_wrong_session_and_partial_are_not_success(self):
        reasons = {"disconnect": "disconnected", "malformed": "malformed_event",
                   "oversize": "output_size_limit", "session_mismatch": "session_identity_mismatch",
                   "partial": "disconnected"}
        for scenario, reason in reasons.items():
            with self.subTest(scenario=scenario):
                self.scenario(scenario)
                receipt = self.run_mock(scenario)
                self.assertEqual(receipt["status"], "delivery_unknown")
                self.assertEqual(receipt["reason"], reason)
                self.assertEqual(receipt["answer"], "")
                start = len(self.methods())
                self.assertTrue(self.run_mock(scenario)["duplicate"])
                self.assertEqual(len(self.methods()), start)

    def test_incomplete_terminal_response_is_failed_not_returned(self):
        self.scenario("incomplete")
        receipt = self.run_mock()
        self.assertEqual(receipt["status"], "failed")
        self.assertTrue(receipt["response_received"])
        self.assertEqual(receipt["answer"], "")

    def test_total_output_limit_applies_across_individually_valid_frames(self):
        self.scenario("total_limit")
        receipt = self.run_mock()
        self.assertEqual(receipt["reason"], "output_size_limit")
        self.assertEqual(receipt["status"], "delivery_unknown")
        self.assertEqual(receipt["answer"], "")

    def test_malformed_protocol_version_stops_before_session_creation(self):
        self.scenario("bad_protocol")
        receipt = self.run_mock()
        self.assertEqual(receipt["status"], "blocked")
        self.assertEqual(receipt["reason"], "incompatible_protocol")
        self.assertEqual(self.methods(), ["initialize"])

    def test_cleanup_uncertainty_keeps_final_result_but_blocks_new_owner(self):
        original = contract.Wire.close
        def close_then_report_failure(wire):
            original(wire)  # Actual fixture is reaped; simulate an uncertain cleanup report.
            raise OSError("synthetic-private-cleanup-error")
        with patch.object(contract.Wire, "close", close_then_report_failure):
            receipt = self.run_mock()
        self.assertEqual(receipt["status"], "returned")
        self.assertEqual(receipt["cleanup_status"], "unverified")
        with self.assertRaisesRegex(contract.ContractError, "unresolved attempt"):
            self.run_mock("next")
        self.assertNotIn("synthetic-private", self.runner.state.read_bytes().decode(errors="ignore"))

    def test_timeout_kills_owned_process_and_keeps_delivery_uncertain(self):
        self.scenario("timeout")
        spawned = []
        original = contract.subprocess.Popen
        def spawn(*args, **kwargs):
            process = original(*args, **kwargs)
            spawned.append(process)
            return process
        started = time.monotonic()
        with patch.object(contract.subprocess, "Popen", side_effect=spawn):
            receipt = self.run_mock(timeout=0.4)
        self.assertLess(time.monotonic() - started, 6)
        self.assertEqual(receipt["status"], "delivery_unknown")
        self.assertEqual(receipt["reason"], "timeout")
        self.assertTrue(all(process.poll() is not None for process in spawned))
        self.assertFalse(receipt["remote_cancellation_verified"])

    def test_concurrent_duplicate_and_cancel_do_not_launch_another_owner(self):
        self.scenario("timeout")
        cancel, results = threading.Event(), []
        thread = threading.Thread(target=lambda: results.append(self.run_mock(cancelled=cancel)))
        thread.start()
        try:
            deadline = time.monotonic() + 2
            while "session/prompt" not in self.methods() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertIn("session/prompt", self.methods())
            duplicate = self.run_mock()
            self.assertEqual(duplicate["status"], "in_progress")
            self.assertTrue(duplicate["duplicate"])
            self.assertTrue(duplicate["prompt_attempted"])
            self.assertIsNone(duplicate["prompt_written"])
            with self.assertRaisesRegex(contract.ContractError, "unresolved attempt"):
                self.run_mock("other")
        finally:
            cancel.set()
            thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results[0]["reason"], "cancelled")
        self.assertEqual(results[0]["status"], "delivery_unknown")
        self.assertEqual(self.methods().count("session/prompt"), 1)

    def test_pre_cancel_and_prompt_size_stop_without_process(self):
        cancel = threading.Event()
        cancel.set()
        with patch.object(contract.subprocess, "Popen") as spawn:
            receipt = self.run_mock(cancelled=cancel)
            with self.assertRaisesRegex(contract.ContractError, "bounded"):
                self.runner.run(self.scope, "large", "x" * (contract.MAX_PROMPT + 1), opt_in=True)
        spawn.assert_not_called()
        self.assertEqual(receipt["status"], "blocked")
        self.assertFalse(receipt["prompt_attempted"])

    def test_unresolved_durable_attempt_blocks_new_work_after_reopen(self):
        self.run_mock()
        with self.runner.connect() as db:
            db.execute("UPDATE attempts SET active=1")
        reopened = contract.Experiment(self.runner.state, self.command)
        with self.assertRaisesRegex(contract.ContractError, "unresolved attempt"):
            reopened.run(self.scope, "new", "Input", opt_in=True)

    def test_no_secret_environment_or_raw_stderr_in_receipts(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "synthetic-secret", "HOME": "private-profile",
                                     "HTTPS_PROXY": "synthetic-secret"}):
            env = contract.mock_environment()
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertNotIn("HOME", env)
        self.assertNotIn("HTTPS_PROXY", env)
        self.scenario("stderr")
        receipt = self.run_mock()
        self.assertEqual(receipt["status"], "returned")
        self.assertNotIn("synthetic-private", self.runner.state.read_bytes().decode(errors="ignore"))


if __name__ == "__main__":
    unittest.main()
