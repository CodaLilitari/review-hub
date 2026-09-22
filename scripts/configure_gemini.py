#!/usr/bin/env python3
"""Pin an already-installed official Gemini CLI and create an empty OAuth home.

No credentials are requested, copied or read, and no model request is sent.
Existing configurations/profiles are refused. Run the official login separately.
"""
import argparse
import json
from pathlib import Path

import gemini_check as adapter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--cli-root", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=adapter.DEFAULT_CONFIG)
    args = parser.parse_args()
    node = args.node.resolve(strict=True)
    root = args.cli_root.resolve(strict=True)
    profile = args.profile.resolve()
    config = args.config.resolve()
    if config.exists() or profile.exists():
        parser.error("Configuration and dedicated profile must both be new paths")
    package = json.loads((root / "package.json").read_text(encoding="utf-8"))
    if package.get("name") != "@google/gemini-cli" or package.get("version") != adapter.VERSION:
        parser.error("Install the reviewed official @google/gemini-cli version first")
    if not node.is_file() or not (root / "bundle/gemini.js").is_file():
        parser.error("Missing Node runtime or official CLI entry point")
    value = {"version": adapter.VERSION, "node": str(node), "node_sha256": adapter.sha(node.read_bytes()),
             "cli_root": str(root), "cli_tree_sha256": adapter.tree_digest(root), "profile": str(profile)}
    adapter.check_profile(profile, require_auth=False)
    (profile / ".gemini").mkdir(parents=True)
    adapter.write_json(profile / ".gemini/settings.json", {"security": {"auth": {"selectedType": "oauth-personal"}}})
    config.parent.mkdir(parents=True, exist_ok=True)
    adapter.write_json(config, value)
    adapter.load_config(config)
    adapter.check_profile(profile, require_auth=False)
    print(json.dumps({"configured": True, "config": str(config), "profile": str(profile),
                      "authenticated": False, "sent": False, "version": adapter.VERSION}))


if __name__ == "__main__":
    raise SystemExit("Retired personal-subscription route. Use configure_antigravity.py and antigravity_check.py; existing Gemini history and profiles are preserved.")
