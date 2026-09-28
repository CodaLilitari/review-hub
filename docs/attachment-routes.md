# Files, images and returned artifacts

Review Hub supports embedded source text for automated review, native image blocks for Claude Code, and native-file staging for an app handoff. It does not itself upload to apps, generate images, download artifacts, or grant project-editing access. Select the route that preserves the actual files needed for the task; see [native file support](native-file-support.md).

## Snapshot rules

Supply exact absolute paths inside the authorized project. The hub reads only that list, records hashes, and preserves snapshots for the job. It rejects folders, wildcards, parent traversal, duplicate paths, symlinks/reparse points and special files. Windows inputs must be ordinary local-drive files, not network/device paths or alternate streams.

Current local limits are **16 files, 20 MiB per file and 50 MiB combined**. Provider limits may be smaller. These are disclosure/size checks, not malware scanning or a sandbox against another process running as the same user. MIME values are filename-derived hints, not verified content types.

Never add a whole folder merely because a provider supports folder upload. Select only material justified by the named task and destination. Keep manifests, original paths and private snapshots out of the public repository.

## Automated source-text review

The `attachments` list on a `submit` request accepts supported UTF-8 source/text files. Their contents are embedded as quoted JSON evidence with project-relative names and hashes. The complete packet must fit **128 KiB**, including the introduction and encoding. A successful answer does not prove every supplied line was understood.

This source-text path is not a native file upload. SVG is reviewed as source text, not as rendered pixels. Notebook JSON is source data, not an executed notebook. If content was extracted, rendered or otherwise converted beforehand, identify that transformation and retain provenance. PDFs and other unsupported automated formats require an app handoff; do not silently omit or convert them.

Grok has a specific preprocessing concern: published [prompt-parser source](https://github.com/xai-org/grok-build/blob/4247f661689354b831191f11eeeac8424993fe3d/crates/codegen/xai-grok-shell/src/session/prompt_parser.rs) expands literal `@file` references before model tool permissions. `--verbatim` alone does not stop that source path. Text packets containing an at-sign are encoded with literal Unicode escapes and retained as `.txt`; original snapshots remain separate. The [headless parser](https://github.com/xai-org/grok-build/blob/4247f661689354b831191f11eeeac8424993fe3d/crates/codegen/xai-grok-pager/src/headless/cli.rs) treats `.txt` as text. Changing it to `.json` or `--prompt-json` would decode escapes before collection and requires a new safety review. This source-based guard is not proof of every behavior of every provider version.

The retired Gemini CLI experiment also required protection against `@file` preprocessing. Its archived behavior is described in the [historical Gemini CLI restrictions](gemini-meta-v0.3.md#restrictions-and-evidence); those removed helper scripts are not a current setup route. The current automated Google route is [Antigravity](antigravity-v0.4.md), with separate controls and discovery.

## Claude Code native image review

A `claude-code` request containing PNG, JPEG, GIF or WebP selects structured image input automatically. The original image bytes are supplied as base64 image content blocks, with separately labeled quoted source text in mixed requests. No model file-reading tool or broad project access is enabled. The same exact-path snapshot rules apply, with tighter limits of **5 MiB per image and 8 MiB for the entire encoded request**, and 128 KiB for prompt/source text.

Suffix/signature checks reject mislabeled or unsupported image inputs; they do not fully decode or visually validate the image. Animation review is not established: Claude documents first-frame handling. The worker verifies staged snapshots and requires the helper receipt's input format, native transport, request hash and ordered image hashes to match before recording successful completion. Transport evidence does not prove image understanding. See the [adapter contract](adapter-contract.md) for exact receipt fields and local helper pin updates.

## Native app handoffs

1. Select a named, saved, non-Temporary project conversation and observe the app's current support for the selected formats. Call `handoff` with the exact files and conversation reference when known. It stages snapshots and a packet; `sent:false` means no upload occurred. Verify saved mode before sending, and retain the assigned reference and history evidence afterward.
2. Call `attachment_files` with `direction: input` immediately before the separately operated upload. Use only its verified snapshot paths.
3. Use a direct chooser/path-entry method. Avoid browsing unrelated directories or capturing file pickers/recent-file surfaces. Verify every attachment chip against the manifest before sending.
4. Inspect the actual sent message and response. Record them with `record_handoff_result`, including the observed attachment IDs, evidence of their presence, and `completion_observation`. Preserve interruptions as partial turns and continue only in that same saved conversation; see [app review completion](app-review-completion.md). These are coordinator observations, not automated provider inspection.
5. Save any returned artifact under an exact authorized project path, then supply it through `returned_files` with artifact evidence. Outputs remain separate for each response turn. `attachment_files` with `direction: output` and optional `turn_id` rechecks those saved bytes; it does not download or validate their contents.

A returned image can be included in a later explicitly scoped handoff to another reviewer. Each transfer is a new disclosure decision. Neither an attachment chip nor a provider's assertion establishes pixel fidelity or executed-code correctness; inspect and test the relevant artifact independently.

## Provider evidence and validation limits

The source-text/app staging design was researched on September 20, 2026. The September 27 follow-up informed the native Claude extension and rechecked distinctions between other products and routes. Availability and plan limits can change; [dated research notes](attachment-route-research.md) retain the evidence boundaries.

- **Claude Code:** [structured input](https://code.claude.com/docs/en/cli-reference) and [official SDK examples](https://code.claude.com/docs/en/agent-sdk/streaming-vs-single-mode) inform the implemented native image transport. [Vision formats](https://platform.claude.com/docs/en/build-with-claude/vision) include JPEG, PNG, GIF and WebP. Offline transport tests do not establish live image interpretation or current account access; API/app ceilings do not establish identical subscription-CLI limits.
- **Grok Build:** current public source differs by harness: some paths produce auxiliary image descriptions, while others retain multimodal content. An initialize-only installed-runtime probe advertised `image:false`. Native images remain outside automated Hub dispatch pending runtime and subscription-route validation.
- **Antigravity:** its current [headless contract](https://www.antigravity.google/docs/cli/headless/) documents text blocks. Interactive media input and the SDK are distinct routes; SDK API/Cloud authentication does not establish consumer-subscription access.
- **Gemini web and other supported apps:** observe the account's actual upload controls and current format/count/size limits. Google's [upload guide](https://support.google.com/gemini/answer/14903178?co=GENIE.Platform%3DDesktop&hl=en) describes native uploads and separate code-folder imports; folder support does not authorize uploading a whole project. Rolling usage, storage and context limits still apply.

Image generation or editing, when requested, happens through the separately authorized provider app and its actual account entitlement. The hub records the handoff and returned artifact; it is not an image-generation transport or a paid-API fallback.
