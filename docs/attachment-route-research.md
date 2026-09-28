# Attachment routes: evidence and limits

These dated research notes inform the [implemented file routes](native-file-support.md). They distinguish documented interfaces, public source, local non-generating observations, and behavior still requiring a live account check. Native Claude image transport is implemented and tested offline. Grok Build and Antigravity headless remain source/text-only in the Hub. App file handoffs and returned-file snapshots are implemented separately.

## Claude Code: structured native images

Anthropic's [CLI reference](https://code.claude.com/docs/en/cli-reference) documents `--input-format stream-json` with print mode. Its [streaming-input examples](https://code.claude.com/docs/en/agent-sdk/streaming-vs-single-mode) show a user message containing text and base64 image blocks. The Hub serializes one bounded frame to the official CLI's structured stdin, retaining tool/MCP restrictions, a temporary working directory and subscription checks. The coordinator reads exact allowlisted files; the model needs no file-reading tool. No SDK installation or paid API route is introduced.

Claude's [vision guide](https://platform.claude.com/docs/en/build-with-claude/vision) lists JPEG, PNG, GIF and WebP; animation uses only the first frame. API/app limits are not independently verified subscription-CLI limits. The Hub's conservative limits are 5 MiB per image, 8 MiB per complete encoded request and 16 exact selected files. Native PDF/arbitrary-binary input is not implemented by this helper. Code/text remains labeled quoted source evidence.

A guarded development help check on September 27, 2026 observed Claude Code 2.1.282 advertising structured input and tool selection. No generating request was sent for this extension. Offline tests cover the frame validator, byte preservation, helper invocation and input-bound receipts; a live image interpretation result is separate evidence. This runtime observation does not freeze compatibility to that version.

The CLI's `--file` startup download feature is not a local attachment mechanism. Do not introduce Files API uploads or `--bare` as a shortcut; the latter skips subscription OAuth. Retain the [official binary/user-login boundary](https://code.claude.com/docs/en/legal-and-compliance#authentication-and-credential-use), with no silent API fallback.

## Grok Build: route and harness distinctions

Grok Build supports [headless scripting](https://docs.x.ai/build/cli/headless-scripting), and public source accepts structured content. However, a September 27 initialize-only development probe of installed Grok Build 1.0.34 advertised `image:false`, `audio:false`, and `embeddedContext:true`. Initialization sent no review or image and did not establish account access or billing.

The [September 23 public source snapshot](https://github.com/xai-org/grok-build/blob/f0e3be1100ef5252488e3be8bb0e91cf68d8c305/crates/codegen/xai-grok-shell/src/session/acp_session_impl/turn.rs#L1141) differs by harness: Cursor uses an auxiliary image description, while other harnesses retain multimodal image parts. That source was not established as the installed development build. Do not generalize older findings about auxiliary descriptions to every current harness, or treat the source alone as a verified native subscription route.

The [binary-resource implementation](https://github.com/xai-org/grok-build/blob/f0e3be1100ef5252488e3be8bb0e91cf68d8c305/crates/codegen/xai-grok-workspace/src/file_system/attach_file.rs#L192) stages bytes and supplies a path/MIME/size hint. The Hub's tools-disabled helper cannot read a PDF's contents from that hint. Enabling a file reader would change the boundary and needs separate design and validation. The [Grok Bot app](https://docs.x.ai/grok-bot/files-and-results) is a separate native-file handoff option whose current account support must be observed.

### File-reference preprocessing

The published [prompt parser](https://github.com/xai-org/grok-build/blob/4247f661689354b831191f11eeeac8424993fe3d/crates/codegen/xai-grok-shell/src/session/prompt_parser.rs) expands user-authority `@file` references before model tool calls; `--verbatim` does not disable that source path. Quoting a path is not a general escape. The [headless parser](https://github.com/xai-org/grok-build/blob/4247f661689354b831191f11eeeac8424993fe3d/crates/codegen/xai-grok-pager/src/headless/cli.rs) reads `.txt` as text, while `.json` and `--prompt-json` parse JSON before reference collection.

The current text adapter encodes literal at-signs as the characters `\u0040` in a JSON-encoded packet retained as `.txt`, keeping the original snapshots separate. Changing the file to `.json` would decode the escapes back into at-signs and requires a new review. This establishes a guard against the inspected source path; it is not proof of all preprocessing behavior across future binaries. Structured native Grok input requires its own file-reference, billing and runtime validation.

## Antigravity: headless input and other products

A September 27 development check observed Antigravity 1.2.8 exposing stream input. Google's [headless contract](https://www.antigravity.google/docs/cli/headless/) documents text content blocks; its [interactive media input](https://antigravity.google/docs/cli/prompting/) is a different route. The SDK documents native images/documents, but its [authentication setup](https://www.antigravity.google/docs/sdk/overview/) uses API-key or Cloud credentials. That SDK route is not a verified consumer-subscription fallback for this Hub.

The current headless helper therefore accepts source/text. No generating request was sent for this research. Do not broaden file-reader permissions or convert a document silently merely to make the headless route appear compatible.

## Native app uploads

For supported documents or other media, use a saved, non-Temporary project conversation and the selected app's observed upload controls. Google's [Gemini upload guide](https://support.google.com/gemini/answer/14903178?co=GENIE.Platform%3DDesktop&hl=en), for example, describes native file uploads with format, count, size and plan limits. Check the current account and limits at use time; published support does not establish remaining quota.

Use exact allowlists and a direct chooser method, verify the actual attachment chips before sending, and record submission/response evidence. Broad folder uploads and unrelated connected storage are outside this design. The Hub stages files and retains receipts; it does not operate the app, inherit another product's entitlement, or prove the returned artifact's content.
