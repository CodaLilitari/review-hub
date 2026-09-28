"""Pure descriptions of implemented routes and attachment representations.

These functions inspect no files, accounts, apps, or provider services. A route
contract describes what the hub can prepare; it does not establish entitlement,
delivery, app acceptance, or how a provider interpreted an attachment.
"""
from __future__ import annotations

from pathlib import PurePosixPath
import re

from .attachments import TEXT_EXTENSIONS, NATIVE_IMAGE_TYPES, MAX_NATIVE_IMAGE_BYTES, MAX_NATIVE_PACKET_BYTES
from .identity import PROVIDERS


AUTOMATED_PROVIDERS = frozenset({"claude-code", "grok", "antigravity"})
HANDOFF_PROVIDERS = frozenset({
    "claude-desktop", "chatgpt", "gemini", "gemini-desktop", "gemini-spark",
    "meta-ai", "meta-muse", "claude-cowork", "grok-bot",
    "microsoft-copilot", "github-copilot",
})
RETIRED_PROVIDERS = frozenset({"gemini-cli"})
LEGACY_PROVIDERS = {"claude": "claude-code"}
CAPABILITY_FIELDS = (
    "text_snapshot", "native_file_manifest", "image_visual_input",
    "document_binary_input", "returned_file_snapshot", "session_resume",
)
INPUT_TRANSPORTS = frozenset({"utf8_json_in_prompt", "claude_content_blocks", "app_file_handoff"})
OUTPUT_TRANSPORTS = frozenset({"app_file_handoff", "returned_file_snapshot"})


def route_capabilities(provider: str) -> dict:
    """Return a fresh route contract; null means current app evidence is needed.

    ``text_snapshot`` means embedded UTF-8 file/source text, not an uploaded
    native file. ``native_file_manifest`` and ``returned_file_snapshot`` refer
    to local staging/retention only. App interpretation and continuation remain
    unknown until a coordinator observes that app and conversation.
    """
    if not isinstance(provider, str) or provider not in PROVIDERS:
        raise ValueError("Unknown provider capability route")
    canonical = LEGACY_PROVIDERS.get(provider, provider)
    result = {
        "provider": provider,
        "canonical_provider": canonical,
        "evidence_level": "local_implementation_contract",
        "current_app_observation_required": False,
        "upload_claimed": False,
        "provider_acceptance_verified": False,
        "provider_interpretation_verified": False,
    }
    if canonical in RETIRED_PROVIDERS:
        result.update(
            transport="unavailable", available_for_new_work=False,
            historical_receipts_available=True,
            **{field: False for field in CAPABILITY_FIELDS},
        )
        result["capability_evidence"] = {
            field: "Retired for new work; existing receipts remain historical evidence."
            for field in CAPABILITY_FIELDS
        }
    elif canonical in AUTOMATED_PROVIDERS:
        result.update(
            transport="automated_cli", available_for_new_work=True,
            text_snapshot=True, native_file_manifest=False,
            image_visual_input=False, document_binary_input=False,
            returned_file_snapshot=False, session_resume=False,
        )
        result["capability_evidence"] = {
            "text_snapshot": "Selected UTF-8 file/source snapshots are embedded as quoted JSON in the bounded prompt.",
            "native_file_manifest": "The automated route embeds text; it does not upload native files.",
            "image_visual_input": "Visual image input is refused; SVG may be embedded as source text only.",
            "document_binary_input": "Binary document input is refused by the automated text route.",
            "returned_file_snapshot": "The automated worker retains response text and local receipts, not provider-returned file attachments.",
            "session_resume": "Each automated review is isolated; no provider session resume is requested.",
        }
        if canonical == "claude-code":
            result.update(native_file_manifest=True, image_visual_input=True,
                native_input_media_types=sorted(set(NATIVE_IMAGE_TYPES.values())),
                max_native_image_bytes=MAX_NATIVE_IMAGE_BYTES, max_encoded_request_bytes=MAX_NATIVE_PACKET_BYTES)
            result["capability_evidence"].update(
                native_file_manifest="Exact image snapshots are encoded as native content blocks; source/text remains quoted evidence.",
                image_visual_input="PNG/JPEG/GIF/WebP bytes can be sent through Claude Code structured stdin with tools disabled. This is an implemented transport, not current account/model acceptance or visual correctness. SVG remains source text.",
                document_binary_input="PDF/Office/audio/video are not enabled in this CLI adapter; use an observed supported app upload.")
        result["file_guidance"] = ("Choose a supported app handoff for formats outside this CLI's implemented input types; "
                                   "do not silently omit files or label extracted text as native input.")
    elif canonical in HANDOFF_PROVIDERS:
        result.update(
            transport="coordinator_handoff", available_for_new_work=True,
            current_app_observation_required=True,
            text_snapshot=False, native_file_manifest=True,
            image_visual_input=None, document_binary_input=None,
            returned_file_snapshot=True, session_resume=None,
        )
        result["capability_evidence"] = {
            "text_snapshot": "File contents are staged as native bytes; the prepared prompt includes a manifest, not embedded file text.",
            "native_file_manifest": "Exact files can be snapshotted locally with an attachment manifest; uploading and app acceptance require separate observations.",
            "image_visual_input": "Unknown pending a current app observation; staging image bytes does not prove visual input or interpretation.",
            "document_binary_input": "Unknown pending a current app observation; staging document bytes does not prove app acceptance or interpretation.",
            "returned_file_snapshot": "Exact project files can be retained as returned artifacts with separately recorded coordinator provenance; no download is performed by this capability.",
            "session_resume": "A coordinator can reference an existing conversation; actual app continuation must be observed, and the hub does not resume a provider session.",
        }
    else:
        raise ValueError("No implemented capability contract for this provider")
    return result


def all_capabilities() -> dict:
    """Map every supported provider identifier, including aliases, to its contract."""
    return {provider: route_capabilities(provider) for provider in sorted(PROVIDERS)}


def _manifest_text(value, label: str, maximum: int = 512) -> str:
    if (not isinstance(value, str) or not value or len(value) > maximum
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise ValueError(f"Invalid attachment {label}")
    return value


def attachment_view(manifest_item: dict, direction: str, transport: str) -> dict:
    """Describe a declared transport using an allowlist of manifest metadata.

    Hashes and names are preserved, not verified. Absolute source/snapshot paths,
    file contents, and unknown fields are omitted. Callers separately verify the
    manifest and record actual app delivery or artifact-origin observations.
    """
    if not isinstance(manifest_item, dict):
        raise ValueError("Attachment manifest entry must be an object")
    if not isinstance(direction, str) or direction not in {"input", "output"}:
        raise ValueError("Attachment direction must be input or output")
    allowed = INPUT_TRANSPORTS if direction == "input" else OUTPUT_TRANSPORTS
    if not isinstance(transport, str) or transport not in allowed:
        raise ValueError("Unsupported attachment transport for this direction")
    identifier = _manifest_text(manifest_item.get("attachment_id"), "identifier", 200)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", identifier):
        raise ValueError("Invalid attachment identifier")
    checksum = manifest_item.get("sha256")
    if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", checksum):
        raise ValueError("Invalid attachment SHA-256")
    names = {}
    for key in ("original_name", "upload_name"):
        name = _manifest_text(manifest_item.get(key), key)
        if name in {".", ".."} or any(char in name for char in "/\\:"):
            raise ValueError("Attachment names must be filenames, not paths")
        names[key] = name
    size = manifest_item.get("size_bytes")
    if type(size) is not int or size < 0:
        raise ValueError("Invalid attachment byte count")
    result = {
        "attachment_id": identifier, "sha256": checksum,
        **names, "size_bytes": size, "direction": direction, "transport": transport,
        "evidence_level": "manifest_and_declared_transport",
        "metadata_verification": "Metadata only; file bytes and the stored hash were not checked here.",
        "upload_claimed": False,
        "provider_acceptance_verified": False,
        "provider_interpretation_verified": False,
    }
    if manifest_item.get("media_type_hint") is not None:
        result["media_type_hint"] = _manifest_text(manifest_item["media_type_hint"], "media type hint", 200)
    if direction == "output":
        result.update(
            representation="retained_returned_file_artifact",
            representation_evidence="Local file bytes retained as an output artifact; the manifest alone does not establish provider origin.",
            provider_acceptance="not_applicable_to_retained_output",
            provider_interpretation="not_attested",
        )
    elif transport == "claude_content_blocks" and PurePosixPath(names["original_name"]).suffix.lower() in NATIVE_IMAGE_TYPES:
        result.update(
            representation="native_image_content_block",
            representation_evidence="Image bytes are represented as a native base64 image block, not an extracted description. The declared transport alone does not prove provider receipt or visual correctness.",
            provider_acceptance="not_attested",
            provider_interpretation="native_image_input_no_understanding_claim",
        )
    elif transport in {"utf8_json_in_prompt", "claude_content_blocks"}:
        if PurePosixPath(names["original_name"]).suffix not in TEXT_EXTENSIONS:
            raise ValueError("Automated attachment descriptions require a supported source/text filename")
        result.update(
            representation="inline_utf8_source_text",
            representation_evidence="File text is represented as quoted UTF-8/source text in the prompt; SVG is source text, not a viewed image. This metadata does not prove decoding or delivery.",
            provider_acceptance="not_attested",
            provider_interpretation="source_text_only_no_visual_input",
        )
    else:
        result.update(
            representation="staged_native_file_bytes",
            representation_evidence="Exact native file bytes are staged locally for a coordinator; this does not claim an upload or app acceptance.",
            provider_acceptance="unknown_pending_current_app_observation",
            provider_interpretation="unknown_pending_current_app_observation",
        )
    return result
