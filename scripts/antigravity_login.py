#!/usr/bin/env python3
"""Run official interactive Antigravity sign-in in the guarded dedicated home.

Invoke in your own terminal and complete the account choice yourself. No model
prompt is supplied. Exit after authentication. Login is separate from readiness
and does not enable credit fallback or extract/copy another app's credentials.
"""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile

import antigravity_check as adapter


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=adapter.DEFAULT_CONFIG)
    args = parser.parse_args(argv)
    config = adapter.load_config(args.config)
    profile = Path(config["profile"])
    settings_path = profile / ".gemini/antigravity-cli/settings.json"
    with tempfile.TemporaryDirectory(prefix="reviewhub-antigravity-login-") as temp:
        work = Path(temp)
        command, env = adapter.prepare_runtime(config, work)
        try:
            # Explicitly invoked interactive login only. No background auth retry.
            code = subprocess.call(command + ["--agent", adapter.AGENT, "--model", adapter.MODEL,
                                              "--effort", "high"], cwd=str(work), env=env, shell=False)
        finally:
            # An interactive session can record its temporary folder under
            # trustedWorkspaces. These settings are helper-owned: restore the
            # reviewed content rather than widening what the checker accepts.
            adapter.no_links(settings_path)
            adapter.write_json(settings_path, adapter.settings())
    # Fail loudly here, not at the next review, if the runtime or profile drifted.
    adapter.load_config(args.config)
    adapter.check_profile(profile)
    print(json.dumps({"session_exit_code": code, "runtime_pin_verified": True,
                      "profile_checked": True, "settings_restored": True}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
