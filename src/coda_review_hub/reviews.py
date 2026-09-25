"""Typed advisory findings and exact snapshot citation checks. No provider calls."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from .attachments import TEXT_EXTENSIONS, check_open_path, no_links, manifest_digest, MAX_FILE_BYTES


def text(value, name, maximum=8000, *, empty=True):
    if not isinstance(value, str) or len(value.encode('utf-8')) > maximum or (not empty and not value.strip()):
        raise ValueError(f'{name} must be bounded text (maximum {maximum} UTF-8 bytes)')
    return value


def fields(value, required, optional=()):
    if not isinstance(value, dict) or set(value) - set(required) - set(optional) or set(required) - set(value):
        raise ValueError('Unexpected or missing review fields')


def strings(value, name):
    if not isinstance(value, list) or len(value) > 50:
        raise ValueError(f'{name} must be a list of at most 50 strings')
    return [text(item, name, 4000, empty=False) for item in value]


def normalize_review(value):
    fields(value, ('schema_version', 'summary', 'findings'), ('limitations',))
    if type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise ValueError('Unsupported review schema_version; use 1')
    if not isinstance(value['findings'], list) or len(value['findings']) > 100:
        raise ValueError('findings must contain at most 100 entries')
    result = {'schema_version': 1, 'summary': text(value['summary'], 'summary'),
              'findings': [], 'limitations': strings(value.get('limitations', []), 'limitations')}
    ids = set()
    for finding in value['findings']:
        fields(finding, ('id', 'severity', 'claim'), ('evidence_status', 'anchors', 'uncertainty', 'verification', 'proposed_change'))
        identifier = text(finding['id'], 'id', 100, empty=False)
        if identifier in ids:
            raise ValueError('Finding IDs must be unique within a review')
        ids.add(identifier)
        severity = finding['severity']
        if severity not in ('info', 'low', 'medium', 'high', 'critical'):
            raise ValueError('Unknown finding severity')
        status = finding.get('evidence_status', 'inferred')
        if status not in ('reported_demonstration', 'inferred', 'missing_evidence'):
            raise ValueError('Evidence status is reported_demonstration, inferred, or missing_evidence')
        item = {'id': identifier, 'severity': severity, 'claim': text(finding['claim'], 'claim', empty=False),
                'evidence_status': status, 'anchors': []}
        for name in ('uncertainty', 'verification', 'proposed_change'):
            item[name] = text(finding.get(name, ''), name)
        anchors = finding.get('anchors', [])
        if not isinstance(anchors, list) or len(anchors) > 16:
            raise ValueError('Each finding accepts at most 16 anchors')
        for anchor in anchors:
            fields(anchor, ('attachment_id', 'sha256', 'start_line', 'end_line', 'quote'))
            aid = text(anchor['attachment_id'], 'attachment_id', 100, empty=False)
            hashed = anchor['sha256']
            if not isinstance(hashed, str) or not re.fullmatch(r'[0-9a-f]{64}', hashed):
                raise ValueError('Anchor SHA-256 must be 64 lowercase hex characters')
            start, end = anchor['start_line'], anchor['end_line']
            if type(start) is not int or type(end) is not int or not 1 <= start <= end <= 10000000 or end-start >= 1000:
                raise ValueError('Anchor line range must be positive, ordered and at most 1000 lines')
            item['anchors'].append({'attachment_id': aid, 'sha256': hashed, 'start_line': start,
                                    'end_line': end, 'quote': text(anchor['quote'], 'quote', 32000, empty=False)})
        result['findings'].append(item)
    if len(json.dumps(result, ensure_ascii=False).encode('utf-8')) > 1048576:
        raise ValueError('Review envelope exceeds 1 MiB')
    return result


def snapshot_bytes(job, item):
    """Read the recorded snapshot, never a reviewer-supplied path or current source."""
    root = Path(job['evidence_directory']).resolve(strict=True)
    path = Path(item['snapshot_path'])
    expected = root / 'attachments' / item['upload_name']
    if path != expected or path.name != item['upload_name']:
        raise ValueError('Snapshot path differs from the job manifest')
    no_links(path, root)
    with path.open('rb') as stream:
        check_open_path(stream, path)
        data = stream.read(MAX_FILE_BYTES + 1)
    no_links(path, root)
    if len(data) != item['size_bytes'] or len(data) > MAX_FILE_BYTES or hashlib.sha256(data).hexdigest() != item['sha256']:
        raise ValueError('Snapshot bytes differ from the recorded hash/size')
    return data


def check_anchors(envelope, job):
    """Return fresh checks. A match verifies a citation, never a defect or model claim."""
    result = json.loads(json.dumps(envelope))
    manifest = job.get('attachments', [])
    manifest_ok = manifest_digest(manifest) == job.get('attachment_manifest_sha256') if manifest else True
    by_id = {item['attachment_id']: item for item in manifest}
    cache = {}
    for finding in result['findings']:
        for anchor in finding['anchors']:
            item = by_id.get(anchor['attachment_id'])
            status, detail = 'unanchored', 'Attachment ID is absent from this job input manifest'
            if not manifest_ok:
                status, detail = 'unavailable', 'Recorded attachment manifest integrity check failed'
            elif item and anchor['sha256'] != item['sha256']:
                status, detail = 'hash_mismatch', 'Cited hash differs from the job input snapshot'
            elif item:
                aid = item['attachment_id']
                if aid not in cache:
                    try:
                        data = snapshot_bytes(job, item)
                        if Path(item['original_name']).suffix not in TEXT_EXTENSIONS:
                            cache[aid] = ('unsupported', 'Binary/visual source requires independent inspection')
                        else:
                            source = data.decode('utf-8-sig')
                            if any(ord(c) < 32 and c not in '\r\n\t' for c in source):
                                raise UnicodeError('Non-text control bytes')
                            lines = source.replace('\r\n', '\n').replace('\r', '\n').split('\n')
                            if lines[-1] == '':
                                lines.pop()
                            cache[aid] = ('text', lines)
                    except (OSError, ValueError, KeyError, UnicodeError):
                        cache[aid] = ('unavailable', 'Snapshot missing, changed, or not readable as UTF-8 text')
                kind, content = cache[aid]
                if kind != 'text':
                    status, detail = kind, content
                elif anchor['end_line'] > len(content):
                    status, detail = 'out_of_range', 'Cited line range exceeds the immutable snapshot'
                else:
                    actual = '\n'.join(content[anchor['start_line']-1:anchor['end_line']])
                    quote = anchor['quote'].replace('\r\n', '\n').replace('\r', '\n')
                    # One terminal line ending is immaterial; other whitespace is exact.
                    if quote.endswith('\n'):
                        quote = quote[:-1]
                    status = 'matched' if actual == quote else 'quote_mismatch'
                    detail = 'Exact quoted lines match the saved snapshot; claim remains unverified' if status == 'matched' else 'Quoted text does not exactly match the cited snapshot lines'
            anchor['check'] = {'status': status, 'detail': detail}
    result['claims_independently_verified'] = False
    return result


def default_lineage(job):
    is_app = job.get('state') in ('awaiting_handoff', 'returned_via_handoff') or 'conversation_ref' in job
    mechanism = 'app_conversation_unclassified' if is_app else 'fresh_isolated_request'
    return {'kind': 'handoff' if is_app else 'fresh', 'mechanism': mechanism,
            'parent_job_id': None, 'provider_session_id': job.get('provider_session_id'),
            'conversation_ref': job.get('conversation_ref'), 'resume_performed': False,
            'replay_performed': False, 'evidence_basis': 'Existing hub route semantics; no native resume is implemented'}
