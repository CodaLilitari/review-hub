"""One detached batch worker; provider helpers retain their original guards."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from .core import Hub, ACTIVE, atomic_json, digest, encoded, now
from .attachments import verify_files, manifest_digest


def contain_worker():
    """Windows job lifetime contains descendants if the worker itself dies.

    This is process-lifetime containment, not filesystem/network sandboxing.
    Child cancellation also uses taskkill /T; the lifetime job is the crash guard.
    """
    if os.name != "nt":
        return None
    import win32api
    import win32job
    job = win32job.CreateJobObject(None, "")
    limits = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
    limits["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, limits)
    win32job.AssignProcessToJobObject(job, win32api.GetCurrentProcess())
    return job


def terminate_tree(process):
    if process.poll() is not None:
        return
    if os.name == "nt":
        command = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32/taskkill.exe"
        subprocess.run([str(command), "/PID", str(process.pid), "/T", "/F"],
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=20, creationflags=subprocess.CREATE_NO_WINDOW, shell=False)
        if process.poll() is None:
            process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=20)


def load_helper(path):
    spec = importlib.util.spec_from_file_location("pinned_review_helper", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_job(hub: Hub, job_id: str):
    process = None
    data = None
    try:
        with hub.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None or row["state"] != "prepared":
                return
            if row["cancel_requested"]:
                hub._update(c, row, state="cancelled", finished_at=now(), submission="not_started")
                return
            data = json.loads(row["data"])
            observation = c.execute(
                "SELECT revoked,expires FROM observations WHERE id=? AND provider=? AND project=?",
                (data["observation_id"], data["provider"], data["project"]),
            ).fetchone()
            if observation is None or observation["revoked"]:
                hub._update(c, row, state="blocked", submission="not_started", finished_at=now(),
                            error="Usage allowance revoked or missing before worker dispatch")
                return
            if data["observation_expires"] <= time.time() or observation["expires"] <= time.time():
                hub._update(c, row, state="blocked", submission="not_started", error="Usage observation expired before worker dispatch")
                return
            pin = hub._pins(data["provider"])
            if pin["sha256"] != data["helper_sha256"]:
                raise ValueError("Helper pin changed since this job was prepared")
            if pin["model"] != data["model"] or pin["effort"] != data["effort"]:
                raise ValueError("Model or effort changed since this job was prepared")
            directory = Path(data["evidence_directory"])
            request = directory / "packet.txt"
            if digest(request.read_bytes()) != data["packet_sha256"]:
                raise ValueError("Prepared packet changed; refusing dispatch")
            manifest = verify_files(directory, data.get("attachments", []))
            if manifest and manifest_digest(manifest) != data.get("attachment_manifest_sha256"):
                raise ValueError("Prepared attachment manifest changed; refusing dispatch")
            # Run the verified bytes, so another project's helper update cannot
            # silently change this job between validation and Python startup.
            runner = directory / "pinned_helper.py"
            helper_bytes = Path(pin["path"]).read_bytes()
            if digest(helper_bytes) != pin["sha256"]:
                raise ValueError("Helper changed during preparation")
            runner.write_bytes(helper_bytes)
            helper = load_helper(runner)
            env = helper.clean_environment() if data["provider"] == "claude" else helper.safe_env()
            output = directory / "provider"
            command = [sys.executable, "-I", str(runner), "--prompt-file", str(request),
                       "--output-dir", str(output), "--model", pin["model"],
                       "--effort", pin["effort"], "--timeout", str(data["timeout"])]
            data = hub._update(c, row, state="running", started_at=now(),
                               submission="local_helper_launch_pending", worker_pid=os.getpid())
        flags = {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        with (directory / "helper.stdout.txt").open("wb") as stdout, (directory / "helper.stderr.txt").open("wb") as stderr:
            process = subprocess.Popen(command, cwd=str(directory), env=env, stdin=subprocess.DEVNULL,
                                       stdout=stdout, stderr=stderr, shell=False, **flags)
            started = time.monotonic()
            stop = None
            while process.poll() is None:
                with hub.connect() as c:
                    row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
                    if row["cancel_requested"]:
                        stop = "cancelled_local_tree"
                    elif row["state"] != "running":
                        stop = "coordinator_state_changed"
                    c.execute("UPDATE jobs SET heartbeat=? WHERE id=?", (time.time(), job_id))
                if time.monotonic() - started > data["timeout"] + 180:
                    stop = "outer_deadline"
                if stop:
                    terminate_tree(process)
                    break
                time.sleep(0.25)
        metadata_path = output / "metadata.json"
        metadata = {}
        if metadata_path.is_file():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (ValueError, UnicodeError):
                pass
        delivery_fields = [metadata[key] for key in ("sent", "submission_attempted")
                           if metadata.get(key) is not None]
        attempted = next((value for value in delivery_fields if type(value) is bool), None)
        claims_completion = (metadata.get("status") == "completed"
                             and metadata.get("model_review_completed") is True)
        delivery_contradiction = (any(type(value) is not bool for value in delivery_fields)
                                  or (True in delivery_fields and False in delivery_fields)
                                  or (claims_completion and False in delivery_fields))
        contradiction = delivery_contradiction or any(metadata.get(key) not in allowed for key, allowed in {
            "response_stop_reason": (None, "end_turn", "stop_sequence"),
            "response_finish_reason": (None, "stop", "end_turn", "stop_sequence"),
            "response_terminal_reason": (None, "completed", "success", "end_turn", "stop_sequence"),
            "response_subtype": (None, "success"),
            "response_is_error": (None, False),
        }.items())
        successful = (not stop and not contradiction and process.returncode == 0 and metadata.get("status") == "completed"
                      and metadata.get("model_review_completed") is True)
        result_path = output / "result.txt"
        answer = result_path.read_text(encoding="utf-8") if result_path.is_file() else ""
        if successful and not answer.strip():
            successful = False
        if successful:
            state, submission = "returned", "completed_response_received"
        elif delivery_contradiction:
            state, submission = "delivery_unknown", "conflicting_helper_submission_receipt"
        elif attempted is False:
            state, submission = "blocked", "not_sent_by_helper"
        elif not stop and (contradiction or metadata.get("status") in {"review_failed", "response_received_unverified"}):
            state, submission = "failed", "response_received_not_successful"
        else:
            state, submission = "delivery_unknown", "attempt_or_completion_uncertain"
        # Only the final answer is available via MCP. Raw evidence remains
        # private on disk and is never included in normal tool responses.
        if answer:
            (directory / "answer.txt").write_text(answer, encoding="utf-8")
        models = metadata.get("verified_response_models", [])
        if not isinstance(models, list):
            models = []
        with hub.connect() as c:
            row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            hub._update(c, row, state=state, submission=submission, finished_at=now(),
                        helper_exit_code=process.returncode, helper_status=metadata.get("status", "missing_receipt"),
                        verified_response_models=models, local_stop_reason=stop,
                        contradictory_completion_fields=contradiction,
                        contradictory_submission_fields=delivery_contradiction,
                        provider_session_id=metadata.get("session_id"),
                        error=None if successful else "Inspect the local helper receipt before retrying; no automatic retry was made",
                        answer_available=bool(answer.strip()),
                        attachment_delivery=("embedded_text_response_received" if successful else "see_submission_state") if data.get("attachments") else "no_attachments",
                        provider_resume=False)
    except BaseException as exc:
        if process is not None and process.poll() is None:
            try:
                terminate_tree(process)
            except Exception:
                pass
        with hub.connect() as c:
            row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is not None:
                hub._update(c, row, state="delivery_unknown" if process is not None else "blocked",
                            submission="uncertain" if process is not None else "not_started", finished_at=now(),
                            error=f"Worker stopped: {type(exc).__name__}; inspect evidence before retrying")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--batch", required=True)
    args = parser.parse_args()
    hub = Hub(args.state_dir)
    with hub.connect() as c:
        jobs = [r["id"] for r in c.execute("SELECT id FROM jobs WHERE batch_id=? AND state='prepared'", (args.batch,))]
    try:
        lifetime_job = contain_worker()
    except Exception:
        with hub.connect() as c:
            for job in jobs:
                row = c.execute("SELECT * FROM jobs WHERE id=?", (job,)).fetchone()
                hub._update(c, row, state="blocked", submission="not_started", error="Could not establish Windows descendant lifetime containment")
        return 1
    with ThreadPoolExecutor(max_workers=max(1, len(jobs))) as pool:
        list(pool.map(lambda job: run_job(hub, job), jobs))
    # Keep the lifetime Job Object handle alive through every completed receipt.
    _ = lifetime_job
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
