#!/usr/bin/env python3
"""Open the official CLI's Google login using the hub's dedicated guarded home.

Run interactively in your own terminal. Complete the browser's account/consent
choice yourself, then exit the CLI. This script supplies no model prompt and
never copies credentials from another app. Configuration and runtime are pinned.
"""
import argparse
from pathlib import Path
import subprocess
import tempfile

import gemini_check as adapter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=adapter.DEFAULT_CONFIG)
    args = parser.parse_args()
    config = adapter.load_config(args.config)
    adapter.check_profile(Path(config["profile"]), require_auth=False)
    with tempfile.TemporaryDirectory(prefix="reviewhub-gemini-login-") as temp:
        work = Path(temp)
        command, env = adapter.prepare_runtime(config, work)
        env.pop("NO_BROWSER", None)
        # This is an interactive, explicitly invoked user login launcher only.
        return subprocess.call(command, cwd=str(work), env=env, shell=False)


if __name__ == "__main__":
    raise SystemExit(main())
