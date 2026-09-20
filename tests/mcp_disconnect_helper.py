"""Offline worker fixture. It cannot invoke a provider or open a connection."""

import argparse
import json
import os
from pathlib import Path
import sys
import time


def clean_environment():
    return {
        key: value for key, value in os.environ.items()
        if key.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC", "PATHEXT"}
    }


safe_env = clean_environment


def main():
    def offline(event, args):
        if event in {"socket.connect", "subprocess.Popen", "os.system", "os.posix_spawn"}:
            raise RuntimeError("Disconnect fixture forbids network and child processes")

    sys.addaudithook(offline)
    parser = argparse.ArgumentParser()
    for name in ("prompt-file", "output-dir", "model", "effort", "timeout"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    output = Path(args.output_dir)
    output.mkdir()
    root = output.parent
    with (root / "launches.txt").open("a", encoding="utf-8") as log:
        log.write(str(os.getpid()) + "\n")
    (root / "fixture-started.json").write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
    deadline = time.monotonic() + 15
    while not (root / "release-fixture").exists():
        if time.monotonic() >= deadline:
            return 2
        time.sleep(0.05)
    (output / "result.txt").write_text("Synthetic fixture completed; no provider contacted.", encoding="utf-8")
    (output / "metadata.json").write_text(json.dumps({
        "status": "completed", "model_review_completed": True,
        "sent": True, "verified_response_models": ["offline-fixture"],
        "response_stop_reason": "end_turn",
    }), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
