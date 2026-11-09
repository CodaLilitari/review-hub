"""Official MCP SDK stdio surface for the local review hub."""

import argparse
import atexit
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, field_validator

from . import __version__
from .core import AUTO, Hub
from .worker import contain_worker


AttachmentPaths = Annotated[list[StrictStr], Field(max_length=16, strict=True)]
AttachmentIds = Annotated[list[StrictStr], Field(max_length=16, strict=True)]
IdentityMapping = Annotated[dict[StrictStr, StrictStr], Field(max_length=32, strict=True)]
CheckList = Annotated[list[Annotated[StrictStr, Field(min_length=1, max_length=500)]], Field(max_length=64, strict=True)]


class CompletionObservation(BaseModel):
    """Observed completion evidence, not proof obtained by the Hub."""

    model_config = ConfigDict(extra="forbid", strict=True)
    status: Literal["unknown", "completed", "incomplete", "tool_limit", "output_limit",
                    "cancelled", "provider_error", "delivery_unknown"] = "unknown"
    provider_stop_reason: Annotated[StrictStr, Field(max_length=128)] = ""
    continue_available: StrictBool = False
    outstanding_checks: CheckList = Field(default_factory=list)
    resolved_checks: CheckList = Field(default_factory=list)


@asynccontextmanager
async def server_lifespan(_server: MCPServer):
    """Bind Windows workers to this dedicated stdio server before it accepts work.

    A client's post-spawn job assignment can race a Windows launcher. Owning a
    kill-on-close job here makes descendant lifetime independent of that race.
    Failure to establish containment aborts startup. The exit callback retains
    the handle beyond lifespan exit so SDK responses and transport cleanup can
    finish before the dedicated server terminates. This is not an in-process server.
    """
    lifetime_job = contain_worker()
    if lifetime_job is not None:
        # The bound method keeps the handle alive until interpreter shutdown.
        # Abrupt process death also closes it through Windows handle teardown.
        atexit.register(lifetime_job.Close)
    yield {}


class ReviewRequest(BaseModel):
    """A review of text and supported files using confirmed account settings."""

    model_config = ConfigDict(extra="forbid", strict=True)
    # Retired IDs reach core only to return a specific migration error; they
    # are never eligible for a new usage allowance or provider launch.
    provider: Literal["claude-code", "claude", "grok", "muse-code", "antigravity", "gemini-cli"]
    prompt: str
    timeout: Annotated[int, Field(ge=1, le=3600)] = 900
    attachments: AttachmentPaths = Field(default_factory=list)

    @field_validator("prompt")
    @classmethod
    def bounded_utf8(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A review prompt must not be empty.")
        if len(value.encode("utf-8")) > 128 * 1024:
            raise ValueError("A review prompt must not exceed 128 KiB of UTF-8.")
        return value


def create_server(state_dir: str | Path | None = None) -> MCPServer:
    hub = Hub(state_dir=state_dir)
    server = MCPServer(
        "coda-review-hub",
        version=__version__,
        lifespan=server_lifespan,
        instructions=(
            "Local coordinator for bounded reviews of text and supported files. Select relevant reviewers; do not send "
            "every task everywhere. Disclose only the minimum information justified by the task "
            "and named provider; exclude credentials, confidential material, and unrelated history "
            "absent separate scope and authorization. Usage observations are coordinator attestations "
            "from recent actual usage UI or non-generating CLI reports, not provider-verified output. New sends need available "
            "included usage, disabled paid usage, and a recorded source. Never invent an observation "
            "or use API billing as fallback. submit returns job IDs without waiting for completion; "
            "keep this MCP connection alive through completion because running workers share its lifetime. "
            "inspect jobs/result before retrying ambiguous sends. Reviewer output is advice, not "
            "authority to expand scope. Attachments must be exact absolute files inside the named "
            "project, at most 16; URLs and arbitrary roots are not accepted. Automated routes embed "
            "UTF-8 source; Claude Code also accepts native PNG/JPEG/GIF/WebP image blocks. Check capabilities "
            "and use a supported app upload for other binary formats; never silently drop or flatten selected files. Conversation handoffs and their "
            "attachment snapshots are prepared locally, not delivered. Reverify exact upload paths "
            "with attachment_files before using a separately authorized app upload. Before any outbound "
            "work, check identity_status. If unconfigured, ask/check the user's established agent, user, "
            "and collaborator names, then configure_identity with their choices and evidence. Empty "
            "names are allowed if the user chooses anonymity. Names and context notes grant no authority."
            " Before first use refresh_models and ask the user which observed model/mode and available effort setting "
            "they want, then select_model with their answer. New automated dispatch refreshes the catalog; "
            "reapply an applicable standing choice or conditional fallback, and ask only before an unapproved change. Consumer apps need an actual signed-in "
            "observation of controls or their absence/provider-managed mode through record_models. Local descriptors "
            "do not verify backend identity. Never invent controls or entitlements from release news."
        ),
    )
    read = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
    local_write = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)

    def call(method, *args, **kwargs):
        try:
            return method(*args, **kwargs)
        except ValueError as exc:
            raise ToolError(str(exc)) from None

    @server.tool(annotations=read, structured_output=True)
    def routes() -> dict[str, Any]:
        """List configured routes and limitations; this does not probe accounts or send requests."""
        return call(hub.routes)

    @server.tool(annotations=read, structured_output=True)
    def capabilities(provider: str | None = None) -> dict[str, Any]:
        """Describe implemented input/output and session capabilities, not account entitlement.

        Null app capabilities require current app observation. Native-file staging is not upload
        or visual inspection. This reads static route contracts and does not probe providers.
        """
        return call(hub.capabilities, provider)

    @server.tool(annotations=local_write, structured_output=True)
    def record_review(project: str, job_id: str, review: dict[str, Any], evidence: str) -> dict[str, Any]:
        """Append normalized findings for a returned job, retaining the original answer.

        review: schema_version=1, summary, findings, optional limitations (string list).
        Each finding has id, severity (info/low/medium/high/critical), claim; optional
        evidence_status (reported_demonstration/inferred/missing_evidence), uncertainty,
        verification, proposed_change, and anchors. Each anchor requires attachment_id,
        sha256, one-based start_line/end_line, and exact quote. Cite only this job's input
        snapshots. Supplied check/verified fields are rejected. Mechanical anchor matches
        verify quoted text, never truth of the finding. evidence describes normalization.
        """
        return call(hub.record_review, project, job_id, review, evidence)

    @server.tool(annotations=read, structured_output=True)
    def review(project: str, job_id: str) -> dict[str, Any]:
        """Read normalized findings/history and recheck saved citations without sending.

        Rechecks snapshot and source-answer integrity. Unanchored, mismatched, unavailable,
        or binary/visual citations remain distinct from matching source quotations.
        """
        return call(hub.review, project, job_id)

    @server.tool(annotations=local_write, structured_output=True)
    def record_lineage(project: str, job_id: str, parent_job_id: str,
                       kind: Literal['snapshot_replay', 'app_conversation'], evidence: str,
                       omitted_context: str = '') -> dict[str, Any]:
        """Record observed parent/child context for two returned jobs in the same project.

        Same-app continuation requires the same provider and exact conversation reference.
        Snapshot replay is a coordinator attestation; record omitted/truncated context.
        This never performs a send, replay, fork, or native CLI resume. Native resume is
        not a production capability; a provider session ID alone does not establish it.
        """
        return call(hub.record_lineage, project, job_id, parent_job_id, kind, evidence, omitted_context)

    @server.tool(annotations=read, structured_output=True)
    def comparison_report(project: str, job_ids: Annotated[list[StrictStr], Field(min_length=1, max_length=16)],
                          format: Literal['html', 'markdown'] = 'html') -> dict[str, Any]:
        """Return a static escaped comparison of explicitly selected local job records.

        Includes model/mode observations, delivery states, findings, citation checks,
        session lineage and attachment metadata. No live calls, scripts, external assets,
        file uploads or publishing. The report contains selected project/private output;
        save locally and share only within the user's authorized scope.
        """
        return call(hub.comparison_report, project, job_ids, format)

    @server.tool(annotations=read, structured_output=True)
    def model_status(provider: str) -> dict[str, Any]:
        """Read saved catalog and user choice; no provider call or model generation."""
        return call(hub.model_status, provider)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True), structured_output=True)
    def refresh_models(provider: str) -> dict[str, Any]:
        """Discover current account-visible CLI models/efforts without a model prompt.

        For an app handoff, inspect signed-in controls or their absence/provider-managed mode and record_models.
        On first use or a changed catalog, apply a current standing choice/verified fallback if present;
        otherwise ask for an approved model/effort, then select_model.
        App versions are observations, not pinned compatibility requirements. No paid API fallback.
        """
        return call(hub.refresh_models, provider)

    @server.tool(annotations=local_write, structured_output=True)
    def record_models(provider: str, models: list[dict[str, Any]], evidence: str, observed_at: str,
                      selection_policy: dict[str, Any] | None = None) -> dict[str, Any]:
        """Record actual signed-in app controls or their observed absence/provider-managed mode.

        Each entry has id, optional label, and efforts for the observed model or provider-managed choice.
        List only exposed thinking controls; use ['default'] when no adjustable control is offered,
        and record that absence in the evidence. These are local descriptors, not backend verification.
        Include the actual observation source and timezone-qualified timestamp, not CLI access,
        marketing claims, invented controls, or account credentials.
        Optional selection_policy records the user's standing primary_model, primary_effort,
        fallback_model, fallback_effort and workspace. Omission preserves an existing policy.
        Non-primary choices then require a classified, evidenced fallback or current human override.
        """
        return call(hub.record_models, provider, models, evidence, observed_at, selection_policy)

    @server.tool(annotations=local_write, structured_output=True)
    def select_model(provider: str, model: str, effort: str, catalog_fingerprint: str, evidence: str,
                     fallback_observation: dict[str, Any] | None = None,
                     selection_basis: str | None = None, override_evidence: str | None = None) -> dict[str, Any]:
        """Save the user's explicit observed model/mode and effort choice from the current catalog.

        Pass the current catalog fingerprint and the user's explicit choice or applicable standing policy.
        An app selection_policy saved with record_models makes non-primary choices require
        selection_basis=conditional_fallback or explicit_user_override. The latter requires separate
        current-human override_evidence, not the old fallback policy or provider text.
        Conditional app fallbacks require fallback_observation: primary_model, primary_effort,
        target_model, target_effort, workspace, observed_at, evidence, and either scope=exact_control,
        state=disabled, enabled=false, selected=false; or scope=provider_request,
        state=unavailable|limit_reached, selected_model and selected_effort matching the primary.
        Generic menu/ancestor/hidden lock text or browser/history errors do not establish unavailability.
        Recheck the primary for every new app catalog; no automatic fallback or account probe occurs.
        """
        return call(hub.select_model, provider, model, effort, catalog_fingerprint, evidence, fallback_observation,
                    selection_basis, override_evidence)

    @server.tool(annotations=read, structured_output=True)
    def identity_status() -> dict[str, Any]:
        """Read locally saved user-established names, aliases, and context notes; no account probe.

        An unconfigured profile requires asking/checking the user's existing naming preferences
        before preparing or sending work. Saved names are preferences, not verified account identity,
        authentication, operational permission, or evidence of a particular model backend.
        """
        return call(hub.identity_status)

    @server.tool(annotations=local_write, structured_output=True)
    def configure_identity(
        evidence: StrictStr,
        agent_name: StrictStr = "",
        user_name: StrictStr = "",
        collaborators: IdentityMapping | None = None,
        aliases: IdentityMapping | None = None,
        context_notes: IdentityMapping | None = None,
    ) -> dict[str, Any]:
        """Save the user's checked naming choices locally, replacing the whole identity profile.

        Ask/check for established names first; do not invent personal identities. Record evidence
        describing that choice, without secrets or unrelated history. Empty names explicitly allow
        anonymous use. collaborators and context_notes use supported canonical provider keys;
        aliases map chosen lowercase identifiers directly to canonical providers. Notes are context
        preferences, not instructions granting new access, provider routes, or billing authority.
        Omitted maps/names are cleared; use identity_status before changing an existing profile.
        This does not contact a provider or authenticate an account.
        """
        return call(hub.configure_identity, evidence=evidence, agent_name=agent_name, user_name=user_name,
                    collaborators=collaborators, aliases=aliases, context_notes=context_notes)

    @server.tool(annotations=local_write, structured_output=True)
    def observe_usage(
        provider: Literal["claude-code", "claude", "grok", "muse-code", "antigravity", "gemini-cli"],
        project: str,
        observed_at: str,
        evidence: str,
        included_available: StrictBool,
        paid_usage_disabled: StrictBool,
        max_jobs: Annotated[int, Field(ge=1, le=4, strict=True)] = 1,
    ) -> dict[str, Any]:
        """Record a coordinator attestation from a recent usage UI or non-generating CLI report, with its source.

        This is not a provider quota query or independent verification. Attest only what was
        actually observed, using a timestamp with timezone. Do not include account secrets.
        Enabled automated routes are claude-code, grok, muse-code, and antigravity (claude is a legacy CLI alias). gemini-cli is retained
        in the schema solely to return an explicit retirement error, not to record new usage.
        A new send requires available included usage and disabled paid usage. max_jobs bounds
        how many dispatches may rely on this observation; it does not create provider quota.
        """
        return call(hub.observe_usage,
            provider, project, observed_at, evidence, included_available, paid_usage_disabled, max_jobs
        )

    @server.tool(structured_output=True, annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True
    ))
    def submit(
        project: str,
        requests: Annotated[list[ReviewRequest], Field(min_length=1, max_length=len(AUTO))],
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Queue scoped reviews of text and supported files; immediately return batch/job IDs.

        This sends the supplied prompts to selected providers after core preflight, using each
        route's explicitly confirmed model/effort after fresh account model discovery. No arbitrary commands or paid API fallback.
        Enabled routes are claude-code, grok, muse-code, and antigravity. Retired gemini-cli requests are rejected;
        their existing records remain readable through jobs/result and are never redirected.
        Recent sourced usage attestations with included capacity and paid usage disabled are
        required. Reuse the idempotency key for the same logical request, then inspect jobs/results
        instead of duplicating a potentially delivered prompt. Model replies are not verified facts.
        Keep the MCP connection open through completion; disconnect can terminate running jobs.
        Optional attachments are at most 16 exact absolute project-file paths. UTF-8 source is
        embedded as quoted evidence. Claude Code additionally accepts native PNG/JPEG/GIF/WebP
        images: 5 MiB each and 8 MiB for the encoded request, with source text bounded at 128 KiB.
        Other binary formats require a supported app handoff; no silent conversion or omission.
        No folder or URL attachment. Inspect capabilities for the route's implemented limits.
        """
        return call(hub.submit, project, [request.model_dump() for request in requests], idempotency_key)

    @server.tool(annotations=read, structured_output=True)
    def jobs(project: str, batch_id: str | None = None) -> list[dict[str, Any]]:
        """Read scoped job status without waiting for completion or sending another prompt."""
        return call(hub.jobs, project, batch_id=batch_id)

    @server.tool(annotations=read, structured_output=True)
    def result(
        project: str,
        job_id: str,
        offset: Annotated[int, Field(ge=0, strict=True)] = 0,
        limit: Annotated[int, Field(ge=1, le=32000, strict=True)] = 12000,
        turn_id: Annotated[StrictStr, Field(max_length=32)] = "",
    ) -> dict[str, Any]:
        """Read a bounded page of a scoped job result and its completion state; no new send."""
        return call(hub.result, project, job_id, offset=offset, limit=limit, turn_id=turn_id)

    @server.tool(annotations=read, structured_output=True)
    def attachment_files(
        project: str,
        job_id: str,
        direction: Literal["input", "output"] = "input",
        turn_id: Annotated[StrictStr, Field(max_length=32)] = "",
    ) -> dict[str, Any]:
        """Reverify scoped attachment snapshots and return their manifest and exact upload paths.

        direction selects prepared input or coordinator-observed output files. sent:false means
        this only reads local evidence; it never uploads, downloads, or verifies provider receipt.
        Use only the returned exact paths for a separately authorized app attachment. Do not browse
        personal directories or broaden the file list. Verify every attachment chip before sending.
        """
        return call(hub.attachment_files, project, job_id, direction=direction, turn_id=turn_id)

    @server.tool(structured_output=True, annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=True, openWorldHint=False
    ))
    def cancel(project: str, job_id: str) -> dict[str, Any]:
        """Request cancellation of a scoped local job; cancellation does not prove non-delivery."""
        return call(hub.cancel, project, job_id)

    @server.tool(annotations=local_write, structured_output=True)
    def handoff(
        project: str,
        provider: str,
        prompt: str,
        conversation_ref: str = "",
        attachments: AttachmentPaths | None = None,
    ) -> dict[str, Any]:
        """Prepare a scoped conversation handoff locally; it does not send or verify delivery.

        Provide an existing relevant conversation reference when known. Preserve project scope
        and attribution, identify the configured coordinator, and thank the collaborator. Never invent a conversation.
        Use a normal saved, non-Temporary project conversation and name it clearly. Before sending,
        inspect actual mode/history controls and verify normal saved mode; do not send if that mode
        cannot be established. A brand-new normal saved chat need not already have a URL/history entry.
        After the response, verify the completed exchange appears in saved history and can be reopened.
        Preserve the actual title, reference, mode observation, and post-response history check in
        returned-result evidence. The hub only prepares the handoff and cannot verify or change app
        settings; preparation or a supplied reference does not prove conversation persistence.
        Optional attachments are at most 16 exact absolute project-file paths, snapshotted locally.
        Reverify them with attachment_files before an app upload; staging does not establish receipt.
        Follow the returned route instructions: verify Gemini model and thinking per conversation;
        Spark/Muse backend identity is unverified. Meta Thinking is an exposed mode, not a universal
        ranking. Consumer access does not establish CLI entitlement or authorize broader access.
        """
        return call(hub.handoff, project, provider, prompt, conversation_ref, attachments=attachments)

    @server.tool(annotations=local_write, structured_output=True)
    def record_handoff_result(
        project: str,
        job_id: str,
        response: str,
        evidence: str,
        conversation_ref: str,
        acknowledgment: Literal["pending", "delivered", "not_possible"] = "pending",
        observed_attachment_ids: AttachmentIds | None = None,
        attachment_evidence: str = "",
        returned_files: AttachmentPaths | None = None,
        artifact_evidence: str = "",
        observed_model: Annotated[StrictStr, Field(max_length=256)] = "",
        observed_mode: Annotated[StrictStr, Field(max_length=256)] = "",
        completion_observation: CompletionObservation | None = None,
        previous_turn_id: Annotated[StrictStr, Field(max_length=32)] = "",
    ) -> dict[str, Any]:
        """Record coordinator-observed app output for a previously prepared handoff.

        Supply the exact returned response, a non-secret evidence reference and conversation
        reference, and the acknowledgment state actually observed. This is a coordinator record,
        not automated verification of provider delivery, backend model identity, or correctness.
        In evidence, preserve the actual saved project-conversation title, non-secret reference,
        normal saved mode observed before sending, and the post-response check that the completed
        exchange appears in saved history and can be reopened. A new chat's reference/history entry
        may only become available after its first send. Pass the exact reference as
        conversation_ref. Report only actual observations; the hub cannot verify app settings
        or infer persistence from a prepared handoff or a conversation reference.
        It does not send a prompt or acknowledgment. Preserve the respondent's attribution.
        If the prepared input includes attachments, supply their exact observed IDs and actual
        attachment evidence. Optional returned_files are at most 16 exact project-local downloaded
        files; supply actual artifact evidence. The hub snapshots them without downloading itself.
        Optional observed_model and observed_mode preserve visible conversation labels as
        coordinator testimony only. They do not verify exact backend identity or model capability.
        A response or verdict is not necessarily a finished review. Supply actual completion
        observations; omission remains unknown and nonterminal. Prefer provider_stop_reason when
        available, record Continue controls and outstanding checks. Tool/output limits, cancellation,
        errors, unknown delivery and unfinished checks override generic 'finished' prose. Record
        each partial response verbatim; leave acknowledgment pending. Continue only in the same
        saved conversation, with exact previous_turn_id from the last receipt and resolved_checks
        listing prior checks actually closed. Partial turns remain individually hashed and readable
        with result(turn_id=...). Only completed review output can enter findings/comparison or
        closing acknowledgment. This call records observations; it does not click Continue.
        """
        return call(
            hub.record_handoff_result, project, job_id, response, evidence, conversation_ref, acknowledgment,
            observed_attachment_ids=observed_attachment_ids, attachment_evidence=attachment_evidence,
            returned_files=returned_files, artifact_evidence=artifact_evidence,
            observed_model=observed_model, observed_mode=observed_mode,
            completion_observation=completion_observation.model_dump() if completion_observation is not None else None,
            previous_turn_id=previous_turn_id,
        )

    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local review hub MCP server (stdio only).")
    parser.add_argument("--state-dir", type=Path)
    args = parser.parse_args(argv)
    create_server(args.state_dir).run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
