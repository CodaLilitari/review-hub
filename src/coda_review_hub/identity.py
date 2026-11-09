"""Explicit local naming preferences, separate from route authority and credentials."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import uuid


PROVIDERS = frozenset({
    "claude", "grok", "chatgpt", "gemini", "claude-cowork", "grok-bot",
    "microsoft-copilot", "github-copilot", "gemini-cli", "gemini-desktop",
    "gemini-spark", "meta-ai", "meta-muse", "antigravity", "claude-code", "claude-desktop", "muse-code",
})
# These names were valid user aliases before the additional routes existed.
# Only reads of older profiles may preserve their former (old-route) targets.
ADDED_PROVIDERS = frozenset({"gemini-cli", "gemini-desktop", "gemini-spark", "meta-ai", "meta-muse", "antigravity", "claude-code", "claude-desktop", "muse-code"})
# Antigravity was introduced after the v0.3 routes. A pre-existing alias with
# this name may legitimately point to any earlier route, including Gemini CLI.
LEGACY_ALIAS_TARGETS = {
    name: (PROVIDERS - {"muse-code"} if name == "muse-code" else PROVIDERS - {"muse-code", "claude-code", "claude-desktop"} if name in {"claude-code", "claude-desktop"} else PROVIDERS - {"muse-code", "antigravity", "claude-code", "claude-desktop"} if name == "antigravity" else PROVIDERS - ADDED_PROVIDERS)
    for name in ADDED_PROVIDERS
}
FIELDS = frozenset({"agent_name", "user_name", "collaborators", "aliases", "context_notes", "evidence"})
IDENTIFIER = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")
CONFIGURE_MESSAGE = (
    "Identity preferences are not configured. Ask/check the user for existing agent, user, "
    "and collaborator names, then call configure_identity with evidence of their choice. "
    "Empty names are allowed when the user chooses an anonymous identity."
)


def _text(value, label: str, maximum: int, *, minimum: int = 0, multiline: bool = False) -> str:
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
        raise ValueError(f"{label} must be text with {minimum}..{maximum} characters")
    if any(ord(char) < 32 and (not multiline or char not in "\n\r\t") for char in value) or "\x7f" in value:
        raise ValueError(f"{label} contains control characters")
    return value.strip()


def _mapping(value, label: str, *, allow_legacy_aliases: bool = False) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > 32 or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be an object with at most 32 string keys")
    result = {}
    for key, item in value.items():
        if label == "aliases":
            legacy = (allow_legacy_aliases and key in ADDED_PROVIDERS
                      and isinstance(item, str) and item in LEGACY_ALIAS_TARGETS[key])
            if not IDENTIFIER.fullmatch(key) or (key in PROVIDERS and not legacy):
                raise ValueError("Aliases must be lowercase identifiers and cannot replace canonical provider names")
            if not isinstance(item, str) or item not in PROVIDERS:
                raise ValueError("Each alias must point directly to a supported canonical provider")
            result[key] = item
        else:
            if key not in PROVIDERS:
                raise ValueError(f"{label} keys must be supported canonical providers")
            result[key] = _text(item, label, 4096 if label == "context_notes" else 128,
                                multiline=label == "context_notes")
    return result


def _normalize(payload: dict, *, allow_legacy_aliases: bool = False) -> dict:
    if not isinstance(payload, dict) or payload.keys() - FIELDS or "evidence" not in payload:
        raise ValueError("Identity configuration requires evidence and accepts only names, collaborators, aliases, and context_notes")
    return {
        "agent_name": _text(payload.get("agent_name", ""), "agent_name", 128),
        "user_name": _text(payload.get("user_name", ""), "user_name", 128),
        "collaborators": _mapping(payload.get("collaborators"), "collaborators"),
        "aliases": _mapping(payload.get("aliases"), "aliases", allow_legacy_aliases=allow_legacy_aliases),
        "context_notes": _mapping(payload.get("context_notes"), "context_notes"),
        "evidence": _text(payload["evidence"], "evidence", 4000, minimum=12, multiline=True),
    }


def _read_json(path: Path) -> dict:
    raw = path.read_bytes()
    if len(raw) > 65536:
        raise ValueError("Identity profile must not exceed 64 KiB")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Identity profile must be a valid UTF-8 JSON object") from exc
    if not isinstance(value, dict):
        raise ValueError("Identity profile must be a JSON object")
    return value


class IdentityStore:
    """Persist a user-established naming choice; names never grant operational authority.

    Public installations have no seed. An explicitly supplied local seed is applied once,
    only when identity.json is absent, and cannot overwrite an existing user choice.
    """

    def __init__(self, state_dir: str | Path, seed_path: str | Path | None = None):
        self.path = Path(state_dir).expanduser().resolve() / "identity.json"
        if seed_path is not None and not self.path.exists():
            self.configure(**_read_json(Path(seed_path)))

    def read(self) -> dict:
        if not self.path.exists():
            return {"configured": False, "agent_name": "", "user_name": "", "collaborators": {},
                    "aliases": {}, "context_notes": {}, "evidence": "", "configured_at": ""}
        record = _read_json(self.path)
        if record.keys() - FIELDS - {"configured", "configured_at"} or record.get("configured") is not True:
            raise ValueError("Stored identity profile is invalid; explicitly configure the user's identity preferences")
        try:
            configured_at = datetime.fromisoformat(record["configured_at"])
            if configured_at.tzinfo is None:
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise ValueError("Stored identity profile needs a timezone-qualified configured_at timestamp") from None
        values = _normalize({key: record[key] for key in FIELDS if key in record}, allow_legacy_aliases=True)
        result = {"configured": True, **values, "configured_at": configured_at.isoformat()}
        conflicts = {alias: {"previous_target": target, "canonical_provider": alias}
                     for alias, target in values["aliases"].items() if alias in PROVIDERS}
        if conflicts:
            # Surface the preserved mapping without rewriting user choices or
            # silently promoting a former app alias into an automated route.
            result["alias_conflicts"] = conflicts
        return result

    def configure(self, *, evidence: str, agent_name: str = "", user_name: str = "",
                  collaborators: dict[str, str] | None = None, aliases: dict[str, str] | None = None,
                  context_notes: dict[str, str] | None = None) -> dict:
        """Replace the whole local profile after checking the user's naming preferences."""
        values = _normalize({"agent_name": agent_name, "user_name": user_name, "collaborators": collaborators,
                             "aliases": aliases, "context_notes": context_notes, "evidence": evidence})
        record = {"configured": True, **values, "configured_at": datetime.now(timezone.utc).isoformat()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f"identity.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as output:
                output.write(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
        return record

    def require_configured(self) -> dict:
        record = self.read()
        if not record["configured"]:
            raise ValueError(CONFIGURE_MESSAGE)
        if record.get("alias_conflicts"):
            raise ValueError("Saved aliases conflict with newly supported provider names; inspect "
                             "identity_status.alias_conflicts and explicitly configure_identity to resolve "
                             "them before outbound work")
        return record

    def greeting(self) -> str:
        record = self.require_configured()
        agent = record["agent_name"]
        speaker = f"{agent}: Hello, I'm {agent}" if agent else "Hello, I'm the coordinating assistant"
        person = record["user_name"] or "the user"
        return (f"{speaker}, collaborating with {person}. Please review only this bounded project packet. "
                "Thank you for your help.\n\n")

    def resolve_provider(self, alias: str) -> str:
        if not isinstance(alias, str):
            raise ValueError("provider must be a canonical name or configured alias")
        record = self.read()
        if alias in record.get("alias_conflicts", {}):
            raise ValueError("This saved alias conflicts with a new canonical provider; inspect "
                             "identity_status.alias_conflicts and explicitly configure_identity before use")
        provider = record["aliases"].get(alias, alias)
        if provider not in PROVIDERS:
            raise ValueError("Unknown provider or alias; check identity_status and the supported routes")
        return provider

    def note(self, provider: str) -> str:
        record = self.read()
        # Route inventory reads canonical notes even while a naming conflict
        # blocks outbound work; it must not route through the old alias.
        canonical = provider if provider in PROVIDERS else self.resolve_provider(provider)
        return record["context_notes"].get(canonical, "")
