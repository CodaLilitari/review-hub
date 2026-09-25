"""Offline adversarial contracts for advisory findings, lineage and report export."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_core
from coda_review_hub import cli
from coda_review_hub.reviews import normalize_review


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_core.HubTests('test_fresh_observation_and_exact_packet_bytes')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.hub = self.fixture.hub
        self.project = str(self.fixture.project)
        self.source = self.fixture.project / 'sample.py'
        self.source.write_bytes(b'first\r\nsecond\r\nthird\r\n')

    def returned(self, ref='synthetic-conversation', source=True):
        test_core.seed_models(self.hub)
        prepared = self.hub.handoff(self.project, 'chatgpt', 'Synthetic review only.', ref,
                                    [str(self.source)] if source else None)
        job = prepared['job']
        self.hub.record_handoff_result(self.project, job['id'], 'Synthetic returned advice.',
                                      'Observed synthetic response for offline test.', ref,
                                      observed_attachment_ids=[a['attachment_id'] for a in job.get('attachments', [])],
                                      attachment_evidence='Observed synthetic attachment chips only.')
        return job

    def envelope(self, job):
        attachment = job['attachments'][0]
        return {'schema_version': 1, 'summary': 'Synthetic conclusion.', 'findings': [
            {'id': 'f-1', 'severity': 'medium', 'claim': 'This is advice, not a proof.',
             'anchors': [{'attachment_id': attachment['attachment_id'], 'sha256': attachment['sha256'],
                          'start_line': 2, 'end_line': 2, 'quote': 'second\n'}]}]}

    def record(self, job, envelope=None):
        return self.hub.record_review(self.project, job['id'], envelope or self.envelope(job),
                                      'Coordinator normalized this synthetic response.')

    def test_exact_snapshot_match_after_source_changed(self):
        job = self.returned()
        self.source.write_text('Current working file changed.', encoding='utf-8')
        result = self.record(job)
        self.assertEqual(result['findings'][0]['anchors'][0]['check']['status'], 'matched')
        self.assertFalse(result['claims_independently_verified'])
        self.assertEqual(self.hub.review(self.project, job['id'])['source_answer_integrity'], 'matched')
        self.fixture.launch.assert_not_called()

    def test_anchor_failures_are_distinct(self):
        job = self.returned()
        for changes, expected in [({'quote': 'invented'}, 'quote_mismatch'),
                                  ({'sha256': '0'*64}, 'hash_mismatch'),
                                  ({'attachment_id': 'unknown'}, 'unanchored'),
                                  ({'end_line': 99}, 'out_of_range')]:
            with self.subTest(expected=expected):
                envelope = self.envelope(job)
                envelope['findings'][0]['anchors'][0].update(changes)
                result = self.record(job, envelope)
                self.assertEqual(result['findings'][0]['anchors'][0]['check']['status'], expected)

    def test_unicode_separators_do_not_change_source_line_numbers(self):
        for separator in ('\u2028', '\u2029', '\u0085'):
            with self.subTest(separator=repr(separator)):
                self.source.write_bytes(('alpha'+separator+'beta\ngamma\n').encode('utf-8'))
                job = self.returned()
                value = self.envelope(job)
                value['findings'][0]['anchors'][0]['quote'] = 'beta'
                result = self.record(job, value)
                self.assertEqual(result['findings'][0]['anchors'][0]['check']['status'], 'quote_mismatch')
                value['findings'][0]['anchors'][0]['quote'] = 'gamma'
                result = self.record(job, value)
                self.assertEqual(result['findings'][0]['anchors'][0]['check']['status'], 'matched')

    def test_snapshot_tamper_is_rechecked_without_destroying_original_receipt(self):
        job = self.returned()
        first = self.record(job)
        Path(job['attachments'][0]['snapshot_path']).write_bytes(b'first\nforged\nthird\n')
        latest = self.hub.review(self.project, job['id'])
        self.assertEqual(latest['review']['findings'][0]['anchors'][0]['check']['status'], 'unavailable')
        self.assertEqual(latest['review']['record_id'], first['record_id'])

    def test_original_answer_tamper_blocks_new_normalization(self):
        job = self.returned()
        self.record(job)
        (Path(job['evidence_directory'])/'answer.txt').write_text('changed', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.record(job)
        self.assertEqual(self.hub.review(self.project, job['id'])['source_answer_integrity'], 'unavailable_or_changed')

    def test_append_only_revisions(self):
        job = self.returned()
        first = self.record(job)
        second = self.record(job)
        result = self.hub.review(self.project, job['id'])
        self.assertEqual([r['id'] for r in result['revisions']], [first['record_id'], second['record_id']])
        self.assertEqual(result['review']['record_id'], second['record_id'])

    def test_foreign_project_and_pending_job_refused(self):
        job = self.returned()
        with self.assertRaises(ValueError):
            self.hub.record_review(str(self.fixture.other_project), job['id'], self.envelope(job), 'Evidence.')
        test_core.seed_models(self.hub)
        pending = self.hub.handoff(self.project, 'chatgpt', 'Pending synthetic review')['job']
        with self.assertRaises(ValueError):
            self.hub.record_review(self.project, pending['id'], self.envelope(job), 'Evidence.')

    def test_forged_validation_unknown_fields_and_bad_ranges_rejected(self):
        job = self.returned()
        base = self.envelope(job)
        for edits in [{'check': {'status': 'matched'}}, {'start_line': True}, {'start_line': 0},
                      {'end_line': 1}, {'sha256': 'fake'}, {'quote': ''}, {'source_path': 'C:/private.txt'}]:
            value = copy.deepcopy(base)
            value['findings'][0]['anchors'][0].update(edits)
            with self.subTest(edits=edits), self.assertRaises(ValueError):
                normalize_review(value)
        for changes in [{'claims_independently_verified': True}, {'schema_version': True}, {'findings': [{}]},
                        {'findings': base['findings']*2}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                normalize_review({**base, **changes})

    def test_binary_source_is_unsupported_not_visual_verification(self):
        self.source = self.fixture.project / 'image.png'
        self.source.write_bytes(b'Not an image decoder fixture')
        job = self.returned()
        result = self.record(job)
        self.assertEqual(result['findings'][0]['anchors'][0]['check']['status'], 'unsupported')

    def test_same_app_lineage_and_no_native_resume(self):
        parent, child = self.returned(), self.returned()
        result = self.hub.record_lineage(self.project, child['id'], parent['id'], 'app_conversation',
                                         'Observed replies in the same synthetic app conversation.')
        self.assertEqual(result['parent_job_id'], parent['id'])
        self.assertFalse(result['resume_performed'])
        self.assertFalse(result['replay_performed'])
        self.assertEqual(self.hub.review(self.project, child['id'])['lineage']['kind'], 'app_conversation')
        with self.assertRaises(ValueError):
            self.hub.record_lineage(self.project, child['id'], parent['id'], 'native_resume', 'Not implemented.')

    def test_lineage_requires_returned_earlier_parent_and_same_app(self):
        parent, child = self.returned(), self.returned(ref='different-conversation')
        for child_id, parent_id, kind in [(child['id'], parent['id'], 'app_conversation'),
                                          (parent['id'], child['id'], 'snapshot_replay'),
                                          (child['id'], child['id'], 'snapshot_replay')]:
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.hub.record_lineage(self.project, child_id, parent_id, kind, 'Synthetic observed relation.')
        replay = self.hub.record_lineage(self.project, child['id'], parent['id'], 'snapshot_replay',
                                         'Coordinator reported copied context, not native resume.', 'Attachments omitted.')
        self.assertEqual(replay['omitted_context'], 'Attachments omitted.')
        self.assertFalse(replay['replay_performed'])

    def test_report_is_bounded_scoped_and_inert(self):
        job = self.returned()
        review = self.envelope(job)
        review['findings'][0]['claim'] = '<script>fetch("https://evil.invalid")</script>'
        self.record(job, review)
        with patch('subprocess.Popen', side_effect=AssertionError('No process')), patch('socket.create_connection', side_effect=AssertionError('No network')):
            report = self.hub.comparison_report(self.project, [job['id']])
        self.assertIn('&lt;script&gt;', report['content'])
        self.assertNotIn('<script>', report['content'])
        self.assertFalse(report['published'])
        self.assertFalse(report['sent'])
        for ids in [[], [job['id']]*2, ['missing']]:
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                self.hub.comparison_report(self.project, ids)
        with self.assertRaises(ValueError):
            self.hub.comparison_report(str(self.fixture.other_project), [job['id']])

    def test_cli_report_does_not_overwrite_or_export_outside_project(self):
        job = self.returned()
        request = self.fixture.root / 'request.json'
        request.write_text(json.dumps({'project': self.project, 'job_ids': [job['id']], 'format': 'markdown'}), encoding='utf-8')
        output = self.fixture.project / 'report.md'
        args = ['--state-dir', str(self.hub.state), 'report', str(request), '--output', str(output)]
        with patch('builtins.print'):
            self.assertEqual(cli.main(args), 0)
            original = output.read_bytes()
            self.assertEqual(cli.main(args), 2)
            self.assertEqual(output.read_bytes(), original)
            args[-1] = str(self.fixture.other_project/'report.md')
            self.assertEqual(cli.main(args), 2)
            self.assertFalse(Path(args[-1]).exists())


if __name__ == '__main__':
    unittest.main()
