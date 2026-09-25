"""Offline hub/worker contracts. All dispatched helpers are temporary local fixtures.

No provider executable, account, API, or network is used. Temporary BASE/pins are
patched only inside tests; the production entry points have no helper override.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))
from coda_review_hub import core, worker


FAKE_HELPER = r"""
import argparse, json, os
from pathlib import Path
import subprocess, sys, time

def clean_environment():
    return {key: value for key, value in os.environ.items()
            if key.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC", "PATHEXT"}}

safe_env = clean_environment

def discover_models():
    return {"source": "official_cli", "runtime_version": "fixture-1", "evidence": "Synthetic offline model catalog for tests only.",
            "models": [
                {"id": "fixture-opus", "efforts": ["max", "low"]},
                {"id": "fixture-grok", "efforts": ["xhigh"]},
                {"id": "fixture-antigravity", "efforts": ["xhigh", "fixture-high"]}]}

def main():
    def offline(event, args):
        if event in {"socket.connect", "os.system"}:
            raise RuntimeError("Fake helper is offline")
    sys.addaudithook(offline)
    parser = argparse.ArgumentParser()
    for name in ("prompt-file", "output-dir", "model", "effort", "timeout"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    output = Path(args.output_dir)
    packet = Path(args.prompt_file).read_text(encoding="utf-8")
    output.mkdir()
    root = output.parent
    with (root / "launches.txt").open("a", encoding="utf-8") as log:
        log.write(str(os.getpid()) + "\n")
    (root / "started.json").write_text(json.dumps({"pid": os.getpid(), "time": time.time()}), encoding="utf-8")
    if "MODE:CHILD" in packet:
        child = subprocess.Popen([sys.executable, "-I", "-c", "import time; time.sleep(45)"],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        (root / "grandchild.json").write_text(json.dumps({"pid": child.pid}), encoding="utf-8")
        time.sleep(45)
    if "MODE:SLOW" in packet:
        time.sleep(0.8)
    status, code, completed, attempted = "completed", 0, True, True
    if "MODE:UNKNOWN" in packet:
        status, code, completed = "response_received_unverified", 2, False
    if "MODE:FAIL" in packet:
        status, code, completed = "review_failed", 1, False
    if "MODE:PREFLIGHT" in packet:
        status, code, completed, attempted = "preflight_failed", 1, False, False
    answer = json.dumps({"model": args.model, "effort": args.effort, "answer": "synthetic only"})
    (output / "result.txt").write_text(answer, encoding="utf-8")
    metadata = {"status": status, "model_review_completed": completed,
                "sent": attempted, "submission_attempted": attempted,
                "verified_response_models": [args.model],
                "stop_reason": "end_turn", "terminal_reason": "completed",
                "finished_time": time.time()}
    if "MODE:CONFLICT" in packet:
        metadata["response_terminal_reason"] = "error"
    (output / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    (output / "response.raw.json").write_text(json.dumps({"thought": "PRIVATE_TEST_REASONING"}), encoding="utf-8")
    return code

if __name__ == "__main__":
    raise SystemExit(main())
"""


def seed_models(hub, pins=None):
    """Explicit synthetic choices; never infer production user preferences."""
    catalog = [
        {"id": "fixture-opus", "efforts": ["max", "low"]},
        {"id": "fixture-grok", "efforts": ["xhigh"]},
        {"id": "fixture-antigravity", "efforts": ["xhigh", "fixture-high"]}]
    pins = pins or {"claude-code": {"model": "fixture-opus", "effort": "max"},
                    "grok": {"model": "fixture-grok", "effort": "xhigh"}}
    for provider, pin in pins.items():
        provider = core.LEGACY_AUTO.get(provider, provider)
        if provider not in core.AUTO or hub.models.status(provider)["selection"]:
            continue
        status = hub.models.record(provider, catalog, "Synthetic account catalog fixture only.", "official_cli")
        hub.select_model(provider, pin["model"], pin["effort"], status["catalog"]["fingerprint"], "Explicit synthetic test choice only.")
    for provider in core.HANDOFF:
        status = hub.models.record(provider, [{"id": "fixture-app", "efforts": ["default"]}],
                                   "Synthetic app picker observation only.", "observed_app")
        hub.select_model(provider, "fixture-app", "default", status["catalog"]["fingerprint"], "Explicit synthetic test choice only.")


def wait_for(predicate, seconds=8):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("Timed out waiting for offline fixture")


def process_alive(pid):
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


class HubTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="coda-hub-offline-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / "project"
        self.other_project = self.root / "other-project"
        self.project.mkdir()
        self.other_project.mkdir()
        self.package = self.root / "fake-package"
        self.package.mkdir()
        self.fake = self.package / "fake_helper.py"
        self.fake.write_bytes(FAKE_HELPER.encode("utf-8"))
        self.pins = {
            "claude-code": {"path": str(self.fake), "sha256": core.digest(self.fake.read_bytes()), "model": "fixture-opus", "effort": "max"},
            "grok": {"path": str(self.fake), "sha256": core.digest(self.fake.read_bytes()), "model": "fixture-grok", "effort": "xhigh"},
        }
        self.write_pins()
        base = patch.object(core, "BASE", self.package)
        base.start()
        self.addCleanup(base.stop)
        self.hub = core.Hub(self.root / "state")
        self.hub.configure_identity(
            agent_name="FixtureAgent", user_name="FixtureUser",
            evidence="Explicit synthetic names for isolated offline tests; no real identity or account.",
        )
        seed_models(self.hub, self.pins)
        launch = patch.object(self.hub, "_launch")
        self.launch = launch.start()
        self.addCleanup(launch.stop)

    def write_pins(self):
        (self.package / "helpers.json").write_text(json.dumps(self.pins), encoding="utf-8")
        if hasattr(self, "hub"):
            seed_models(self.hub, self.pins)

    def observe(self, provider="claude-code", jobs=1, project=None, age=0, **overrides):
        args = dict(provider=provider, project=str(project or self.project),
                    observed_at=(datetime.now(timezone.utc) - timedelta(seconds=age)).isoformat(),
                    evidence="Offline fixture: included allowance available; paid usage disabled.",
                    included_available=True, paid_usage_disabled=True, max_jobs=jobs)
        args.update(overrides)
        return self.hub.observe_usage(**args)

    def submit(self, provider="claude-code", prompt="Bounded synthetic question.", key="one", project=None):
        return self.hub.submit(str(project or self.project),
                               [{"provider": provider, "prompt": prompt, "timeout": 5}], key)

    def execute(self, batch):
        for item in batch["jobs"]:
            worker.run_job(self.hub, item["id"])
        return self.hub.jobs(str(self.project), batch["batch_id"])

    def remaining(self):
        with self.hub.connect() as c:
            return {r["id"]: r["remaining"] for r in c.execute("SELECT id,remaining FROM observations")}

    def test_fresh_observation_and_exact_packet_bytes(self):
        observation = self.observe()
        batch = self.submit(prompt="Line one.\nLine two: \u03c0.")
        item = batch["jobs"][0]
        directory = Path(item["evidence_directory"])
        self.assertEqual(core.digest((directory / "packet.txt").read_bytes()), item["packet_sha256"])
        self.assertEqual(core.digest((directory / "original.txt").read_bytes()), item["original_sha256"])
        self.assertEqual(item["observation_id"], observation["id"])
        self.assertFalse(item["claims_independently_verified"])
        self.assertEqual(self.remaining()[observation["id"]], 0)
        self.launch.assert_called_once_with(batch["batch_id"])

    def test_stale_future_naive_and_false_observations_refused(self):
        cases = [
            {"age": 3605},
            {"age": -120},
            {"observed_at": datetime.now().isoformat()},
            {"included_available": False},
            {"paid_usage_disabled": False},
            {"included_available": "true"},
            {"max_jobs": True},
            {"max_jobs": 0},
            {"max_jobs": 5},
        ]
        for values in cases:
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.observe(**values)
        self.assertEqual(self.remaining(), {})
        self.launch.assert_not_called()

    def test_fresh_negative_observation_revokes_prior_allowance(self):
        other_provider = self.observe("grok", jobs=2)
        for index, values in enumerate((
            {"included_available": False},
            {"paid_usage_disabled": False},
            {"included_available": False, "paid_usage_disabled": False},
        )):
            with self.subTest(values=values):
                earlier = self.observe(jobs=3)
                other_project = self.observe(project=self.other_project, jobs=2)
                with self.assertRaisesRegex(ValueError, "prior allowance revoked"):
                    self.observe(**values)
                remaining = self.remaining()
                self.assertEqual(remaining[earlier["id"]], 0)
                self.assertEqual(remaining[other_provider["id"]], 2)
                self.assertEqual(remaining[other_project["id"]], 0)
                with self.hub.connect() as c:
                    revoked = {r["id"]: r["revoked"] for r in c.execute("SELECT id,revoked FROM observations")}
                self.assertEqual(revoked[earlier["id"]], 1)
                self.assertEqual(revoked[other_project["id"]], 1)
                self.assertEqual(revoked[other_provider["id"]], 0)
                with self.assertRaises(ValueError):
                    self.submit(key=f"revoked-{index}")
                with self.assertRaises(ValueError):
                    self.submit(project=self.other_project, key=f"revoked-other-{index}")
        self.launch.assert_not_called()
        self.assertEqual(self.hub.jobs(str(self.project)), [])

    def test_legacy_observation_schema_migrates_without_changing_jobs(self):
        legacy_state = self.root / "legacy-state"
        legacy_state.mkdir()
        legacy_row = ("prior", str(self.project), "claude-code", 100.0, 200.0, 2, "Prior observation", "created")
        with closing(sqlite3.connect(legacy_state / "jobs.sqlite3")) as c, c:
            c.executescript("""
                CREATE TABLE observations (
                    id TEXT PRIMARY KEY, project TEXT NOT NULL, provider TEXT NOT NULL,
                    observed REAL NOT NULL, expires REAL NOT NULL, remaining INTEGER NOT NULL,
                    evidence TEXT NOT NULL, created TEXT NOT NULL);
                CREATE TABLE jobs (
                    id TEXT PRIMARY KEY, batch_id TEXT NOT NULL, project TEXT NOT NULL,
                    provider TEXT NOT NULL, state TEXT NOT NULL, data TEXT NOT NULL,
                    heartbeat REAL NOT NULL, cancel_requested INTEGER NOT NULL DEFAULT 0);
            """)
            c.execute("INSERT INTO observations VALUES (?,?,?,?,?,?,?,?)", legacy_row)
            c.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)",
                      ("active", "batch", str(self.project), "grok", "running", '{"preserve":"exact"}', 100.0, 0))
        migrated = core.Hub(legacy_state)
        core.Hub(legacy_state)  # Migration must also be idempotent.
        with migrated.connect() as c:
            observation = dict(c.execute("SELECT * FROM observations WHERE id='prior'").fetchone())
            active = dict(c.execute("SELECT * FROM jobs WHERE id='active'").fetchone())
        self.assertEqual(observation["revoked"], 0)
        self.assertEqual(observation["remaining"], 2)
        self.assertEqual(tuple(observation[name] for name in
                               ("id", "project", "provider", "observed", "expires", "remaining", "evidence", "created")),
                         legacy_row)
        self.assertEqual(active["state"], "running")
        self.assertEqual(active["data"], '{"preserve":"exact"}')
        self.assertEqual(active["heartbeat"], 100.0)

    def test_prepared_job_revoked_from_other_project_stays_blocked_after_new_positive(self):
        original_observation = self.observe(jobs=2)
        batch = self.submit(key="prepared-before-revoke")
        with self.assertRaisesRegex(ValueError, "prior allowance revoked"):
            self.observe(project=self.other_project, paid_usage_disabled=False)
        replacement = self.observe(jobs=1)
        self.assertNotEqual(original_observation["id"], replacement["id"])
        with patch.object(worker.subprocess, "Popen", side_effect=AssertionError("Revoked job must not launch")) as spawn:
            item = self.execute(batch)[0]
        spawn.assert_not_called()
        self.assertEqual(item["state"], "blocked")
        self.assertEqual(item["submission"], "not_started")
        self.assertIn("revoked", item["error"])
        self.assertFalse((Path(item["evidence_directory"]) / "pinned_helper.py").exists())
        self.assertEqual(self.remaining()[replacement["id"]], 1)
        newer = self.execute(self.submit(key="new-positive-job"))[0]
        self.assertEqual(newer["state"], "returned")
        self.assertEqual(newer["observation_id"], replacement["id"])
        with self.assertRaises(ValueError):
            self.submit(project=self.other_project, key="positive-is-not-account-wide")

    def test_timeout_requires_integer_seconds(self):
        self.observe()
        for value in (1.5, 5.0, "5", True, None, float("nan")):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "integer"):
                self.hub.submit(str(self.project), [{"provider": "claude-code", "prompt": "Offline.", "timeout": value}],
                                "invalid-timeout")
        self.launch.assert_not_called()
        self.assertEqual(self.hub.jobs(str(self.project)), [])
        self.assertEqual(list(self.remaining().values()), [1])

    def test_invalid_negative_observation_does_not_revoke_valid_allowance(self):
        earlier = self.observe(jobs=2)
        for values in (
            {"included_available": False, "age": 3605},
            {"paid_usage_disabled": False, "age": -120},
            {"included_available": False, "paid_usage_disabled": "false"},
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.observe(**values)
            self.assertEqual(self.remaining()[earlier["id"]], 2)
        self.launch.assert_not_called()

    def test_allowance_is_bounded_and_replacement_does_not_stack(self):
        first = self.observe(jobs=4)
        second = self.observe(jobs=2)
        self.assertEqual(self.remaining(), {first["id"]: 0, second["id"]: 2})
        for i in range(2):
            states = self.execute(self.submit(key=f"allowed-{i}"))
            self.assertEqual(states[0]["state"], "returned")
        with self.assertRaises(ValueError):
            self.submit(key="exhausted")
        self.assertEqual(self.remaining()[second["id"]], 0)

    def test_batch_preflight_all_or_none_when_second_observation_missing(self):
        observation = self.observe("claude-code")
        requests = [{"provider": "claude-code", "prompt": "First."}, {"provider": "grok", "prompt": "Second."}]
        with self.assertRaises(ValueError):
            self.hub.submit(str(self.project), requests, "two")
        self.assertEqual(self.hub.jobs(str(self.project)), [])
        self.assertEqual(self.remaining()[observation["id"]], 1)
        self.launch.assert_not_called()
        self.assertFalse((self.hub.state / "artifacts").exists())

    def test_batch_preflight_all_or_none_when_second_pin_changed(self):
        self.observe("claude-code")
        self.observe("grok")
        self.pins["grok"]["sha256"] = "0" * 64
        self.write_pins()
        with self.assertRaises(ValueError):
            self.hub.submit(str(self.project), [{"provider": p, "prompt": "Offline."} for p in ("claude-code", "grok")], "bad-pin")
        self.assertEqual(self.hub.jobs(str(self.project)), [])
        self.assertEqual(set(self.remaining().values()), {1})
        self.launch.assert_not_called()

    def test_idempotency_replay_consumes_once_and_conflict_refused(self):
        self.observe(jobs=2)
        first = self.submit(key="stable")
        replay = self.submit(key="stable")
        self.assertTrue(replay["reused"])
        self.assertEqual(first["batch_id"], replay["batch_id"])
        self.assertEqual(first["jobs"][0]["id"], replay["jobs"][0]["id"])
        self.assertEqual(list(self.remaining().values()), [1])
        self.launch.assert_called_once()
        with self.assertRaises(ValueError):
            self.submit(prompt="Different packet.", key="stable")

    def test_project_isolation_observation_result_cancel_and_listing(self):
        self.observe(project=self.project)
        with self.assertRaises(ValueError):
            self.submit(project=self.other_project)
        batch = self.submit()
        identifier = batch["jobs"][0]["id"]
        self.assertEqual(self.hub.jobs(str(self.other_project)), [])
        for action in (self.hub.result, self.hub.cancel):
            with self.subTest(action=action.__name__), self.assertRaises(ValueError):
                action(str(self.other_project), identifier)

    def test_arbitrary_provider_model_helper_and_duplicate_provider_refused(self):
        self.observe()
        cases = [
            [{"provider": "unknown", "prompt": "Question"}],
            [{"provider": "claude-code", "prompt": "Question", "model": "arbitrary"}],
            [{"provider": "claude-code", "prompt": "Question", "helper": "arbitrary"}],
            [{"provider": "claude-code", "prompt": "Question", "effort": "low"}],
            [{"provider": "claude-code", "prompt": "Question", "timeout": float("inf")}],
            [{"provider": "claude-code", "prompt": "Question"}, {"provider": "claude-code", "prompt": "Second"}],
        ]
        for i, requests in enumerate(cases):
            with self.subTest(requests=requests), self.assertRaises(ValueError):
                self.hub.submit(str(self.project), requests, str(i))
        self.launch.assert_not_called()

    def test_tampered_packet_refused_without_helper_start(self):
        self.observe()
        batch = self.submit()
        directory = Path(batch["jobs"][0]["evidence_directory"])
        (directory / "packet.txt").write_bytes(b"Different content")
        item = self.execute(batch)[0]
        self.assertEqual(item["state"], "blocked")
        self.assertEqual(item["submission"], "not_started")
        self.assertFalse((directory / "started.json").exists())

    def test_tampered_helper_refused_without_start(self):
        self.observe()
        batch = self.submit()
        directory = Path(batch["jobs"][0]["evidence_directory"])
        self.fake.write_bytes(self.fake.read_bytes() + b"\n# changed\n")
        item = self.execute(batch)[0]
        self.assertEqual(item["state"], "blocked")
        self.assertFalse((directory / "started.json").exists())

    def test_model_pin_change_cannot_silently_change_prepared_dispatch(self):
        self.observe()
        batch = self.submit()
        requested = batch["jobs"][0]["model"]
        self.pins["claude-code"]["model"] = "unexpected-new-model"
        self.write_pins()
        item = self.execute(batch)[0]
        if item["state"] == "returned":
            answer = json.loads(self.hub.result(str(self.project), item["id"])["answer"])
            self.assertEqual(answer["model"], requested)
        else:
            self.assertEqual(item["state"], "blocked")
            self.assertEqual(item["submission"], "not_started")

    def test_expired_before_dispatch_is_blocked(self):
        self.observe()
        batch = self.submit()
        identifier = batch["jobs"][0]["id"]
        with self.hub.connect() as c:
            row = c.execute("SELECT * FROM jobs WHERE id=?", (identifier,)).fetchone()
            self.hub._update(c, row, observation_expires=time.time() - 1)
        item = self.execute(batch)[0]
        self.assertEqual(item["state"], "blocked")
        self.assertEqual(item["submission"], "not_started")

    def test_success_returns_answer_without_reasoning_or_independent_verification(self):
        self.observe()
        item = self.execute(self.submit())[0]
        self.assertEqual(item["state"], "returned")
        result = self.hub.result(str(self.project), item["id"])
        self.assertFalse(result["job"]["claims_independently_verified"])
        self.assertIn("synthetic only", result["answer"])
        self.assertNotIn("PRIVATE_TEST_REASONING", json.dumps(result))
        self.assertEqual(result["job"]["verified_response_models"], ["fixture-opus"])

    def test_failed_unverified_and_preflight_receipts_do_not_become_success(self):
        for i, mode in enumerate(("FAIL", "UNKNOWN", "PREFLIGHT")):
            with self.subTest(mode=mode):
                self.observe()
                item = self.execute(self.submit(prompt=f"MODE:{mode}", key=f"mode-{i}"))[0]
                self.assertNotEqual(item["state"], "returned")
                self.assertFalse(item["claims_independently_verified"])
                if mode == "PREFLIGHT":
                    self.assertEqual(item["submission"], "not_sent_by_helper")
                else:
                    self.assertEqual(item["submission"], "response_received_not_successful")

    def test_contradictory_completion_metadata_is_not_success(self):
        self.observe()
        item = self.execute(self.submit(prompt="MODE:CONFLICT", key="contradiction"))[0]
        self.assertNotEqual(item["state"], "returned")
        self.assertTrue(item["contradictory_completion_fields"])
        self.assertFalse(item["claims_independently_verified"])

    def test_cancel_prepared_never_starts_a_helper(self):
        self.observe()
        batch = self.submit()
        identifier = batch["jobs"][0]["id"]
        self.hub.cancel(str(self.project), identifier)
        item = self.execute(batch)[0]
        self.assertEqual(item["state"], "cancelled")
        self.assertEqual(item["submission"], "not_started")
        self.assertFalse((Path(item["evidence_directory"]) / "started.json").exists())

    def test_stale_prepared_is_blocked_not_started_and_not_retried(self):
        self.observe(jobs=2)
        batch = self.submit(key="unstarted-orphan")
        identifier = batch["jobs"][0]["id"]
        with self.hub.connect() as c:
            c.execute("UPDATE jobs SET heartbeat=? WHERE id=?", (time.time() - 100, identifier))
        item = self.hub.jobs(str(self.project))[0]
        self.assertEqual(item["state"], "blocked")
        self.assertEqual(item["submission"], "not_started")
        directory = Path(item["evidence_directory"])
        self.assertFalse((directory / "started.json").exists())
        self.assertEqual(json.loads((directory / "job.json").read_text())["state"], "blocked")
        replay = self.submit(key="unstarted-orphan")
        self.assertTrue(replay["reused"])
        self.assertEqual(replay["jobs"][0]["state"], "blocked")
        self.assertEqual(replay["jobs"][0]["submission"], "not_started")
        worker.run_job(self.hub, identifier)
        self.assertFalse((directory / "started.json").exists())
        self.launch.assert_called_once()

    def test_stale_running_preserves_unknown_and_replay_does_not_resubmit(self):
        self.observe(jobs=2)
        batch = self.submit(key="orphan")
        identifier = batch["jobs"][0]["id"]
        with self.hub.connect() as c:
            row = c.execute("SELECT * FROM jobs WHERE id=?", (identifier,)).fetchone()
            self.hub._update(c, row, state="running", submission="local_helper_launch_pending")
            c.execute("UPDATE jobs SET heartbeat=? WHERE id=?", (time.time() - 100, identifier))
        item = self.hub.jobs(str(self.project))[0]
        self.assertEqual(item["state"], "delivery_unknown")
        self.assertNotEqual(item["submission"], "not_started")
        directory = Path(item["evidence_directory"])
        self.assertEqual(json.loads((directory / "job.json").read_text())["state"], "delivery_unknown")
        replay = self.submit(key="orphan")
        self.assertTrue(replay["reused"])
        self.assertEqual(replay["jobs"][0]["state"], "delivery_unknown")
        self.launch.assert_called_once()

    def test_two_providers_overlap_and_duplicate_worker_does_not_double_dispatch(self):
        for provider in ("claude-code", "grok"):
            self.observe(provider)
        batch = self.hub.submit(str(self.project), [{"provider": p, "prompt": "MODE:SLOW", "timeout": 5}
                                                    for p in ("claude-code", "grok")], "parallel")
        ids = [job["id"] for job in batch["jobs"]]
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(lambda identifier: worker.run_job(self.hub, identifier), [ids[0], ids[1], ids[0]]))
        items = self.hub.jobs(str(self.project), batch["batch_id"])
        self.assertEqual([j["state"] for j in items], ["returned", "returned"])
        spans = []
        for item in items:
            directory = Path(item["evidence_directory"])
            self.assertEqual(len((directory / "launches.txt").read_text().splitlines()), 1)
            start = json.loads((directory / "started.json").read_text())["time"]
            end = json.loads((directory / "provider" / "metadata.json").read_text())["finished_time"]
            spans.append((start, end))
        self.assertLess(max(start for start, end in spans), min(end for start, end in spans))

    def test_active_provider_is_serialized_across_projects(self):
        self.observe(project=self.project)
        self.observe(project=self.other_project)
        self.submit(project=self.project)
        with self.assertRaisesRegex(ValueError, "active job"):
            self.submit(project=self.other_project, key="other")

    @unittest.skipUnless(os.name == "nt", "Windows descendant cleanup contract")
    def test_running_cancellation_terminates_fake_helper_and_grandchild(self):
        self.observe()
        batch = self.submit(prompt="MODE:CHILD", key="cancel-tree")
        item = batch["jobs"][0]
        directory = Path(item["evidence_directory"])
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(worker.run_job, self.hub, item["id"])
            try:
                wait_for(lambda: (directory / "grandchild.json").is_file())
                parent_pid = json.loads((directory / "started.json").read_text())["pid"]
                child_pid = json.loads((directory / "grandchild.json").read_text())["pid"]
                self.assertTrue(process_alive(parent_pid))
                self.assertTrue(process_alive(child_pid))
                self.hub.cancel(str(self.project), item["id"])
                future.result(timeout=12)
                wait_for(lambda: not process_alive(parent_pid) and not process_alive(child_pid))
            finally:
                self.hub.cancel(str(self.project), item["id"])
                future.result(timeout=12)
        finished = self.hub.jobs(str(self.project), batch["batch_id"])[0]
        self.assertEqual(finished["state"], "delivery_unknown")
        self.assertEqual(finished["local_stop_reason"], "cancelled_local_tree")
        self.assertFalse(finished["claims_independently_verified"])

    @unittest.skipUnless(os.name == "nt" and importlib.util.find_spec("win32job") is not None,
                         "Windows worker crash containment requires declared pywin32")
    def test_worker_crash_job_object_terminates_descendants(self):
        self.observe()
        batch = self.submit(prompt="MODE:CHILD", key="worker-crash")
        item = batch["jobs"][0]
        directory = Path(item["evidence_directory"])
        bootstrap = (
            "import sys; from pathlib import Path; "
            "sys.path.insert(0, sys.argv[1]); "
            "from coda_review_hub import core, worker; "
            "core.BASE=Path(sys.argv[2]); "
            "sys.argv=['worker','--state-dir',sys.argv[3],'--batch',sys.argv[4]]; "
            "raise SystemExit(worker.main())"
        )
        log_path = self.root / "crash-worker.log"
        log = log_path.open("wb")
        self.addCleanup(log.close)
        child = subprocess.Popen([sys.executable, "-I", "-c", bootstrap, str(PACKAGE_ROOT / "src"),
                                  str(self.package), str(self.hub.state), batch["batch_id"]],
                                 stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                 creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW)
        pids = []
        try:
            wait_for(lambda: (directory / "grandchild.json").is_file() or child.poll() is not None)
            self.assertTrue((directory / "grandchild.json").is_file(),
                            "Worker exited before fake dispatch: " + log_path.read_text(encoding="utf-8")
                            + json.dumps(self.hub.jobs(str(self.project), batch["batch_id"])))
            pids = [json.loads((directory / filename).read_text())["pid"]
                    for filename in ("started.json", "grandchild.json")]
            self.assertTrue(all(process_alive(pid) for pid in pids))
            child.kill()  # Deliberately kill only the worker; its Job Object must kill descendants.
            child.wait(timeout=8)
            wait_for(lambda: all(not process_alive(pid) for pid in pids))
        finally:
            if child.poll() is None:
                worker.terminate_tree(child)
            for pid in pids:
                if process_alive(pid):
                    subprocess.run([str(Path(os.environ["SYSTEMROOT"]) / "System32" / "taskkill.exe"),
                                    "/PID", str(pid), "/T", "/F"], capture_output=True,
                                   creationflags=subprocess.CREATE_NO_WINDOW, timeout=10, check=False)
        with self.hub.connect() as c:
            c.execute("UPDATE jobs SET heartbeat=? WHERE id=?", (time.time() - 100, item["id"]))
        finished = self.hub.jobs(str(self.project), batch["batch_id"])[0]
        self.assertEqual(finished["state"], "delivery_unknown")


if __name__ == "__main__":
    unittest.main()
