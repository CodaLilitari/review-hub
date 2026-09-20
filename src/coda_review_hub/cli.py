"""JSON-oriented command line interface; policy and execution live in core."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .core import Hub


def _payload(filename: str, required: set[str], optional: set[str] | None = None) -> dict[str, Any]:
    payload = json.loads(Path(filename).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("The UTF-8 JSON payload must be an object.")
    missing = required - payload.keys()
    unknown = payload.keys() - required - (optional or set())
    if missing:
        raise ValueError("Missing payload fields: " + ", ".join(sorted(missing)))
    if unknown:
        raise ValueError("Unknown payload fields: " + ", ".join(sorted(unknown)))
    return payload


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(
        description="Coordinate bounded subscription reviews; no automatic API fallback."
    )
    command.add_argument("--state-dir", type=Path, help="Directory for local hub state.")
    commands = command.add_subparsers(dest="command", required=True)
    commands.add_parser("routes", help="List route capabilities without sending a prompt.")
    commands.add_parser("identity-status", help="Read saved naming choices; unconfigured outbound work is blocked.")
    for name, help_text in (
        ("configure-identity", "Save checked user naming choices locally; this replaces the full profile."),
        ("observe-usage", "Record a coordinator attestation from a recent actual usage UI; not a provider probe."),
        ("submit", "Queue bounded reviews and return IDs without waiting for model completion."),
        ("handoff", "Prepare a scoped conversation handoff; this does not send it."),
        ("record-handoff-result", "Record coordinator-observed app output; not automated delivery verification."),
    ):
        child = commands.add_parser(name, help=help_text)
        child.add_argument("jsonfile", help="Exact UTF-8 JSON payload file.")
    for name in ("jobs", "result", "cancel", "attachment-files"):
        child = commands.add_parser(name)
        child.add_argument("--project", required=True)
        if name == "jobs":
            child.add_argument("--batch-id")
        else:
            child.add_argument("--job-id", required=True)
        if name == "result":
            child.add_argument("--offset", type=int, default=0)
            child.add_argument("--limit", type=int, default=12000)
        if name == "attachment-files":
            child.add_argument("--direction", choices=("input", "output"), default="input")
    return command


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        hub = Hub(state_dir=args.state_dir)
        if args.command == "routes":
            value = hub.routes()
        elif args.command == "identity-status":
            value = hub.identity_status()
        elif args.command == "configure-identity":
            value = hub.configure_identity(**_payload(args.jsonfile, {"evidence"}, {
                "agent_name", "user_name", "collaborators", "aliases", "context_notes",
            }))
        elif args.command == "observe-usage":
            value = hub.observe_usage(**_payload(args.jsonfile, {
                "provider", "project", "observed_at", "evidence", "included_available",
                "paid_usage_disabled",
            }, {"max_jobs"}))
        elif args.command == "submit":
            value = hub.submit(**_payload(args.jsonfile, {"project", "requests", "idempotency_key"}))
        elif args.command == "jobs":
            value = hub.jobs(args.project, batch_id=args.batch_id)
        elif args.command == "result":
            value = hub.result(args.project, args.job_id, offset=args.offset, limit=args.limit)
        elif args.command == "cancel":
            value = hub.cancel(args.project, args.job_id)
        elif args.command == "attachment-files":
            value = hub.attachment_files(args.project, args.job_id, direction=args.direction)
        elif args.command == "record-handoff-result":
            value = hub.record_handoff_result(**_payload(args.jsonfile, {
                "project", "job_id", "response", "evidence", "conversation_ref",
            }, {"acknowledgment", "observed_attachment_ids", "attachment_evidence", "returned_files", "artifact_evidence"}))
        else:
            value = hub.handoff(**_payload(args.jsonfile, {"project", "provider", "prompt"}, {"conversation_ref", "attachments"}))
    except (ValueError, TypeError, OSError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 2
    print(json.dumps(value, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
