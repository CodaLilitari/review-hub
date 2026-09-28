"""Pure static rendering of review receipts; never open files or contact providers.

Every value from the report is untrusted display text. HTML uses no active URLs,
scripts, images, or external assets. Markdown places values in escaped literals,
with fences longer than any fence in the value, rather than interpreting provider
Markdown. This module presents recorded checks; it does not perform verification.
"""
from __future__ import annotations

from collections import Counter
from html import escape
import json
import re


_CSS = """
:root{color-scheme:dark;--bg:#10141d;--panel:#19212d;--line:#334257;--ink:#e9eef7;--muted:#b4c1d3;--accent:#97c8ff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1440px;margin:auto;padding:clamp(18px,4vw,52px)}h1,h2,h3,h4{line-height:1.25;overflow-wrap:anywhere}h1{font-size:clamp(2rem,4vw,3rem);margin:10px 0}h2{margin-top:2.2rem}h3{margin:0 0 1rem}h4{margin:1.2rem 0 .7rem}
p{margin:.65rem 0}.eyebrow{color:var(--accent);font-size:.8rem;letter-spacing:.1em;text-transform:uppercase}.muted,.note{color:var(--muted)}.note{border-left:3px solid var(--accent);padding:.5rem 1rem;background:#141d29}
.stats{display:flex;flex-wrap:wrap;gap:10px;margin:22px 0}.stat,.badge{display:inline-block;border:1px solid var(--line);border-radius:8px;padding:6px 11px;background:var(--panel)}.stat strong{font-size:1.2rem;margin-right:5px}.badge{font-size:.82rem;white-space:normal}.received{border-color:#5d917b}.pending{border-color:#ad955b}.problem{border-color:#b47a84}
.table-scroll{overflow-x:auto;border:1px solid var(--line);border-radius:10px}table{border-collapse:collapse;width:100%;min-width:760px;text-align:left}th,td{padding:12px 15px;border-bottom:1px solid var(--line);vertical-align:top;overflow-wrap:anywhere}th{background:#202c3b;font-size:.84rem;color:var(--muted)}td{max-width:290px}tbody tr:last-child td{border-bottom:0}
.jobs{display:grid;gap:24px}.job{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:clamp(16px,3vw,30px)}.job-head{display:flex;justify-content:space-between;gap:15px;align-items:start}.meta{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:5px 24px}.meta div{padding:5px 0;min-width:0}dt{font-size:.8rem;color:var(--muted)}dd{margin:2px 0;overflow-wrap:anywhere;white-space:pre-wrap}.finding{border:1px solid var(--line);border-radius:8px;padding:18px;margin:14px 0;background:#141c27}.anchor{border-left:2px solid var(--line);padding-left:15px;margin:14px 0}.file{border-top:1px solid var(--line);padding:12px 0}.file strong{overflow-wrap:anywhere}
pre{white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word;background:#0e151e;padding:16px;border:1px solid var(--line);border-radius:8px;font: .88rem/1.6 ui-monospace,Consolas,monospace}details{margin:14px 0}summary{cursor:pointer;color:var(--accent);overflow-wrap:anywhere}li{overflow-wrap:anywhere}.literal{white-space:pre-wrap;overflow-wrap:anywhere}footer{margin-top:30px;color:var(--muted);font-size:.85rem}
@media(max-width:680px){.meta{grid-template-columns:1fr}.job-head{display:block}.badge{margin-bottom:10px}main{padding:16px}table{font-size:.9rem}}
@media print{:root{color-scheme:light;--bg:white;--panel:white;--ink:#111;--muted:#333;--line:#bbb;--accent:#18446b}body,pre,.finding,.note,th{background:white;color:#111}main{padding:0}.job{break-inside:avoid}details{display:block}}
"""
_STATE_CLASSES = {
    "returned": "received", "returned_via_handoff": "received",
    "prepared": "pending", "running": "pending", "awaiting_handoff": "pending", "needs_continuation": "pending",
    "blocked": "problem", "failed": "problem", "delivery_unknown": "problem",
    "cancelled": "problem", "interrupted": "problem",
}
_NOTICE = (
    "Review claims are advice, not verified conclusions. Anchor checks describe cited "
    "snapshots and do not prove a finding is correct. Requested model settings, observed "
    "labels, delivery receipts, and independent verification remain separate."
)
_ATTACHMENT_NOTICE = (
    "Original files and text representations are distinct. An embedded text snapshot "
    "does not establish a native-file upload or visual inspection; SVG source is not a "
    "viewed image. This report displays metadata only and never loads the listed files."
)


def _value(value, default: str = "Not recorded") -> str:
    if value is None or value == "":
        return default
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def _html(value, default: str = "Not recorded") -> str:
    return escape(_value(value, default), quote=True)


def _mapping(value) -> dict:
    return value if isinstance(value, dict) else {}


def _items(value) -> list:
    return value if isinstance(value, list) else []


def _metadata(job: dict) -> list[tuple[str, object]]:
    return [
        ("Job ID", job.get("id")), ("Provider", job.get("provider")),
        ("State", job.get("state")), ("Submission / delivery", job.get("submission")),
        ("Requested model", job.get("model")), ("Requested thinking / effort", job.get("effort")),
        ("Observed app model", job.get("observed_model")), ("Observed app mode", job.get("observed_mode")),
        ("CLI-observed models", job.get("observed_cli_models")),
        ("Response-reported models", job.get("verified_response_models")),
        ("Model evidence", job.get("model_evidence", job.get("model_observation_basis"))),
        ("Independent findings verification recorded", job.get("claims_independently_verified")),
        ("Created", job.get("created_at")), ("Started", job.get("started_at")),
        ("Finished", job.get("finished_at")), ("Session continuity", job.get("session_continuity")),
        ("Conversation reference (text only)", job.get("conversation_ref")),
        ("App completion observation", job.get("completion")),
        ("Completion turn ID", job.get("completion_turn_id")),
        ("Separate app response turns (use result with turn_id for verbatim text)", [
            {key: turn.get(key) for key in (
                "turn_id", "recorded_at", "previous_turn_id", "previous_answer_sha256",
                "answer_sha256", "conversation_ref", "completion", "observed_model", "observed_mode")}
            for turn in _items(job.get("handoff_turns")) if isinstance(turn, dict)]),
        ("Packet SHA-256", job.get("packet_sha256")), ("Answer SHA-256", job.get("answer_sha256")),
        ("Source answer integrity", job.get("source_answer_integrity")),
        ("Answer display notice", job.get("answer_notice")),
        ("Error / interruption", job.get("error", job.get("local_stop_reason"))),
    ]


def _review_metadata(review: dict) -> list[tuple[str, object]]:
    return [("Review recorded", review.get("recorded_at")),
            ("Source answer SHA-256", review.get("source_answer_sha256"))]


def _finding_metadata(finding: dict) -> list[tuple[str, object]]:
    return [("Severity (reported)", finding.get("severity")),
            ("Evidence status (recorded)", finding.get("evidence_status")),
            ("Claim", finding.get("claim")), ("Uncertainty", finding.get("uncertainty")),
            ("Verification", finding.get("verification")),
            ("Proposed change", finding.get("proposed_change"))]


def _anchor_metadata(anchor: dict) -> list[tuple[str, object]]:
    check = _mapping(anchor.get("check"))
    return [("Attachment ID", anchor.get("attachment_id")), ("SHA-256", anchor.get("sha256")),
            ("Start line", anchor.get("start_line")), ("End line", anchor.get("end_line")),
            ("Anchor check", check.get("status", "Not checked")), ("Check detail", check.get("detail"))]


def _html_fields(fields: list[tuple[str, object]]) -> str:
    return '<dl class="meta">' + "".join(
        f"<div><dt>{escape(label)}</dt><dd>{_html(value)}</dd></div>" for label, value in fields
    ) + "</dl>"


def _html_literal(value, default="Not recorded") -> str:
    return f"<pre>{_html(value, default)}</pre>"


def _attachment_lists(item: dict) -> list[tuple[str, list]]:
    attachments = _mapping(item.get("attachments"))
    return [("Inputs", _items(attachments.get("input"))),
            ("Returned artifacts", _items(attachments.get("output")))]


def _html_attachments(item: dict, job: dict) -> str:
    parts = ["<h4>Attachments and representations</h4>", f'<p class="note">{_ATTACHMENT_NOTICE}</p>',
             _html_fields([("Input transport", job.get("attachment_transport")),
                           ("Attachment delivery", job.get("attachment_delivery"))])]
    for label, files in _attachment_lists(item):
        parts.append(f"<h4>{label}</h4>")
        if not files:
            parts.append('<p class="muted">None recorded.</p>')
        for raw in files:
            file = _mapping(raw)
            title = file.get("relative_name", file.get("original_name", file.get("attachment_id")))
            parts.extend(['<div class="file">', f"<strong>{_html(title, 'Attachment')}</strong>",
                          _html_fields([("Original filename", file.get("original_name")),
                                        ("Attachment ID", file.get("attachment_id")),
                                        ("Snapshot SHA-256", file.get("sha256")),
                                        ("Snapshot size (bytes)", file.get("size_bytes")),
                                        ("Media type hint", file.get("media_type_hint")),
                                        ("Representation / derivation", file.get("representation", file.get("derivation")))]),
                          "<details><summary>Complete snapshot and representation metadata (text only)</summary>",
                          _html_literal(raw), "</details></div>"])
    return "".join(parts)


def _html_review(review) -> str:
    if not isinstance(review, dict):
        return '<h4>Structured findings</h4><p class="muted">No structured review recorded. This is not a finding of no issues.</p>'
    parts = ["<h4>Review summary</h4>", f'<p class="literal">{_html(review.get("summary"))}</p>',
             _html_fields(_review_metadata(review)), "<h4>Structured findings</h4>"]
    findings = _items(review.get("findings"))
    if not findings:
        parts.append('<p class="muted">No structured findings recorded; no independent all-clear is implied.</p>')
    for index, raw in enumerate(findings, 1):
        finding = _mapping(raw)
        parts.extend(['<section class="finding">',
                      f"<h4>Finding {index} · {_html(finding.get('id'), 'ID not recorded')}</h4>",
                      _html_fields(_finding_metadata(finding)), "<h4>Evidence anchors</h4>"])
        anchors = _items(finding.get("anchors"))
        if not anchors:
            parts.append('<p class="muted">No evidence anchors recorded.</p>')
        for anchor in anchors:
            anchor = _mapping(anchor)
            parts.extend(['<div class="anchor">', _html_fields(_anchor_metadata(anchor)),
                          "<p>Quoted evidence</p>", _html_literal(anchor.get("quote")), "</div>"])
        parts.append("</section>")
    limitations = _items(review.get("limitations"))
    parts.append("<h4>Limitations</h4>")
    parts.append("<ul>" + "".join(f"<li>{_html(value)}</li>" for value in limitations) + "</ul>"
                 if limitations else '<p class="muted">No limitations recorded.</p>')
    return "".join(parts)


def _render_html(data: dict) -> str:
    jobs = data["jobs"]
    counts = Counter(_value(_mapping(item.get("job")).get("state"), "Unknown") for item in jobs)
    parts = ['<!doctype html><html lang="en"><head><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width, initial-scale=1">',
             '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; script-src \'none\'; img-src \'none\'; object-src \'none\'; base-uri \'none\'; form-action \'none\'">',
             '<meta name="referrer" content="no-referrer"><title>Review Hub comparison</title>',
             f"<style>{_CSS}</style></head><body><main>", '<header><div class="eyebrow">Review Hub · static report</div>',
             "<h1>Review comparison</h1>", f'<p class="literal">{_html(data.get("project"), "Project not recorded")}</p>',
             f'<p class="muted">Generated: {_html(data.get("generated_at"))}</p></header>',
             f'<p class="note">{_NOTICE}</p>', '<div class="stats">',
             f'<span class="stat"><strong>{len(jobs)}</strong>review jobs</span>']
    parts.extend(f'<span class="stat"><strong>{count}</strong>{_html(state)}</span>'
                 for state, count in sorted(counts.items()))
    parts.extend(["</div>", "<h2>Comparison</h2>"])
    if jobs:
        parts.append('<div class="table-scroll"><table><thead><tr><th>Reviewer</th><th>Requested model / effort</th><th>Observed labels</th><th>State / delivery</th><th>Structured review</th></tr></thead><tbody>')
        for item in jobs:
            job, review = _mapping(item.get("job")), item.get("review")
            observed = job.get("observed_model") or job.get("observed_cli_models") or job.get("verified_response_models")
            count = len(_items(review.get("findings"))) if isinstance(review, dict) else None
            parts.append("<tr>" + "".join(f"<td>{value}</td>" for value in [
                _html(job.get("provider")), _html(job.get("model")) + "<br>" + _html(job.get("effort")),
                _html(observed) + "<br>" + _html(job.get("observed_mode")),
                _html(job.get("state"), "Unknown") + "<br>" + _html(job.get("submission")),
                "Not recorded" if count is None else f"{count} recorded finding(s)",
            ]) + "</tr>")
        parts.append("</tbody></table></div>")
    else:
        parts.append('<p class="muted">No review jobs recorded.</p>')
    parts.append('<h2>Review receipts</h2><div class="jobs">')
    for index, item in enumerate(jobs, 1):
        job = _mapping(item.get("job"))
        state = _value(job.get("state"), "Unknown")
        style = _STATE_CLASSES.get(state, "")
        parts.extend(['<article class="job">', '<div class="job-head">',
                      f"<h3>{index}. {_html(job.get('provider'), 'Reviewer not recorded')}</h3>",
                      f'<span class="badge {style}">{_html(state)}</span></div>',
                      _html_fields(_metadata(job)), "<h4>Lineage and continuity</h4>",
                      _html_literal(item.get("lineage") or None), _html_attachments(item, job),
                      _html_review(item.get("review")),
                      "<details><summary>Raw answer · untrusted text</summary>",
                      _html_literal(item.get("answer"), "No answer recorded. The job may be incomplete or awaiting handoff."),
                      "</details></article>"])
    parts.extend(["</div><details><summary>Capabilities as recorded</summary>",
                  _html_literal(data.get("capabilities")), "</details>",
                  "<footer>Static export. No scripts, external assets, active links, file previews, or provider actions.</footer>",
                  "</main></body></html>"])
    return "".join(parts)


def _md_literal(value, default="Not recorded", *, inline=False) -> str:
    # Escaped HTML is intentionally visible as literal entities in Markdown's
    # code spans/blocks. This avoids relying on the viewer's HTML sanitization.
    text = escape(_value(value, default), quote=False).replace("\r\n", "\n").replace("\r", "\n")
    if inline:
        text = " ".join(text.split()).replace("|", "&#124;")
    longest = max((len(match.group()) for match in re.finditer(r"`+", text)), default=0)
    fence = "`" * max(1 if inline else 3, longest + 1)
    return f"{fence} {text} {fence}" if inline else f"{fence}text\n{text}\n{fence}"


def _md_fields(fields: list[tuple[str, object]]) -> str:
    parts = []
    for label, value in fields:
        text = _value(value)
        if "\n" not in text and "\r" not in text and len(text) <= 160:
            parts.append(f"- **{label}:** {_md_literal(value, inline=True)}")
        else:
            parts.append(f"**{label}**\n\n{_md_literal(value)}")
    return "\n\n".join(parts)


def _render_markdown(data: dict) -> str:
    parts = ["# Review comparison", "**Project**", _md_literal(data.get("project")),
             "**Generated**", _md_literal(data.get("generated_at")), _NOTICE, "## Comparison"]
    jobs = data["jobs"]
    if jobs:
        rows = ["| Reviewer | Requested model | Effort | State | Delivery |",
                "|---|---|---|---|---|"]
        for item in jobs:
            job = _mapping(item.get("job"))
            rows.append("| " + " | ".join(_md_literal(job.get(key), inline=True)
                                             for key in ("provider", "model", "effort", "state", "submission")) + " |")
        parts.append("\n".join(rows))
    else:
        parts.append("No review jobs recorded.")
    for index, item in enumerate(jobs, 1):
        job = _mapping(item.get("job"))
        parts.extend([f"## Review job {index}", _md_fields(_metadata(job)),
                      "### Lineage and continuity", _md_literal(item.get("lineage") or None),
                      "### Attachments and representations", _ATTACHMENT_NOTICE,
                      _md_fields([("Input transport", job.get("attachment_transport")),
                                  ("Attachment delivery", job.get("attachment_delivery"))])])
        for label, files in _attachment_lists(item):
            parts.append(f"#### {label}")
            if files:
                parts.extend(_md_literal(file) for file in files)
            else:
                parts.append("None recorded.")
        review = item.get("review")
        if not isinstance(review, dict):
            parts.extend(["### Structured findings", "No structured review recorded. This is not a finding of no issues."])
        else:
            parts.extend(["### Review summary", _md_literal(review.get("summary")),
                          _md_fields(_review_metadata(review)), "### Structured findings"])
            findings = _items(review.get("findings"))
            if not findings:
                parts.append("No structured findings recorded; no independent all-clear is implied.")
            for number, raw in enumerate(findings, 1):
                finding = _mapping(raw)
                parts.extend([f"#### Finding {number}", "**Finding ID**", _md_literal(finding.get("id")),
                              _md_fields(_finding_metadata(finding)), "**Evidence anchors**"])
                anchors = _items(finding.get("anchors"))
                if not anchors:
                    parts.append("No evidence anchors recorded.")
                for raw_anchor in anchors:
                    anchor = _mapping(raw_anchor)
                    parts.extend([_md_fields(_anchor_metadata(anchor)), "**Quoted evidence**", _md_literal(anchor.get("quote"))])
            parts.append("### Limitations")
            limitations = _items(review.get("limitations"))
            if limitations:
                parts.extend(_md_literal(value) for value in limitations)
            else:
                parts.append("No limitations recorded.")
        parts.extend(["<details><summary>Raw answer · HTML-escaped literal</summary>",
                      _md_literal(item.get("answer"), "No answer recorded. The job may be incomplete or awaiting handoff."),
                      "</details>"])
    parts.extend(["## Capabilities as recorded", _md_literal(data.get("capabilities")),
                  "Static export. Provider text is displayed as escaped literals; no file or image is embedded."])
    return "\n\n".join(parts) + "\n"


def render_report(data: dict, format: str = "html") -> str:
    """Render schema v1 receipt data without trusting markup or reading artifacts."""
    if format not in {"html", "markdown"}:
        raise ValueError("Report format must be html or markdown")
    if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        raise ValueError("Report requires schema_version 1")
    if not isinstance(data.get("jobs"), list) or any(not isinstance(item, dict) for item in data["jobs"]):
        raise ValueError("Report jobs must be a list of objects")
    return _render_html(data) if format == "html" else _render_markdown(data)
