"""Offline cancellation isolation: one shared worker, two real fake-helper processes."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_core import FAKE_HELPER, core, process_alive, wait_for, worker, seed_models


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


class CancelSiblingTests(unittest.TestCase):
    def test_cancelling_one_helper_tree_leaves_sibling_running_and_returning(self):
        with tempfile.TemporaryDirectory(prefix="coda-cancel-sibling-") as temporary:
            root = Path(temporary)
            package = root / "offline-package"
            source = package / "src" / "coda_review_hub"
            source.mkdir(parents=True)
            for name in ("__init__.py", "core.py", "worker.py", "attachments.py", "identity.py", "models.py"):
                shutil.copy2(PACKAGE_ROOT / "src" / "coda_review_hub" / name, source / name)
            # Reuse the existing offline fixture, with a local release gate so
            # the sibling cannot finish before cancellation has been observed.
            gate = '''    if "MODE:GATE" in packet:
        deadline = time.monotonic() + 15
        while not (root / "release-fixture").exists():
            if time.monotonic() >= deadline:
                return 2
            time.sleep(0.05)
'''
            helper_text = FAKE_HELPER.replace('    if "MODE:SLOW" in packet:\n', gate + '    if "MODE:SLOW" in packet:\n')
            self.assertNotEqual(helper_text, FAKE_HELPER)
            helper = package / "offline_helper.py"
            helper.write_text(helper_text, encoding="utf-8")
            pins = {
                provider: {"path": str(helper), "sha256": core.digest(helper.read_bytes()),
                           "model": "offline-" + provider, "effort": "max"}
                for provider in ("claude-code", "grok")
            }
            (package / "helpers.json").write_text(json.dumps(pins), encoding="utf-8")
            project = root / "project"
            project.mkdir()
            with patch.object(core, "BASE", package):
                hub = core.Hub(root / "state")
                hub.configure_identity(
                    agent_name="FixtureAgent", user_name="FixtureUser",
                    evidence="Explicit synthetic names for isolated cancellation tests; no real identity.",
                )
                seed_models(hub)
                for provider in ("claude-code", "grok"):
                    hub.observe_usage(provider, str(project), datetime.now(timezone.utc).isoformat(),
                                      "Offline fixture only: synthetic included allowance, no real account.", True, True)
                with patch.object(hub, "_launch"):
                    batch = hub.submit(str(project), [
                        {"provider": "claude-code", "prompt": "Synthetic MODE:CHILD cancellation target.", "timeout": 20},
                        {"provider": "grok", "prompt": "Synthetic MODE:GATE surviving sibling.", "timeout": 20},
                    ], "cancel-only-one")
                jobs = {job["provider"]: job for job in batch["jobs"]}
                cancelled_dir = Path(jobs["claude-code"]["evidence_directory"])
                sibling_dir = Path(jobs["grok"]["evidence_directory"])
                env = {key: value for key, value in os.environ.items()
                       if key.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC", "PATHEXT"}}
                env.update({"PYTHONPATH": str(package / "src"), "PYTHONDONTWRITEBYTECODE": "1",
                            "HOME": str(root / "empty-home"), "USERPROFILE": str(root / "empty-home")})
                flags = ({"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
                         if os.name == "nt" else {"start_new_session": True})
                with (root / "worker.log").open("wb") as log:
                    process = subprocess.Popen(
                        [sys.executable, "-B", "-m", "coda_review_hub.worker", "--state-dir", str(hub.state),
                         "--batch", batch["batch_id"]],
                        cwd=package, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log, **flags,
                    )
                    try:
                        wait_for(lambda: (cancelled_dir / "grandchild.json").is_file()
                                 and (sibling_dir / "started.json").is_file())
                        cancelled_pid = json.loads((cancelled_dir / "started.json").read_text())["pid"]
                        child_pid = json.loads((cancelled_dir / "grandchild.json").read_text())["pid"]
                        sibling_pid = json.loads((sibling_dir / "started.json").read_text())["pid"]
                        running = {job["provider"]: job for job in hub.jobs(str(project), batch["batch_id"])}
                        self.assertEqual({job["state"] for job in running.values()}, {"running"})
                        self.assertEqual(running["claude-code"]["worker_pid"], running["grok"]["worker_pid"])
                        self.assertTrue(all(process_alive(pid) for pid in (cancelled_pid, child_pid, sibling_pid)))
                        self.assertEqual(hub.cancel(str(project), jobs["claude-code"]["id"])["state"], "cancellation_requested")

                        def cancelled_receipt():
                            row = hub.result(str(project), jobs["claude-code"]["id"])["job"]
                            return row if row.get("local_stop_reason") == "cancelled_local_tree" else None

                        cancelled = wait_for(cancelled_receipt)
                        wait_for(lambda: not process_alive(cancelled_pid) and not process_alive(child_pid))
                        sibling = hub.result(str(project), jobs["grok"]["id"])["job"]
                        self.assertEqual(cancelled["state"], "delivery_unknown")
                        self.assertEqual(sibling["state"], "running")
                        self.assertTrue(process_alive(sibling_pid))
                        self.assertIsNone(process.poll(), "Cancelling one job terminated the shared worker")
                        self.assertFalse((sibling_dir / "provider" / "metadata.json").exists())
                        (sibling_dir / "release-fixture").touch()
                        returned = wait_for(lambda: hub.result(str(project), jobs["grok"]["id"])
                                            if hub.result(str(project), jobs["grok"]["id"])["job"]["state"] == "returned"
                                            else None)
                        self.assertIn("synthetic only", returned["answer"])
                        self.assertEqual(returned["job"]["submission"], "completed_response_received")
                        self.assertIsNone(returned["job"]["local_stop_reason"])
                        self.assertEqual(process.wait(timeout=8), 0)
                        self.assertEqual(len((sibling_dir / "launches.txt").read_text().splitlines()), 1)
                    finally:
                        if process.poll() is None:
                            worker.terminate_tree(process)


if __name__ == "__main__":
    unittest.main()
