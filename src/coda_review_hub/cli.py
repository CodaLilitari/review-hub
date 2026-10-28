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
    caps = commands.add_parser('capabilities', help='Read static input/output/session capability contracts.')
    caps.add_argument('--provider')
    models = commands.add_parser("models", help="Read account model choices; --refresh probes a CLI without generation.")
    models.add_argument("--provider", required=True)
    models.add_argument("--refresh", action="store_true")
    choose = commands.add_parser("choose-model", help="Refresh and choose an observed model/mode and offered effort setting.")
    choose.add_argument("--provider", required=True)
    for name, help_text in (
        ("configure-identity", "Save checked user naming choices locally; this replaces the full profile."),
        ("record-models", "Record a fresh observation of a signed-in app's model picker."),
        ("select-model", "Save the user's explicit choice against the current catalog fingerprint."),
        ("observe-usage", "Record a coordinator attestation from a recent actual usage UI; not a provider probe."),
        ("submit", "Queue bounded reviews and return IDs without waiting for model completion."),
        ("handoff", "Prepare a scoped conversation handoff; this does not send it."),
        ("record-handoff-result", "Record coordinator-observed app output; not automated delivery verification."),
        ('record-review', 'Append normalized findings and check exact saved source citations.'),
        ('record-lineage', 'Record observed parent context; never sends or resumes.'),
        ('report', 'Render selected jobs to static HTML/Markdown; no provider requests.'),
    ):
        child = commands.add_parser(name, help=help_text)
        child.add_argument("jsonfile", help="Exact UTF-8 JSON payload file.")
        if name == 'report':
            child.add_argument('--output', type=Path, help='New exact report file inside the selected project; never overwrite.')
    for name in ("jobs", "result", "cancel", "attachment-files", 'review'):
        child = commands.add_parser(name)
        child.add_argument("--project", required=True)
        if name == "jobs":
            child.add_argument("--batch-id")
        else:
            child.add_argument("--job-id", required=True)
        if name == "result":
            child.add_argument("--offset", type=int, default=0)
            child.add_argument("--limit", type=int, default=12000)
            child.add_argument("--turn-id", default="")
        if name == "attachment-files":
            child.add_argument("--direction", choices=("input", "output"), default="input")
            child.add_argument("--turn-id", default="")
    return command


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        hub = Hub(state_dir=args.state_dir)
        if args.command == "routes":
            value = hub.routes()
        elif args.command == 'capabilities':
            value = hub.capabilities(args.provider)
        elif args.command == 'record-review':
            value = hub.record_review(**_payload(args.jsonfile, {'project', 'job_id', 'review', 'evidence'}))
        elif args.command == 'record-lineage':
            value = hub.record_lineage(**_payload(args.jsonfile, {'project', 'job_id', 'parent_job_id', 'kind', 'evidence'}, {'omitted_context'}))
        elif args.command == 'review':
            value = hub.review(args.project, args.job_id)
        elif args.command == 'report':
            payload = _payload(args.jsonfile, {'project', 'job_ids'}, {'format'})
            value = hub.comparison_report(**payload)
            if args.output:
                from .attachments import no_links, check_open_path
                from .core import project_path
                import os
                root = Path(project_path(payload['project']))
                target = args.output
                if not target.is_absolute() or '..' in target.parts or (os.name == 'nt' and ':' in str(target)[2:]):
                    raise ValueError('Report output must be an exact absolute project path without traversal/streams')
                target.relative_to(root)
                no_links(target.parent, root)
                with target.open('xb') as stream:
                    check_open_path(stream, target)
                    stream.write(value['content'].encode('utf-8'))
                value = {k: v for k, v in value.items() if k != 'content'}
                value['output_path'] = str(target)
        elif args.command == "identity-status":
            value = hub.identity_status()
        elif args.command == "models":
            value = hub.refresh_models(args.provider) if args.refresh else hub.model_status(args.provider)
        elif args.command == "choose-model":
            if not sys.stdin.isatty():
                raise ValueError("choose-model needs an interactive terminal; use models and select-model for a coordinator")
            status = hub.model_status(args.provider)
            # A coordinator must inspect consumer apps separately. Use its
            # fresh control/mode observation here; CLI routes always rediscover.
            if status["refresh_required"] or not status["catalog"] or status["catalog"]["source"] != "observed_app":
                status = hub.refresh_models(args.provider)
            if status["refresh_required"]:
                raise ValueError(status["next"])
            catalog = status["catalog"]
            update = catalog.get("runtime_update")
            if update and update.get("update_available") is True:
                print("A newer official app release is available: installed " + update.get("installed_version", "unknown")
                      + "; latest " + update.get("latest_version", "unknown") + ". This installed client's catalog can omit newer models. "
                      "You may choose from these current options, or update the app and refresh the catalog first.", file=sys.stderr)
            elif update and update.get("status") == "unavailable":
                print("The latest app release could not be checked. These choices reflect the installed client's account catalog.", file=sys.stderr)
            model = _choose("Choose the observed model/mode for " + args.provider, catalog["models"], lambda item: item["label"] + " (" + item["id"] + ")")
            effort = _choose("Choose its offered effort setting (default if not adjustable)", model["efforts"], str)
            value = hub.select_model(args.provider, model["id"], effort, catalog["fingerprint"],
                                     "User selected observed model/mode and effort descriptors in the interactive CLI; no backend verification implied.")
        elif args.command == "record-models":
            value = hub.record_models(**_payload(args.jsonfile, {"provider", "models", "evidence", "observed_at"}, {"selection_policy"}))
        elif args.command == "select-model":
            value = hub.select_model(**_payload(args.jsonfile, {"provider", "model", "effort", "catalog_fingerprint", "evidence"}, {"fallback_observation", "selection_basis", "override_evidence"}))
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
            value = hub.result(args.project, args.job_id, offset=args.offset, limit=args.limit, turn_id=args.turn_id)
        elif args.command == "cancel":
            value = hub.cancel(args.project, args.job_id)
        elif args.command == "attachment-files":
            value = hub.attachment_files(args.project, args.job_id, direction=args.direction, turn_id=args.turn_id)
        elif args.command == "record-handoff-result":
            value = hub.record_handoff_result(**_payload(args.jsonfile, {
                "project", "job_id", "response", "evidence", "conversation_ref",
            }, {"acknowledgment", "observed_attachment_ids", "attachment_evidence", "returned_files", "artifact_evidence", "observed_model", "observed_mode", "completion_observation", "previous_turn_id"}))
        else:
            value = hub.handoff(**_payload(args.jsonfile, {"project", "provider", "prompt"}, {"conversation_ref", "attachments"}))
    except (ValueError, TypeError, OSError, EOFError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 2
    print(json.dumps(value, ensure_ascii=True))
    return 0


def _choose(label, options, describe):
    print(label, file=sys.stderr)
    for index, item in enumerate(options, 1):
        print(f"  {index}. {describe(item)}", file=sys.stderr)
    while True:
        print("Enter a number: ", file=sys.stderr, end="", flush=True)
        answer = input().strip()
        if answer.isdecimal() and 1 <= int(answer) <= len(options):
            return options[int(answer) - 1]
        print("Please select one of the listed options.", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
