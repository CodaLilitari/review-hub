# Native files and route selection

Select a route based on the input needed for the task, for every authorized reviewer. Prefer the original file when its layout, imagery, sound, motion, timing, formatting or other native content matters. Images and bounded audio/video excerpts are review inputs when relevant and supported. A text-only helper or prompt-only message tool limits that transport; use a capable, authorized app upload when the critique requires media. Do not silently replace an image with a description, audio with a transcript, video with stills, a PDF with extracted text, or omit unsupported files. Any deliberate conversion must preserve the original, record the conversion and its limits, and be suitable for the task.

For excerpts, retain the source hash and start/end times; for conversions, record changes to format, resolution, frame rate or audio tracks when applicable. Include enough context for the requested judgment. The reviewer should identify inaccessible inputs and uninspected intervals. A transcript can support wording review and stills can support composition review; neither establishes listening, motion review or audiovisual synchronization. Delivery and perceptual judgment remain separate evidence.

| Route | Implemented input | Output and audit |
|---|---|---|
| Claude Code CLI | UTF-8/source plus native PNG/JPEG/GIF/WebP image blocks, including mixed requests | Text answer, exact original snapshots, transmitted request/hash, ordered image hashes and helper receipt |
| Grok Build CLI | Quoted UTF-8/source | Text answer and exact local request/response audit |
| Antigravity headless CLI | Quoted UTF-8/source | Text answer and exact local request/response audit |
| Supported AI apps | Native files staged locally; the coordinator must observe the selected app's current type/size support and actual attachment | Saved conversation, exact attachment evidence, response and downloaded files through `returned_files` |

## Claude Code native images

The existing `submit` attachment field takes an explicit list of absolute files inside the current project. With Claude Code, a supported image selects structured input automatically; text-only requests keep their existing behavior. Aliased `claude` requests resolve to `claude-code` as before. A mixed image/source request contains native image blocks and separately labeled quoted source text. Absolute source and snapshot paths are not included in the generated provider packet.

The adapter checks suffix/signature agreement for PNG/JPEG/GIF/WebP and uses canonical base64 bytes. These checks do not fully decode an image or prove it is visually correct. Animated images do not establish animation review; Claude documents first-frame handling only. Current limits are 16 exact selected files, 5 MiB per native image, 128 KiB for accompanying prompt/source text and 8 MiB for the complete encoded request. Nothing is automatically resized or converted. SVG remains source text, not rendered pixels.

The helper validates exactly one newline-terminated user frame. It rejects extra frames, duplicate keys, tool/control/document blocks, URL/file-reference blocks, malformed base64, unsupported MIME types and signature mismatches. Existing tool/MCP restrictions, temporary working directory, subscription authentication and paid-usage guards remain in force. No Files API, API key or broad directory access is introduced. A user upgrading the helper must review its source and update their own local helper hash; placeholder pins do not establish readiness.

The worker rechecks the staged snapshots and requires the returned helper receipt to match the input format, native transport, transmitted request hash and ordered image hashes before marking the review returned. This binds the recorded result to the supplied request; it does not prove how accurately the provider interpreted the image or independently attest its backend model.

## Documents, other media, and returned files

For PDF, Office, audio/video or another unsupported CLI format, choose an authorized app route whose current upload controls accept that format. All app handoffs can stage exact binary file bytes, but staging is not an upload or universal format support. The same [saved conversation](app-conversation-audit.md) and [interruption/continuation](app-review-completion.md) rules apply.

Use `handoff(..., attachments=[...])`, reverify exact `attachment_files` paths immediately before upload, attach only that allowlist, and verify the app's actual attachment chips. Record the ordered `observed_attachment_ids` and real attachment evidence. Downloaded outputs must be saved to exact authorized project-local paths, then retained with `returned_files` and `artifact_evidence`. Responses and outputs from separate continuation turns remain separate. Inspect the actual artifact independently; file transport is not content validation.

Unknown account support, quota or native transport is a reason to choose a verified route or report that specific gap. It does not authorize API charges, omitted files, whole-folder uploads, or an unapproved recipient.

## Evidence and validation boundary

Anthropic documents [structured CLI input](https://code.claude.com/docs/en/cli-reference) and [image content blocks in streaming input](https://code.claude.com/docs/en/agent-sdk/streaming-vs-single-mode). Its [vision guide](https://platform.claude.com/docs/en/build-with-claude/vision) lists the four image formats and first-frame limitation. The SDK wire example informs this CLI adapter; no SDK or API client is used. Published API/app limits do not establish identical subscription-CLI limits.

The implementation includes offline payload, helper, worker and receipt tests, including exact bytes, mixed input, tampered snapshots, unsupported formats, mismatched receipts and missing receipts remaining delivery-unknown. A development help check on September 27, 2026 observed Claude Code 2.1.282 advertising `--input-format stream-json` and `--tools`. That dated observation is not a required runtime version or a live image round trip. A current account/model image review remains a separate validation step requiring fresh included-usage evidence. No live generating request was made to validate this extension.

The [attachment research notes](attachment-route-research.md) explain why the current Grok Build and Antigravity headless adapters remain source/text-only. Provider capabilities and billing routes can change; refresh the actual supported interface before enabling a new transport.

## Public package validation, September 28, 2026

The public package's full suite passed **351 tests in 90.026 seconds**, using the verified public source path. These are offline fixtures covering the helper, native input, receipts, saved-conversation policy, continuation and existing Hub behavior. No generating provider request was made. This result does not establish live image interpretation, a user's subscription entitlement, or actual app history persistence.
