#!/usr/bin/env python3
"""Pin the reviewed official Windows CLI and create guarded checker settings.

No CLI is launched, credential storage is accessed, or model request is sent.
Existing configuration/profile paths are preserved and refused.
"""
import argparse
import json
from pathlib import Path

import antigravity_check as adapter


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=adapter.DEFAULT_CONFIG)
    args = parser.parse_args(argv)
    adapter.no_links(args.exe.absolute())
    exe, profile, config_path = args.exe.resolve(strict=True), args.profile.absolute(), args.config.absolute()
    for path in (exe, profile, config_path):
        adapter.no_links(path)
    if config_path.exists() or profile.exists():
        parser.error("Configuration and dedicated profile must both be new paths")
    if not exe.is_file() or adapter.sha(exe.read_bytes()) != adapter.TRUSTED_RUNTIME_SHA256:
        parser.error("Executable is not the reviewed official Antigravity release")
    if profile == Path.home() or profile == Path(profile.anchor):
        parser.error("Choose a dedicated Antigravity profile")
    value = {"version": adapter.VERSION, "exe": str(exe), "exe_sha256": adapter.TRUSTED_RUNTIME_SHA256,
             "profile": str(profile)}
    (profile / ".gemini/antigravity-cli").mkdir(parents=True)
    adapter.write_json(profile / ".gemini/antigravity-cli/settings.json", adapter.settings())
    agent_dir = profile / ".gemini/config/agents"
    agent_dir.mkdir(parents=True)
    (agent_dir / f"{adapter.AGENT}.md").write_text(adapter.AGENT_MARKDOWN, encoding="utf-8")
    adapter.write_json(profile / ".gemini/config/hooks.json", adapter.hook_settings())
    adapter.write_json(profile / ".gemini/config/review-hub-deny.json", adapter.HOOK_RESPONSE)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    adapter.write_json(config_path, value)
    adapter.load_config(config_path)
    adapter.check_profile(profile)
    print(json.dumps({"configured": True, "config": str(config_path), "profile": str(profile),
                      "authenticated": False, "live_readiness": "not_checked", "sent": False,
                      "version": adapter.VERSION}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
