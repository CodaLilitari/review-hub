# Review results and static reports — v0.6 beta

The five new MCP tools and their CLI equivalents operate on local records. They do not contact models, spend provider usage, upload attachments, publish a report, or enable editing workers. The server now exposes 20 tools. Existing databases gain an additive `review_records` table; existing jobs and original answers remain intact.

See the [dated validation record](validation-v0.6-2026-09-25.md). To generate a fully synthetic example without reading accounts or job state, run `python scripts/demo_report.py C:\exact\new-demo.html` (optional `--format markdown`). The output file must not already exist.

## Record a structured review

After a job is `returned` or `returned_via_handoff`, use `record_review` (CLI `record-review`) with its project, job ID, a bounded envelope and evidence explaining who normalized the answer. This is an explicit normalization step; raw provider prose is never silently interpreted as a trusted schema. Each call appends a revision and binds it to the current saved answer hash.

```json
{
  "project": "C:\\Projects\\example",
  "job_id": "actual-job-id",
  "evidence": "Coordinator normalized the returned answer; no independent defect verification claimed.",
  "review": {
    "schema_version": 1,
    "summary": "A possible empty-input bug needs reproduction.",
    "findings": [{
      "id": "F1",
      "severity": "medium",
      "claim": "The calculation may divide by zero for empty input.",
      "evidence_status": "inferred",
      "anchors": [{
        "attachment_id": "actual-input-attachment-id",
        "sha256": "replace-with-the-actual-64-character-snapshot-hash",
        "start_line": 4,
        "end_line": 4,
        "quote": "    return total / count"
      }],
      "uncertainty": "The caller may exclude empty input.",
      "verification": "Run a minimal empty-input case and inspect caller constraints.",
      "proposed_change": "Handle the empty case if callers permit it."
    }],
    "limitations": ["Only the selected snapshots were reviewed."]
  }
}
```

The example deliberately contains placeholders; supply actual job/attachment IDs and hashes. Severities are `info`, `low`, `medium`, `high`, `critical`. Evidence status is `reported_demonstration`, `inferred`, or `missing_evidence`: even a reported demonstration remains a report until reproduced. Findings are bounded to 100, each with at most 16 anchors; the entire envelope is limited to 1 MiB. Additional fields, supplied check results and verification claims are refused.

`review` returns the latest revision, revision IDs, session relationship and a fresh integrity check. Anchor states distinguish `matched`, `quote_mismatch`, `hash_mismatch`, `unanchored`, `out_of_range`, `unsupported`, and `unavailable`. Checks use the exact job's saved input bytes, not the current working file or a provider-supplied path. Line numbers are one-based and inclusive. CRLF/CR normalize to LF; one terminal newline is ignored; other whitespace must match exactly. UTF-8 BOMs are decoded. Binary images/documents are not interpreted as text.

**A matching citation does not prove the claim.** Changed/missing snapshots and modified saved answers remain visible. New worker answers have an original completion hash. For older records without that hash, normalization records the bytes available at normalization time; it cannot retroactively prove their earlier integrity. The original response is always retained separately from normalized findings.

## Describe attachments honestly

`capabilities` (same CLI name, optional `--provider`) describes the implemented route contract. It is not a current account probe. Automated routes embed selected UTF-8/source snapshots and refuse binary/visual input. App routes stage native file manifests; image/document acceptance and actual session continuation remain unknown until observed in that app.

Report cards preserve original/upload filenames, MIME hints, sizes, hashes, direction and representation. An original image, SVG source, extracted text and a returned file are different inputs. Metadata alone proves neither upload nor successful interpretation. Existing exact-file staging and `attachment_files` verification remain the upload path; there is no automatic whole-folder packaging, conversion, preview execution or new native CLI image transport in this release.

## Record session relationships

`record_lineage` (CLI `record-lineage`) accepts `project`, `job_id`, `parent_job_id`, `kind`, `evidence`, and optional `omitted_context`. Both jobs must have returned in the same project, and the parent must precede the child.

- `app_conversation` requires the same app provider and exact nonempty conversation reference. Record what was observed; this is not a backend-memory guarantee.
- `snapshot_replay` records a coordinator-reported copy of earlier context. It records the parent answer/packet/attachment hashes and omitted context. This call does not perform the copy or a new send.
- Automated CLI jobs are fresh isolated requests. A returned provider session ID is retained without claiming it was resumed. Production native CLI resume/fork is not implemented and cannot be selected through this API.

Relationships append revisions. Earlier-parent ordering prevents cycles. Local client transcript restoration, server-persisted context, and a fresh request containing copied messages must not be conflated. See the separate [mock ACP contract experiment](../experimental/acpx/README.md) for the deliberately nonproduction transport work.

## Export a comparison

`comparison_report` returns static `html` or `markdown` for an explicit list of 1–16 unique job IDs from one project. It includes requested versus observed model/mode labels, delivery state, findings, checks, lineage, attachment metadata and returned prose. Missing structured findings do not imply an all-clear. The display caps each original answer at 64,000 characters and records truncation; full originals remain available through paged `result`. Reports are limited to 4 MiB.

CLI example with an exact JSON request file containing `project`, `job_ids`, and optional `format`:

```powershell
python -m coda_review_hub.cli --state-dir 'C:\exact\private-state' report '.\report-request.json' --output 'C:\Projects\example\comparison.html'
```

Without `--output`, the CLI returns the JSON result, including content. An output path must be an exact new file within the named project; it cannot overwrite an existing file or traverse links. HTML is escaped, has no scripts, active links, images or external assets, and uses a restrictive content policy. Markdown treats untrusted material as escaped literal text rather than executable/rendered provider markup. Opening a report makes no model call. Reports can contain private project material; publication remains a separate scoped action.

The production MCP client now permits 180 seconds for a call by default, configurable with `--call-timeout` from 30–600, because account catalog refresh can exceed 30 seconds. This is separate from the review generation deadline. A client timeout never authorizes an automatic retry: reconcile the saved batch first.
