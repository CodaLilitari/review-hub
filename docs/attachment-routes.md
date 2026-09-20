# Files, images and returned artifacts

Review Hub supports two distinct file paths: embedded source text for automated review, and native-file staging for an app handoff. It does not itself upload to apps, generate images, download artifacts, or grant project-editing access.

## Snapshot rules

Supply exact absolute paths inside the authorized project. The hub reads only that list, records hashes, and preserves snapshots for the job. It rejects folders, wildcards, parent traversal, duplicate paths, symlinks/reparse points and special files. Windows inputs must be ordinary local-drive files, not network/device paths or alternate streams.

Current local limits are **16 files, 20 MiB per file and 50 MiB combined**. Provider limits may be smaller. These are disclosure/size checks, not malware scanning or a sandbox against another process running as the same user. MIME values are filename-derived hints, not verified content types.

Never add a whole folder merely because a provider supports folder upload. Select only material justified by the named task and destination. Keep manifests, original paths and private snapshots out of the public repository.

## Automated source-text review

The `attachments` list on a `submit` request accepts supported UTF-8 source/text files. Their contents are embedded as quoted JSON evidence with project-relative names and hashes. The complete packet must fit **128 KiB**, including the introduction and encoding. A successful answer does not prove every supplied line was understood.

This is not a native file upload. Binary images and PDFs are refused on the automated path. SVG is reviewed as source text, not as rendered pixels. Notebook JSON is source data, not an executed notebook. If content was extracted, rendered or otherwise converted beforehand, identify that transformation and retain provenance.

Grok has a specific preprocessing concern: published [prompt-parser source](https://github.com/xai-org/grok-build/blob/4247f661689354b831191f11eeeac8424993fe3d/crates/codegen/xai-grok-shell/src/session/prompt_parser.rs) expands literal `@file` references before model tool permissions. `--verbatim` alone does not stop that source path. Text packets containing an at-sign are encoded with literal Unicode escapes and retained as `.txt`; original snapshots remain separate. The [headless parser](https://github.com/xai-org/grok-build/blob/4247f661689354b831191f11eeeac8424993fe3d/crates/codegen/xai-grok-pager/src/headless/cli.rs) treats `.txt` as text. Changing it to `.json` or `--prompt-json` would decode escapes before collection and requires a new safety review. This source-based guard is not proof of every behavior of every provider version.

Gemini CLI also preprocesses literal `@file` references before normal tool policy. Its text helper JSON-encodes the full request with literal Unicode escapes for every at-sign, retaining original and transmitted hashes. See [Gemini CLI restrictions](gemini-meta-v0.3.md#restrictions-and-evidence). This is embedded source text, not native image or file transport.

## Native app handoffs

1. Call `handoff` with the selected files and the appropriate project conversation reference when known. It stages snapshots and a packet; `sent:false` means no upload occurred.
2. Call `attachment_files` with `direction: input` immediately before the separately operated upload. Use only its verified snapshot paths.
3. Use a direct chooser/path-entry method. Avoid browsing unrelated directories or capturing file pickers/recent-file surfaces. Verify every attachment chip against the manifest before sending.
4. Inspect the actual sent message and response. Record them with `record_handoff_result`, including the observed attachment IDs and evidence of their presence. This is a coordinator observation, not automated provider inspection.
5. Save any returned artifact under an exact authorized project path, then supply it through `returned_files` with artifact evidence. `attachment_files` with `direction: output` rechecks those saved bytes; it does not download or validate their contents.

A returned image can be included in a later explicitly scoped handoff to another reviewer. Each transfer is a new disclosure decision. Neither an attachment chip nor a provider's assertion establishes pixel fidelity or executed-code correctness; inspect and test the relevant artifact independently.

## Provider research, not enabled transports

Sources checked 2026-09-20; availability and plan limits can change.

- **Claude Code:** [structured input](https://code.claude.com/docs/en/cli-reference) and [official SDK examples](https://code.claude.com/docs/en/agent-sdk/streaming-vs-single-mode) support base64 image content blocks. A guarded stdin extension could supply selected pixels without enabling a file-reading tool, but native images are not implemented by this public helper contract. [Vision formats](https://platform.claude.com/docs/en/build-with-claude/vision) include JPEG, PNG, GIF and WebP; API/app ceilings are not evidence of an identical subscription-CLI limit.
- **Grok Build:** official source accepts JSON content blocks, but an [image pipeline](https://github.com/xai-org/grok-build/blob/4247f661689354b831191f11eeeac8424993fe3d/crates/codegen/xai-grok-shell/src/session/image_describe.rs) can call an auxiliary vision model and provide descriptions to the coding model. Tool denial does not establish included billing for that extra call. Native images remain outside automated hub dispatch until the complete route is verified.
- **Gemini web:** the [upload guide](https://support.google.com/gemini/answer/14903178?co=GENIE.Platform%3DDesktop&hl=en) documents up to 10 files per prompt, subject to availability; generally 100 MB per non-video file and 2 GB per video. Code-folder/repository import is a separate feature. Rolling usage, storage and context limits still apply. Use the account's actual supported app controls, without inferring Gemini CLI/API access.

Image generation or editing, when requested, happens through the separately authorized provider app and its actual account entitlement. The hub records the handoff and returned artifact; it is not an image-generation transport or a paid-API fallback.
