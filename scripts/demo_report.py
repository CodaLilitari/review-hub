"""Render a synthetic static report. No account, runtime state or provider access."""
import argparse
import hashlib
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from coda_review_hub.reporting import render_report
from coda_review_hub.capabilities import all_capabilities


def sample():
    source = b'def average(values):\n    return sum(values) / len(values)\n'
    hashed = hashlib.sha256(source).hexdigest()
    return {'schema_version': 1, 'project': 'Synthetic demonstration — no live provider request',
            'generated_at': 'Example data', 'capabilities': all_capabilities(), 'jobs': [{
                'job': {'id': 'example-returned', 'provider': 'claude-code', 'state': 'returned',
                        'model': 'example-selected-model', 'effort': 'high',
                        'observed_cli_models': ['example-observed-label'],
                        'model_evidence': 'Synthetic labels, not a real model observation',
                        'submission': 'synthetic_response_fixture', 'claims_independently_verified': False,
                        'source_answer_integrity': 'Synthetic fixture', 'answer_notice': '',
                        'attachment_transport': 'utf8_json_in_prompt'},
                'answer': 'Synthetic reviewer: empty input may raise an error. Check the intended contract.',
                'lineage': {'kind': 'fresh', 'resume_performed': False, 'parent_job_id': None},
                'attachments': {'input': [{'attachment_id': 'sample-source', 'original_name': 'average.py',
                                           'upload_name': '01-average.py', 'size_bytes': len(source), 'sha256': hashed,
                                           'representation': 'inline_utf8_source_text'}], 'output': []},
                'review': {'schema_version': 1, 'summary': 'One possible boundary error needs independent verification.',
                           'limitations': ['Synthetic demonstration. No model was consulted or defect certified.'],
                           'findings': [{'id': 'F1', 'severity': 'medium', 'claim': 'Empty input may divide by zero.',
                                         'evidence_status': 'inferred', 'uncertainty': 'The caller may exclude empty input.',
                                         'verification': 'Exercise empty input and inspect the caller contract.',
                                         'proposed_change': 'Handle empty input if it is valid for this function.',
                                         'anchors': [{'attachment_id': 'sample-source', 'sha256': hashed,
                                                      'start_line': 2, 'end_line': 2,
                                                      'quote': '    return sum(values) / len(values)',
                                                      'check': {'status': 'matched', 'detail': 'Synthetic citation-check example; this label does not prove the claim.'}}]}]}},
                {'job': {'id': 'example-handoff', 'provider': 'chatgpt', 'state': 'awaiting_handoff',
                         'model': 'user-selected-app-model', 'effort': 'user-selected-mode', 'submission': 'not_sent'},
                 'answer': '', 'review': None, 'attachments': {'input': [], 'output': []},
                 'lineage': {'kind': 'handoff', 'mechanism': 'Prepared packet only; no delivery or resume claim'}}]}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path, help='Exact new HTML or Markdown file; never overwritten.')
    parser.add_argument('--format', choices=('html', 'markdown'), default='html')
    args = parser.parse_args()
    with args.output.open('x', encoding='utf-8') as stream:
        stream.write(render_report(sample(), args.format))
    print(str(args.output.resolve()))
