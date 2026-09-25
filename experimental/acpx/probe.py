"""Run the bundled mock contract, never a provider or acpx installation."""
import argparse
import json
from pathlib import Path
import tempfile

from contract import Experiment, MockCommand, Scope

def successful(receipt, session_id=None):
    if not isinstance(receipt, dict) or receipt.get("status") != "returned":
        return False
    ident = receipt.get("session_id")
    return isinstance(ident, str) and bool(ident.strip()) and (session_id is None or ident == session_id)


def run_probe(opt_in):
    report = {"experiment": "mock-only; acpx package and providers not invoked"}
    with tempfile.TemporaryDirectory(prefix="review-hub-acp-mock-") as directory:
        root = Path(directory)
        project = root / "synthetic-project"
        project.mkdir()
        runner = Experiment(root / "state.sqlite3", MockCommand.reviewed())
        first = runner.run(Scope(str(project)), "first", "Synthetic input only", opt_in=opt_in)
        report["new_session"] = first
        if not successful(first):
            return 1, report
        session_id = first["session_id"]
        duplicate = runner.run(Scope(str(project)), "first", "Synthetic input only", opt_in=opt_in)
        report["duplicate"] = duplicate
        if not successful(duplicate, session_id) or duplicate.get("duplicate") is not True:
            return 1, report
        resumed = runner.run(Scope(str(project)), "second", "Synthetic follow-up", opt_in=opt_in,
                             session_id=session_id)
        report["resumed"] = resumed
        return (0 if successful(resumed, session_id) else 1), report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-mock-command", action="store_true", required=True)
    args = parser.parse_args(argv)
    status, report = run_probe(args.allow_mock_command)
    print(json.dumps(report, indent=2))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
