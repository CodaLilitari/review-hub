"""Pure, conservative classification of coordinator-observed app responses.

No text heuristic proves completion. Interruption phrases may be quoted from
earlier turns, so they deliberately preserve a partial result until the caller
supplies a later response/observation that actually closes the remaining work.
This module does not inspect an app, infer delivery, or mutate receipt history.
"""
from __future__ import annotations

import re


STATUSES = frozenset({
    "unknown", "completed", "incomplete", "tool_limit", "output_limit",
    "cancelled", "provider_error", "delivery_unknown",
})
OBSERVATION_FIELDS = frozenset({
    "status", "provider_stop_reason", "continue_available",
    "outstanding_checks", "resolved_checks",
})
INTERRUPTIONS = frozenset({
    "tool_limit", "output_limit", "cancelled", "provider_error", "delivery_unknown",
})
STOP_REASONS = {
    "tool_budget": "tool_limit", "max_tools": "tool_limit", "tool_use_limit": "tool_limit",
    "tool_limit": "tool_limit", "tool_budget_exhausted": "tool_limit",
    "tool_call_limit": "tool_limit", "max_tool_calls": "tool_limit",
    "max_turns": "tool_limit", "error_max_turns": "tool_limit",
    # These end or pause a provider turn without establishing that the review
    # finished. Refusal is not evidence of tool-budget exhaustion.
    "pause_turn": "incomplete", "tool_use": "incomplete", "refusal": "incomplete",
    "max_tokens": "output_limit", "length": "output_limit", "output_limit": "output_limit",
    "cancelled": "cancelled", "canceled": "cancelled",
    "error": "provider_error", "provider_error": "provider_error",
    "delivery_unknown": "delivery_unknown", "timeout": "delivery_unknown",
    "end_turn": "completed", "stop_sequence": "completed", "completed": "completed", "success": "completed",
}
TEXT_CUES = {
    "tool_limit": (
        "reached its tool-use limit", "ran out of tool budget",
        "hit the tool limit", "hit the tool-use limit", "hit its tool-use limit",
        "reached the tool-use limit", "reached my tool-use limit",
        "tool-use limit reached", "tool-use limit has been reached",
    ),
    "output_limit": (
        "reached its output limit", "reached the output limit", "hit the output limit",
        "reached its output token limit", "reached the output token limit",
        "ran out of output tokens", "reached the maximum output length",
        "maximum output length reached", "output limit reached",
    ),
    "incomplete": (
        "checks remain unfinished", "checks remain open", "not completed", "not re-verified this pass",
    ),
}
TEXT_PATTERNS = {
    "tool_limit": (
        # Only explicit exhaustion/reached notices: discussion of tool budgets,
        # a configured --max-turns value, or a currency budget is not a cue.
        r"(?:tool(?:[ -](?:call|use))?|turn)[ -](?:limit|budget) (?:has been |was )?(?:reached|exceeded|exhausted)",
        r"(?:hit|reached|exceeded) (?:the |my |its |our |your )?(?:tool(?:[ -](?:call|use))?|turn)[ -](?:limit|budget)",
        r"(?:hit|reached|exceeded) (?:the |my |its |our |your )?maximum (?:allowed )?(?:number of )?(?:[0-9]+ )?(?:tool(?:[ -](?:call|use))?s|turns)",
        r"(?:ran|run) out of (?:tool[ -](?:calls|uses)|turns)",
        r"exhausted (?:the |my |its |our |your )?(?:tool(?:[ -](?:call|use))? (?:budget|limit)|tool[ -](?:calls|uses)|turn (?:budget|limit))",
    ),
}
BASIS = (
    "Coordinator-supplied status, stop reason, checks, and response/evidence text; "
    "no app or provider UI was inspected. Exact text cues are conservative and may quote "
    "earlier interruptions or unfinished work; they can preserve a partial result but cannot establish completion. "
    "This is bounded phrase matching, not a general understanding of the response or approval of the reviewed artifact."
)


def _checks(value, name: str) -> list[str]:
    if not isinstance(value, list) or len(value) > 64:
        raise ValueError(f"{name} must be a list of at most 64 unique checks")
    normalized, seen = [], set()
    for item in value:
        if (not isinstance(item, str) or not item.strip() or len(item) > 500
                or any(ord(char) < 32 or ord(char) == 127 for char in item)):
            raise ValueError(f"{name} entries must contain 1..500 characters without control characters")
        check = item.strip()
        if check in seen:
            raise ValueError(f"{name} must contain unique checks")
        seen.add(check)
        normalized.append(check)
    return normalized


def _cue_text(value: str) -> str:
    # Match the same bounded phrases across wrapping/case and typographic hyphens.
    value = value.casefold().translate(str.maketrans({char: "-" for char in "\u2010\u2011\u2012\u2013\u2014\u2015"}))
    return " ".join(value.split())


def classify_completion(response: str, evidence: str, observation: dict | None,
                        prior_outstanding: list[str]) -> dict:
    """Classify one app turn without promoting an unobserved finish to success.

    Recognized interruption reasons outrank reported completion. An explicit
    incomplete status, a Continue action, or any outstanding work prevents
    completion even after a recognized success reason. Unknown nonempty stop
    reasons never prove completion. Prior checks carry forward until explicitly
    resolved by exact normalized text; the merged open list stays bounded at 64.

    The returned stop reason preserves its supplied spelling after outer-space
    trimming; comparison alone normalizes case, spaces, and hyphens. Returned
    values are fresh data, not verification of the coordinator's observations.
    """
    if not isinstance(response, str) or not isinstance(evidence, str):
        raise ValueError("response and evidence must be strings")
    if observation is not None and (not isinstance(observation, dict)
                                     or set(observation) - OBSERVATION_FIELDS):
        raise ValueError("Completion observation contains unsupported fields or is not an object")
    supplied = {} if observation is None else observation
    reported = supplied.get("status", "unknown")
    if not isinstance(reported, str) or reported not in STATUSES:
        raise ValueError("Unsupported completion status")
    raw_reason = supplied.get("provider_stop_reason", "")
    if (not isinstance(raw_reason, str) or len(raw_reason) > 128
            or any(ord(char) < 32 or ord(char) == 127 for char in raw_reason)):
        raise ValueError("provider_stop_reason must be text of at most 128 characters without controls")
    raw_reason = raw_reason.strip()
    reason = re.sub(r"[ -]+", "_", raw_reason.casefold())
    reason_status = STOP_REASONS.get(reason)
    continued = supplied.get("continue_available", False)
    if type(continued) is not bool:
        raise ValueError("continue_available must be a boolean")
    prior = _checks(prior_outstanding, "prior_outstanding")
    outstanding = _checks(supplied.get("outstanding_checks", []), "outstanding_checks")
    resolved = _checks(supplied.get("resolved_checks", []), "resolved_checks")
    resolved_set = set(resolved)
    if not resolved_set.issubset(prior):
        raise ValueError("resolved_checks must be a subset of prior_outstanding")
    if resolved_set.intersection(outstanding):
        raise ValueError("resolved_checks cannot overlap outstanding_checks")
    carried = [check for check in prior if check not in resolved_set]
    merged = carried + [check for check in outstanding if check not in carried]
    if len(merged) > 64:
        raise ValueError("Merged outstanding checks exceed the 64-check limit")

    signals = []
    if observation is None:
        signals.append("observation_missing")
    signals.append("reported_status:" + reported)
    if raw_reason:
        signals.append("provider_stop_reason:" + reason if reason_status else "unrecognized_provider_stop_reason")
    if reported in INTERRUPTIONS:
        signals.append("reported_interruption:" + reported)
    if reported == "incomplete":
        signals.append("reported_incomplete")
    text_interruptions = set()
    for source, value in (("response", response), ("evidence", evidence)):
        normalized = _cue_text(value)
        for status, phrases in TEXT_CUES.items():
            phrases_match = any(re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", normalized) for phrase in phrases)
            patterns_match = any(re.search(r"(?<!\w)(?:" + pattern + r")(?!\w)", normalized)
                                 for pattern in TEXT_PATTERNS.get(status, ()))
            if phrases_match or patterns_match:
                text_interruptions.add(status)
                signals.append(source + "_cue:" + status)
    if continued:
        signals.append("continue_available")
    if outstanding:
        signals.append("reported_outstanding_checks")
    if carried:
        signals.append("prior_outstanding_checks_carried")
    if resolved:
        signals.append("prior_checks_resolved")

    if reason_status in INTERRUPTIONS:
        classified = reason_status
    elif reported in INTERRUPTIONS:
        classified = reported
    elif text_interruptions:
        classified = ("tool_limit" if "tool_limit" in text_interruptions else
                      "output_limit" if "output_limit" in text_interruptions else "incomplete")
    elif reason_status == "incomplete" or reported == "incomplete" or continued or merged:
        classified = "incomplete"
    elif raw_reason and reason_status is None:
        classified = "unknown"
    elif reason_status == "completed" or reported == "completed":
        classified = "completed"
        signals.append("explicit_completion_observation")
    else:
        classified = "unknown"
    return {
        "status": classified,
        "complete": classified == "completed",
        "provider_stop_reason": raw_reason,
        "continue_available": continued,
        "outstanding_checks": merged,
        "resolved_checks": resolved,
        "reported_status": reported,
        "signals": signals,
        "basis": BASIS,
    }
